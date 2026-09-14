"""Маршруты конвейера подготовки данных закрыты от рядового пользователя.

Модель доступа в системе построена на уровне ДАШБОРДОВ (гранты, whitelist
виджетов) и на уровне СТРОК (data_row_acl). Под ними лежит слой сырых данных:
выпуски датасетов, задания распознавания, справочник полей и список показателей.
Он не имеет своей проверки прав вовсе — только принадлежность к организации,
поэтому рядовой пользователь с доступом к ОДНОМУ дашборду мог одним запросом
прочитать значения всех объектов организации мимо грантов.

Эти экраны в интерфейсе и так доступны только модератору и администратору
(разделы «Объекты», «Загрузка», «Метрики» помечены staffOnly в App.tsx),
поэтому закрытие зависимостью manage ничего не ломает у зрителя.

Здесь проверяется именно граница доступа, а не поведение самих эндпоинтов:
зрителю — отказ, управляющему — работа."""
import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")

from conftest import db

# 403 — роль не подходит; 404 — объект «не существует» для этого пользователя.
# Оба ответа означают «не пустили»; главное, чтобы не было 200 с данными.
DENIED = {403, 404}


async def test_viewer_cannot_read_raw_releases(client, admin_headers, viewer, seed_dataset):
    """Сырые выпуски и значения: зрителю закрыто, управляющему открыто."""
    async with db.acquire() as conn:
        obj = str(await conn.fetchval("select id from objects where name='t_obj'"))
        rel = str(await conn.fetchval(
            "select id from dataset_releases where code='t_ds' order by created_at desc limit 1"))

    vh = viewer["headers"]

    # Список выпусков объекта
    r = await client.get(f"/objects/{obj}/dataset-releases", headers=vh)
    assert r.status_code in DENIED, f"зритель получил список выпусков: {r.status_code} {r.text[:200]}"
    assert (await client.get(f"/objects/{obj}/dataset-releases", headers=admin_headers)).status_code == 200

    # Сам выпуск со значениями — то, ради чего находка и заведена
    r = await client.get(f"/dataset-releases/{rel}", headers=vh)
    assert r.status_code in DENIED, f"зритель прочитал значения выпуска: {r.status_code}"
    ok = await client.get(f"/dataset-releases/{rel}", headers=admin_headers)
    assert ok.status_code == 200 and "values" in ok.json()

    # Справочник канонических полей объекта
    assert (await client.get(f"/objects/{obj}/canonical-fields", headers=vh)).status_code in DENIED
    assert (await client.get(f"/objects/{obj}/canonical-fields", headers=admin_headers)).status_code == 200


async def test_release_limit_is_bounded(client, admin_headers, seed_dataset):
    """limit не безграничен: в базе миллионы строк, и один запрос не должен
    поднимать их в память приложения целиком."""
    async with db.acquire() as conn:
        rel = str(await conn.fetchval(
            "select id from dataset_releases where code='t_ds' order by created_at desc limit 1"))

    assert (await client.get(f"/dataset-releases/{rel}?limit=5000", headers=admin_headers)).status_code == 200
    # Выше потолка и ниже единицы — отказ проверки параметров, а не молчаливое усечение
    assert (await client.get(f"/dataset-releases/{rel}?limit=5001", headers=admin_headers)).status_code == 422
    assert (await client.get(f"/dataset-releases/{rel}?limit=100000", headers=admin_headers)).status_code == 422
    assert (await client.get(f"/dataset-releases/{rel}?limit=0", headers=admin_headers)).status_code == 422


async def test_viewer_cannot_read_pipeline_and_metrics(client, admin_headers, viewer, seed_dataset):
    """Задания распознавания, папки объекта и список показателей."""
    async with db.acquire() as conn:
        obj = str(await conn.fetchval("select id from objects where name='t_obj'"))
    vh = viewer["headers"]

    # Папки объекта: у зрителя фильтра «Папка» нет вовсе, запрос не нужен
    assert (await client.get(f"/objects/{obj}/folders", headers=vh)).status_code in DENIED
    assert (await client.get(f"/objects/{obj}/folders", headers=admin_headers)).status_code == 200

    # Показатели организации и их значения — содержательный результат работы платформы
    assert (await client.get("/metrics", headers=vh)).status_code in DENIED
    assert (await client.get("/metrics/values", headers=vh)).status_code in DENIED
    assert (await client.get("/metrics", headers=admin_headers)).status_code == 200

    # Несуществующее задание распознавания: зритель не должен отличать
    # «нет такого» от «есть, но не для вас» — оба ответа внутри DENIED
    fake = "00000000-0000-0000-0000-000000000000"
    assert (await client.get(f"/extraction-jobs/{fake}", headers=vh)).status_code in DENIED
