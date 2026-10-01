"""Новые графы формы: правило, журнал и уведомление (этап 5, решение 23.09.2026).

«В форме появилась новая графа — добавить виджет?». Форма со временем
прирастает графами (у ежедневного отчёта РЦО — новые услуги ведомств, около двух
раз в месяц), а дашборд остаётся прежним, и узнать об этом можно было только
сверив их вручную.

Правило — здесь и только здесь. Графа кода X новая, если:
  1. у X больше одного выпуска — первый выпуск формы это «новая форма», её
     обслуживает предложение виджетов на «📥 Загрузке» (этап 4);
  2. у графы есть ЧИСЛО в самом свежем активном выпуске X по отчётному периоду.
     Число, а не «ненулевое»: новые услуги РЦО в первый день все нули, а
     ненулевое правило потеряло бы настоящий рост формы. Число отсекает столбец
     названий строк (значений у него нет), пустые и текстовые графы;
  3. её нет ни в одном ДРУГОМ выпуске X — любого статуса. Снятый выпуск тоже
     значит «графу уже видели»: иначе перевыпуск того же периода с «Заместить»
     объявлял бы её второй раз. Загрузка истории сюда же не попадает — её выпуск
     не самый свежий; графа, всплывшая только в старых месяцах, — прошлое, а не
     новость. Возврат прежней графы тоже гасится этим условием;
  4. о ней ещё не объявляли (журнал `dataset_new_fields`): удалённый выпуск
     уносит свои объявления граф, и без журнала графа ожила бы снова;
  5. у неё есть имя: «Столбец N» — безымянный столбец разметки, его код
     сдвигается при каждом росте формы, и объявлять его значило бы повторять
     одно и то же при каждом новом столбце.

Переименование заголовка даёт новый код графы (код выводится из имени), и
правило примет его за новую графу — на РЦО так выглядели 4 события из 19.
Подавлять такое по догадке нельзя (настоящий рост однажды сочтётся
переименованием), поэтому объявление честно называет, сколько граф с числами
было в прошлом отчёте и пропало в этом: «пропало столько же — возможно, графы
переименованы».

Повторная проверка безопасна (журнал), поэтому зовут её несколько путей:
ручной выпуск, выпуск по листам — один раз на книгу, недельный загрузчик
ведомств и ежедневная страховка воркера.
"""
from __future__ import annotations

import logging
import re
from typing import List, Optional

from ..notifications import service as notif

log = logging.getLogger(__name__)

EVENT = "data.new_fields"

# Безымянный столбец разметки (analyze.py: f"Столбец {c + 1}").
_UNNAMED = re.compile(r"^\s*Столбец\s+\d+\s*$")

# Сколько граф перечислять в самом уведомлении. Остальные называются числом —
# полный список откроется в окне дашборда.
PAYLOAD_FIELDS = 40
PAYLOAD_DASHBOARDS = 10


def is_unnamed(name: Optional[str]) -> bool:
    return bool(name and _UNNAMED.match(name))


async def _releases(conn, org_id, code: str) -> list:
    """Два самых свежих активных выпуска кода — по отчётному периоду."""
    return await conn.fetch(
        "select id, object_id, reporting_period_start as period from dataset_releases "
        "where organization_id=$1 and code=$2 and status <> 'superseded' "
        "order by reporting_period_start desc nulls last, created_at desc limit 2",
        org_id, code)


async def _numeric_codes(conn, release_id) -> set:
    rows = await conn.fetch(
        "select distinct canonical_field_code as c from dataset_values "
        "where dataset_release_id=$1 and value_number is not null", release_id)
    return {r["c"] for r in rows}


