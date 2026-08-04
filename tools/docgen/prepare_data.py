#!/usr/bin/env python3
"""Временные данные для скриншотов документации (и их уборка).

Генератор документации снимает интерфейс на ЖИВОЙ системе. Часть разделов
(витрины, обращения, аномалии) невозможно показать на пустой базе, поэтому
здесь заводятся временные сущности с префиксом `zdoc_`, а после съёмки
удаляются тем же скриптом с флагом --cleanup.

    python3 prepare_data.py            # создать
    python3 prepare_data.py --cleanup  # удалить

Требуется поднятый dev-стек и API на http://localhost:8080 (scripts/dev-api.sh
или docker compose -p dashbord up -d), учётка admin/admin.
"""
from __future__ import annotations

import argparse
import datetime as dt
import io
import json
import sys
import time

import httpx

API = "http://localhost:8080"
ADMIN = ("admin", "admin")
PREFIX = "zdoc_"
STATE = "/tmp/dashbord_docgen_state.json"


def client() -> httpx.Client:
    c = httpx.Client(base_url=API, timeout=120)
    r = c.post("/auth/login", data={"username": ADMIN[0], "password": ADMIN[1]})
    r.raise_for_status()
    c.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    return c


def _xlsx(rows: list[tuple]) -> bytes:
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.append(["Услуга", "План", "Факт"])
    for r in rows:
        ws.append(list(r))
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def create(c: httpx.Client) -> dict:
    state: dict = {}

    # 1. Объект + папка + три периода данных (для динамики с выбросом)
    obj = c.post("/objects", json={"name": f"{PREFIX}Объект для документации"}).json()
    state["object"] = obj["id"]
    folder = c.post(f"/objects/{obj['id']}/folders", json={"name": "Отчёты"}).json()
    state["folder"] = folder["id"]

    periods = [
        ("2026-01-01", [("Выдача паспорта", 100, 96), ("Регистрация брака", 40, 42), ("Справка о доходах", 70, 68)]),
        ("2026-02-01", [("Выдача паспорта", 105, 110), ("Регистрация брака", 42, 39), ("Справка о доходах", 72, 75)]),
        ("2026-03-01", [("Выдача паспорта", 110, 108), ("Регистрация брака", 44, 46), ("Справка о доходах", 74, 300)]),
    ]
    for period, rows in periods:
        up = c.post(f"/folders/{folder['id']}/documents",
                    files={"file": (f"{PREFIX}{period}.xlsx", _xlsx(rows),
                                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
                    data={"reporting_period_start": period})
        up.raise_for_status()
        job = c.post(f"/document-versions/{up.json()['version_id']}/extract").json()["job_id"]
        payload: dict = {}
        for _ in range(40):
            time.sleep(1.0)
            payload = c.get(f"/extraction-jobs/{job}").json()
            if payload.get("status") in ("succeeded", "failed"):
                break
        if payload.get("status") != "succeeded":
            raise SystemExit(f"распознавание не удалось: {payload.get('error_message')}")
        table = payload["tables"][0]["id"]
        rel = c.post(f"/extraction-jobs/{job}/release", json={
            "table_id": table, "code": f"{PREFIX}uslugi", "name": "Услуги центра",
            "reporting_period_start": period,
            "fields": [
                {"column_index": 0, "field_code": "service", "field_name": "Услуга", "data_type": "text", "is_row_label": True},
                {"column_index": 1, "field_code": "plan", "field_name": "План", "data_type": "number"},
                {"column_index": 2, "field_code": "fact", "field_name": "Факт", "data_type": "number"},
            ]})
        rel.raise_for_status()
    state["dataset"] = f"{PREFIX}uslugi"

    # 2. Дашборд в папке объекта + виджет динамики с включёнными аномалиями
    dash = c.post("/dashboards", json={"name": f"{PREFIX}Услуги центра", "folder_id": folder["id"]}).json()
    state["dashboard"] = dash["id"]
    page = c.post(f"/dashboards/{dash['id']}/pages", json={"name": "Обзор"}).json()
    state["page"] = page["id"]
    c.post(f"/dashboard-pages/{page['id']}/widgets", json={
        "name": "Динамика: Факт (с аномалиями)", "widget_type": "dynamics",
        "config": {"dataset_code": state["dataset"], "value_field": "fact", "trend": True,
                   "anomalies": True, "anomaly_threshold": 2},
        "position_x": 0, "position_y": 0, "width": 8, "height": 7}).raise_for_status()
    c.post(f"/dashboard-pages/{page['id']}/widgets", json={
        "name": "Σ Факт", "widget_type": "kpi",
        "config": {"dataset_code": state["dataset"], "value_field": "fact", "target": 500},
        "position_x": 8, "position_y": 0, "width": 4, "height": 3}).raise_for_status()

    # 3. Витрина из двух дашбордов (наш + любой существующий с виджетами)
    sc = c.post("/showcases", json={"name": f"{PREFIX}Оперативная сводка"}).json()
    state["showcase"] = sc["id"]
    c.post(f"/showcases/{sc['id']}/items", json={"dashboard_id": dash["id"]}).raise_for_status()
    for d in c.get("/dashboards").json()["items"]:
        if d["id"] != dash["id"] and (d.get("pages") or 0) > 0:
            r = c.post(f"/showcases/{sc['id']}/items", json={"dashboard_id": d["id"]})
            if r.status_code < 300:
                break

    # 4. Временный пользователь + обращение от него (тред для скриншота)
    roles = {r["code"]: r["id"] for r in c.get("/roles").json()}
    u = c.post("/users", json={"login": f"{PREFIX}operator", "password": "DocGen2026",
                               "last_name": "Иванова", "first_name": "Мария",
                               "role_ids": [roles["user"]]}).json()
    state["user"] = u["id"]
    uc = httpx.Client(base_url=API, timeout=60)
    tok = uc.post("/auth/login", data={"username": f"{PREFIX}operator", "password": "DocGen2026"}).json()["access_token"]
    uc.headers["Authorization"] = f"Bearer {tok}"
    uc.post("/auth/change-password", json={"new_password": "DocGen2026x"})
    tok = uc.post("/auth/login", data={"username": f"{PREFIX}operator", "password": "DocGen2026x"}).json()["access_token"]
    uc.headers["Authorization"] = f"Bearer {tok}"
    ap = uc.post("/appeals", json={"subject": "Нет доступа к дашборду «Услуги центра»",
                                   "body": "Добрый день! Мне нужен доступ к дашборду по услугам центра "
                                           "для подготовки еженедельного отчёта. Спасибо."}).json()
    state["appeal"] = ap["id"]
    c.post(f"/appeals/{ap['id']}/messages", json={"body": "Здравствуйте! Доступ выдан, проверьте раздел «Дашборды»."})

    json.dump(state, open(STATE, "w"))
    print("Создано:", json.dumps(state, ensure_ascii=False, indent=2))
    return state


def cleanup(c: httpx.Client) -> None:
    try:
        state = json.load(open(STATE))
    except FileNotFoundError:
        state = {}
    if state.get("showcase"):
        c.delete(f"/showcases/{state['showcase']}")
    if state.get("user"):
        c.delete(f"/users/{state['user']}")
    # дашборд/объект/датасет удаляем напрямую в БД (API удаления дашборда нет by design)
    print("Удалены витрина и временный пользователь. Остальное — SQL-скриптом ниже:")
    print(f"""
docker exec -e PGPASSWORD=dashbord dashbord_postgres psql -U dashbord -d dashbord <<'SQL'
delete from widgets where page_id in (select id from dashboard_pages where dashboard_id in
  (select id from dashboards where name like '{PREFIX}%'));
delete from dashboard_pages where dashboard_id in (select id from dashboards where name like '{PREFIX}%');
delete from dashboards where name like '{PREFIX}%';
delete from dataset_values where dataset_release_id in (select id from dataset_releases where code like '{PREFIX}%');
delete from dataset_release_fields where dataset_release_id in (select id from dataset_releases where code like '{PREFIX}%');
delete from dataset_releases where code like '{PREFIX}%';
delete from extracted_columns where extracted_table_id in (select id from extracted_tables where extraction_job_id in
  (select id from extraction_jobs where document_version_id in (select id from document_versions where document_id in
    (select id from documents where original_filename like '{PREFIX}%'))));
delete from extracted_tables where extraction_job_id in (select id from extraction_jobs where document_version_id in
  (select id from document_versions where document_id in (select id from documents where original_filename like '{PREFIX}%')));
delete from extraction_jobs where document_version_id in (select id from document_versions where document_id in
  (select id from documents where original_filename like '{PREFIX}%'));
delete from document_versions where document_id in (select id from documents where original_filename like '{PREFIX}%');
delete from documents where original_filename like '{PREFIX}%';
delete from canonical_fields where object_id in (select id from objects where name like '{PREFIX}%');
delete from folders where object_id in (select id from objects where name like '{PREFIX}%');
delete from objects where name like '{PREFIX}%';
delete from appeal_messages where appeal_id in (select id from appeals where subject like '%Услуги центра%');
delete from appeals where subject like '%Услуги центра%';
SQL
""")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--cleanup", action="store_true")
    args = ap.parse_args()
    c = client()
    if args.cleanup:
        cleanup(c)
    else:
        create(c)
    sys.exit(0)
