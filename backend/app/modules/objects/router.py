"""Модуль «Объекты»: объекты и папки внутри них.

Объект — верхний контейнер; внутри объекта заводятся папки, куда позже
загружаются документы. Управляют admin/moderator; чтение — любой авторизованный.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from ... import db
from ..audit.service import write_event
from ..auth.deps import get_current_user, require_roles
from . import analytics

router = APIRouter(prefix="/objects", tags=["objects"])

manage = require_roles("superadmin", "admin", "moderator")


class ObjectIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: Optional[str] = None


class ObjectPatch(BaseModel):
    """Частичное обновление объекта: меняются только переданные поля.

    Отличать «поле не передано» от «поле очищено» позволяет exclude_unset —
    поэтому description/code можно и задать, и стереть (передав null).
    """
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    code: Optional[str] = Field(default=None, max_length=100)
    description: Optional[str] = None


class FolderIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    parent_folder_id: Optional[str] = None


class FolderPatch(BaseModel):
    name: Optional[str] = Field(default=None, max_length=200)
    # Готовить ли выпуск автоматически: распознавать новый файл и подставлять
    # разметку прошлого выпуска. Сам выпуск всё равно подтверждает человек.
    auto_prepare: Optional[bool] = None


@router.get("")
async def list_objects(user: dict = Depends(get_current_user)):
    async with db.get_pool().acquire() as conn:
        rows = await conn.fetch(
            "select o.id, o.name, o.code, o.description, o.created_at, "
            "(select count(*) from folders f where f.object_id = o.id) as folders_count "
            "from objects o where o.organization_id = $1 order by o.name",
            user["organization_id"],
        )
    return [dict(r) for r in rows]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_object(data: ObjectIn, user: dict = Depends(manage)):
    async with db.get_pool().acquire() as conn:
        exists = await conn.fetchval(
            "select 1 from objects where organization_id=$1 and name=$2",
            user["organization_id"], data.name,
        )
        if exists:
            raise HTTPException(status.HTTP_409_CONFLICT, "Объект с таким именем уже есть")
        row = await conn.fetchrow(
            "insert into objects(organization_id, name, description, created_by) "
            "values($1,$2,$3,$4) returning id, name, description, created_at",
            user["organization_id"], data.name, data.description, user["id"],
        )
    return dict(row)


@router.patch("/{object_id}")
async def update_object(object_id: str, data: ObjectPatch, user: dict = Depends(manage)):
    """Переименование объекта и правка кода/описания."""
    patch = data.model_dump(exclude_unset=True)
    if "name" in patch:
        patch["name"] = (patch["name"] or "").strip()
        if not patch["name"]:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Название не может быть пустым")
    if not patch:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Не передано ни одного поля")

    async with db.get_pool().acquire() as conn:
        old = await conn.fetchrow(
            "select name, code, description from objects where id=$1::uuid and organization_id=$2",
            object_id, user["organization_id"],
        )
        if not old:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Объект не найден")
        if "name" in patch and patch["name"] != old["name"]:
            dup = await conn.fetchval(
                "select 1 from objects where organization_id=$1 and name=$2 and id <> $3::uuid",
                user["organization_id"], patch["name"], object_id,
            )
            if dup:
                raise HTTPException(status.HTTP_409_CONFLICT, "Объект с таким именем уже есть")

        # Имена колонок берутся из полей ObjectPatch (фиксированный набор), не из
        # пользовательского ввода — подстановка в SQL безопасна.
        cols = list(patch.keys())
        sets = ", ".join(f"{c}=${i + 1}" for i, c in enumerate(cols))
        async with conn.transaction():
            row = await conn.fetchrow(
                f"update objects set {sets}, updated_at=now() where id=${len(cols) + 1}::uuid "
                "returning id, name, code, description, created_at",
                *[patch[c] for c in cols], object_id,
            )
            await write_event(
                conn, user["organization_id"], user["id"], "update", "object", object_id,
                old_data={c: old[c] for c in cols}, new_data=patch,
            )
    return dict(row)


@router.delete("/{object_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_object(object_id: str, user: dict = Depends(manage)):
    """Удаление объекта — только ПУСТОГО.

    В БД на объект завязаны каскады (canonical_fields, data_row_acl) и
    обнуление ссылок (folders.object_id, dataset_releases.object_id): «тихое»
    удаление уничтожило бы справочник полей и оторвало выпуски датасетов от
    объекта, а виджеты продолжили бы ссылаться в пустоту. Поэтому удаляем
    только когда внутри ничего нет, а иначе объясняем, что именно мешает.
    """
    async with db.get_pool().acquire() as conn:
        obj = await conn.fetchrow(
            "select name from objects where id=$1::uuid and organization_id=$2",
            object_id, user["organization_id"],
        )
        if not obj:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Объект не найден")

        c = await conn.fetchrow(
            "select (select count(*) from folders where object_id=$1::uuid) as folders,"
            " (select count(*) from canonical_fields where object_id=$1::uuid) as fields,"
            " (select count(*) from dataset_releases where object_id=$1::uuid) as releases,"
            " (select count(*) from data_row_acl where object_id=$1::uuid) as row_acl",
            object_id,
        )
        blockers = [
            f"{label}: {c[key]}"
            for key, label in (
                ("folders", "папок"), ("fields", "канонических полей"),
                ("releases", "выпусков датасетов"), ("row_acl", "правил доступа к строкам"),
            )
            if c[key]
        ]
        if blockers:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Объект не пустой, удаление отменено — сначала уберите содержимое ("
                + ", ".join(blockers) + ")",
            )

        async with conn.transaction():
            await write_event(
                conn, user["organization_id"], user["id"], "delete", "object", object_id,
                old_data={"name": obj["name"]},
            )
            await conn.execute("delete from objects where id=$1::uuid", object_id)


@router.get("/{object_id}/build-suggestion")
async def build_suggestion(object_id: str, user: dict = Depends(manage)):
    """Стоит ли предложить собрать дашборд по этому объекту.

    Данные копятся сами, а дашборда может не быть месяцами: человек не всегда
    знает, что система уже готова его собрать. Предлагаем, когда выпуски есть,
    а дашборда, который на них смотрит, нет.

    «Дашборд есть» считаем двумя способами сразу: он лежит в папке объекта
    (мастер теперь ставит папку сам) ИЛИ его виджеты ссылаются на коды
    датасетов объекта. Одного признака мало: дашборд могли собрать до
    автопривязки или перенести в другую папку.
    """
    org_id = user["organization_id"]
    async with db.get_pool().acquire() as conn:
        obj = await conn.fetchrow(
            "select id, name from objects where id=$1::uuid and organization_id=$2", object_id, org_id)
        if not obj:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Объект не найден")

        rel = await conn.fetchrow(
            "select count(*) as releases, count(distinct reporting_period_start) as periods, "
            "min(reporting_period_start) as first_period, max(reporting_period_start) as last_period, "
            "array_agg(distinct code) as codes "
            "from dataset_releases where object_id=$1::uuid and status <> 'superseded'", object_id)
        releases = int(rel["releases"] or 0)
        codes = [c for c in (rel["codes"] or []) if c]
        if not releases:
            return {"suggest": False, "reason": "no_data", "releases": 0, "periods": 0}

        in_folder = await conn.fetchval(
            "select count(*) from dashboards d join folders f on f.id = d.folder_id "
            "where f.object_id=$1::uuid and d.publication_status <> 'archived'", object_id)
        by_widget = await conn.fetchval(
            "select count(distinct w.dashboard_id) from widgets w "
            "where w.organization_id=$1 and w.config->>'dataset_code' = any($2::text[])",
            org_id, codes) if codes else 0
        existing = int(in_folder or 0) + int(by_widget or 0)

        return {
            "suggest": existing == 0,
            "reason": "has_dashboard" if existing else "ready",
            "object_name": obj["name"],
            "releases": releases,
            "periods": int(rel["periods"] or 0),
            "first_period": rel["first_period"].isoformat() if rel["first_period"] else None,
            "last_period": rel["last_period"].isoformat() if rel["last_period"] else None,
            "dataset_codes": codes,
            "dashboards": existing,
        }


@router.get("/{object_id}/folders")
async def list_folders(object_id: str, user: dict = Depends(get_current_user)):
    async with db.get_pool().acquire() as conn:
        obj = await conn.fetchval(
            "select 1 from objects where id=$1::uuid and organization_id=$2",
            object_id, user["organization_id"],
        )
        if not obj:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Объект не найден")
        rows = await conn.fetch(
            "select id, name, parent_folder_id, auto_prepare, created_at from folders "
            "where object_id=$1::uuid order by name",
            object_id,
        )
    return [dict(r) for r in rows]


@router.get("/{object_id}/folders/{folder_id}/analytics")
async def folder_analytics(object_id: str, folder_id: str, user: dict = Depends(manage)):
    """Аналитика по папке (п. 8): свод показателей, состояние данных, что
    построено и что нет, сравнение объектов. Значения считаются тем же путём,
    что и у виджетов, — экран не может разойтись с дашбордом."""
    async with db.get_pool().acquire() as conn:
        try:
            data = await analytics.folder_analytics(conn, user["organization_id"], folder_id)
        except analytics.AnalyticsError as e:
            raise HTTPException(status.HTTP_404_NOT_FOUND, str(e))
    if data["folder"]["object_id"] != object_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Папка не найдена в этом объекте")
    return data


@router.post("/{object_id}/folders", status_code=status.HTTP_201_CREATED)
async def create_folder(object_id: str, data: FolderIn, user: dict = Depends(manage)):
    async with db.get_pool().acquire() as conn:
        obj = await conn.fetchval(
            "select 1 from objects where id=$1::uuid and organization_id=$2",
            object_id, user["organization_id"],
        )
        if not obj:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Объект не найден")
        row = await conn.fetchrow(
            "insert into folders(organization_id, object_id, parent_folder_id, name, created_by) "
            "values($1,$2::uuid,$3::uuid,$4,$5) returning id, name, parent_folder_id, created_at",
            user["organization_id"], object_id, data.parent_folder_id, data.name, user["id"],
        )
    return dict(row)


async def _folder_of_object(conn, object_id: str, folder_id: str, org_id):
    """Папка запрошенного объекта в организации пользователя либо 404."""
    row = await conn.fetchrow(
        "select id, name, auto_prepare from folders "
        "where id=$1::uuid and object_id=$2::uuid and organization_id=$3",
        folder_id, object_id, org_id,
    )
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Папка не найдена")
    return row


@router.patch("/{object_id}/folders/{folder_id}")
async def update_folder(object_id: str, folder_id: str, data: FolderPatch, user: dict = Depends(manage)):
    """Правка папки: имя и признак автоподготовки выпуска.

    Частичность как у объекта: передаём только то, что меняем, — галочку можно
    переключить, не трогая название.
    """
    patch = data.model_dump(exclude_unset=True)
    if not patch:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Нечего изменять")
    name = (patch.get("name") or "").strip() if "name" in patch else None
    if "name" in patch and not name:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Название не может быть пустым")

    async with db.get_pool().acquire() as conn:
        old = await _folder_of_object(conn, object_id, folder_id, user["organization_id"])
        sets, params = [], []
        if name is not None:
            params.append(name); sets.append(f"name=${len(params)}")
        if "auto_prepare" in patch:
            params.append(bool(patch["auto_prepare"])); sets.append(f"auto_prepare=${len(params)}")
        params.append(folder_id)
        async with conn.transaction():
            row = await conn.fetchrow(
                f"update folders set {', '.join(sets)} where id=${len(params)}::uuid "
                "returning id, name, parent_folder_id, auto_prepare, created_at",
                *params,
            )
            await write_event(
                conn, user["organization_id"], user["id"], "update", "folder", folder_id,
                old_data={"name": old["name"], "auto_prepare": old.get("auto_prepare")},
                new_data={k: v for k, v in patch.items()},
            )
    return dict(row)


@router.delete("/{object_id}/folders/{folder_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_folder(object_id: str, folder_id: str, user: dict = Depends(manage)):
    """Удаление папки — только ПУСТОЙ (как и объекта, по тем же причинам).

    Ссылки documents.folder_id и dashboards.folder_id обнуляются каскадом
    (`on delete set null`), то есть документы и дашборды не исчезли бы, но
    молча потеряли бы место в структуре — это не то, чего ждёт пользователь.
    """
    async with db.get_pool().acquire() as conn:
        folder = await _folder_of_object(conn, object_id, folder_id, user["organization_id"])
        c = await conn.fetchrow(
            "select (select count(*) from folders where parent_folder_id=$1::uuid) as subfolders,"
            " (select count(*) from documents where folder_id=$1::uuid) as documents,"
            " (select count(*) from dashboards where folder_id=$1::uuid) as dashboards",
            folder_id,
        )
        blockers = [
            f"{label}: {c[key]}"
            for key, label in (
                ("subfolders", "вложенных папок"), ("documents", "документов"),
                ("dashboards", "дашбордов"),
            )
            if c[key]
        ]
        if blockers:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Папка не пустая, удаление отменено — сначала уберите содержимое ("
                + ", ".join(blockers) + ")",
            )

        async with conn.transaction():
            await write_event(
                conn, user["organization_id"], user["id"], "delete", "folder", folder_id,
                old_data={"name": folder["name"]},
            )
            # Папка — securable: снимаем её запись контура доступа, иначе
            # останется висячая строка (FK там логический), а привязанные к ней
            # object_acl уйдут каскадом сами.
            await conn.execute(
                "delete from securable_objects where object_type='folder' and object_id=$1::uuid",
                folder_id,
            )
            await conn.execute("delete from folders where id=$1::uuid", folder_id)