async def detect(conn, org_id, code: str) -> Optional[dict]:
    """Новые графы самого свежего выпуска кода или None.

    Только читает: ни журнала, ни уведомления. Отдельно от `announce`, чтобы
    правило можно было проверить, ничего не записав.
    """
    total = await conn.fetchval(
        "select count(*) from dataset_releases where organization_id=$1 and code=$2", org_id, code)
    if (total or 0) < 2:
        return None
    rel = await _releases(conn, org_id, code)
    if not rel:
        return None
    latest = rel[0]
    # «Нет ни в одном другом выпуске»: и по объявленным графам, и по значениям.
    # Объявлений может не оказаться у выпусков, записанных в обход
    # build_release до 23.09 (их дописывал backfill_release_fields), а по
    # значениям не видно граф, у которых в прошлом не было ни одного числа.
    rows = await conn.fetch(
        "with others as (select id from dataset_releases "
        "                where organization_id=$2 and code=$3 and id <> $1), "
        "cand as (select distinct canonical_field_code as c from dataset_values "
        "         where dataset_release_id=$1 and value_number is not null) "
        "select cand.c, cf.name from cand "
        "left join canonical_fields cf on cf.object_id=$4 and cf.code=cand.c "
        "where not exists (select 1 from dataset_release_fields f "
        "                  where f.dataset_release_id in (select id from others) "
        "                    and f.canonical_field_code = cand.c) "
        "  and not exists (select 1 from dataset_values v "
        "                  where v.dataset_release_id in (select id from others) "
        "                    and v.canonical_field_code = cand.c) "
        "  and not exists (select 1 from dataset_new_fields n "
        "                  where n.organization_id=$2 and n.code=$3 and n.field_code = cand.c) "
        "order by cf.name nulls last, cand.c",
        latest["id"], org_id, code, latest["object_id"])
    fields = [{"code": r["c"], "name": r["name"] or r["c"]} for r in rows
              if not is_unnamed(r["name"] or r["c"])]
    if not fields:
        return None

    # Сколько граф с числами было в прошлом отчёте и пропало в этом —
    # подсказка, что «новые» могут оказаться переименованными.
    gone = 0
    if len(rel) > 1:
        before = await _numeric_codes(conn, rel[1]["id"])
        now = await _numeric_codes(conn, latest["id"])
        lost = before - now
        if lost:
            names = await conn.fetch(
                "select code, name from canonical_fields where object_id=$1 and code = any($2::text[])",
                latest["object_id"], list(lost))
            named = {r["code"]: r["name"] for r in names}
            gone = sum(1 for c in lost if not is_unnamed(named.get(c) or c))
    return {
        "release_id": latest["id"], "object_id": latest["object_id"],
        "period": latest["period"], "fields": fields, "gone": gone,
    }


async def watching_dashboards(conn, org_id, code: str) -> List[dict]:
    """Не архивные дашборды, которые смотрят форму и не отключили подсказку.

    Смотрит — значит хотя бы один виджет стоит на этом коде (прямо или в
    сравнении источников). Тумблер «💡 Подсказки о показателях» у дашборда
    выключен — значит человек просил не напоминать.
    """
    rows = await conn.fetch(
        "select distinct d.id, d.name from dashboards d join widgets w on w.dashboard_id = d.id "
        "where d.organization_id=$1 and d.publication_status <> 'archived' and d.suggest_new_fields "
        "  and (w.config->>'dataset_code' = $2 "
        "       or exists (select 1 from jsonb_array_elements("
        "             case when jsonb_typeof(w.config->'series') = 'array' "
        "                  then w.config->'series' else '[]'::jsonb end) s "
        "           where s->>'dataset_code' = $2)) "
        "order by d.name", org_id, code)
    return [{"id": str(r["id"]), "name": r["name"]} for r in rows]


async def editor_user_ids(conn, org_id) -> list:
    """Кому уведомление: те, кто может добавить виджет (те же роли, что `manage`).

    Не `management_user_ids`: туда входит старший модератор, а добавлять
    виджеты ему нельзя — уведомление «добавить виджет?» было бы для него тупиком.
    """
    rows = await conn.fetch(
        "select distinct u.id from users u join user_roles ur on ur.user_id = u.id "
        "join roles r on r.id = ur.role_id "
        "where u.organization_id=$1 and u.is_active and r.code in ('superadmin','admin','moderator')",
        org_id)
    return [r["id"] for r in rows]


async def announce(conn, org_id, code: str) -> Optional[dict]:
    """Найти новые графы кода, записать в журнал и, если форму смотрит
    дашборд, уведомить. Возвращает то, что объявлено, или None.

    Повторный вызов ничего не делает: объявленные графы уже в журнале.
    """
    found = await detect(conn, org_id, code)
    if found is None:
        return None
    obj_name = await conn.fetchval("select name from objects where id=$1", found["object_id"]) \
        if found["object_id"] else None
    dashboards = await watching_dashboards(conn, org_id, code)

    notice_id = None
    if dashboards and found["object_id"]:
        fields = found["fields"]
        payload = {
            "dataset_code": code,
            "object_id": str(found["object_id"]),
            "object_name": obj_name,
            "period": found["period"],
            "release_id": str(found["release_id"]),
            "fields": fields[:PAYLOAD_FIELDS],
            "total": len(fields),
            "gone": found["gone"],
            "dashboards": dashboards[:PAYLOAD_DASHBOARDS],
            "dashboards_total": len(dashboards),
        }
        users = await editor_user_ids(conn, org_id)
        notice_id = await notif.notify(conn, org_id, EVENT, "object", found["object_id"], payload, users)

    for f in found["fields"]:
        await conn.execute(
            "insert into dataset_new_fields(organization_id, object_id, code, field_code, field_name, "
            "release_id, period, notice_id) values($1,$2,$3,$4,$5,$6,$7,$8) "
            "on conflict (organization_id, code, field_code) do nothing",
            org_id, found["object_id"], code, f["code"], f["name"], found["release_id"],
            found["period"], notice_id)
    return {**found, "object_name": obj_name, "dashboards": dashboards,
            "notice_id": str(notice_id) if notice_id else None}


async def announce_safely(conn, org_id, code: str) -> Optional[dict]:
    """`announce` для путей выпуска: сбой объявления не отменяет выпуск.

    Объявление — подсказка, а подсказка не вправе сорвать работу человека
    (урок 02.09: сбой проверки качества внутри транзакции откатывал сам
    выпуск). Точка сохранения откатывает только объявление; цена — сломанное
    правило молча перестанет объявлять, и узнать об этом можно из лога, а
    ежедневная страховка воркера попробует ещё раз.
    """
    try:
        async with conn.transaction():
            return await announce(conn, org_id, code)
    except Exception:  # noqa: BLE001 — см. докстринг: подсказка не роняет выпуск
        log.exception("Объявление новых граф формы %s не удалось", code)
        return None


def brief(res: Optional[dict]) -> Optional[dict]:
    """Что вернуть экрану выпуска: сколько новых граф и кто о них узнал."""
    if not res:
        return None
    return {"total": len(res["fields"]), "fields": [f["name"] for f in res["fields"][:PAYLOAD_FIELDS]],
            "gone": res["gone"], "notified": bool(res.get("notice_id")),
            "dashboards": [d["name"] for d in res["dashboards"][:PAYLOAD_DASHBOARDS]]}


async def check_all(conn, org_id) -> list:
    """Страховка воркера: пройти все формы организации.

    Пути выпуска зовут `announce` сами, но не все (недельный загрузчик ведомств
    пишет мимо `build_release`), и ежедневный проход ловит остальное.
    """
    codes = await conn.fetch(
        "select code from dataset_releases where organization_id=$1 "
        "group by code having count(*) > 1 order by code", org_id)
    out = []
    for r in codes:
        # Безопасный вызов: сбой одной формы не должен срывать проверку остальных.
        res = await announce_safely(conn, org_id, r["code"])
        if res:
            out.append({"code": r["code"], "fields": len(res["fields"])})
    return out
