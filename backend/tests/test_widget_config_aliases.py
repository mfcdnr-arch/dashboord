"""Конфигурация виджетов: `value_field` и `value_fields` взаимозаменяемы.

Исторически одни типы виджетов ждут одно поле (`value_field`), другие — набор
(`value_fields`). Из-за этого корректно заполненный конфиг мог получить ответ
«укажите value_fields» (финальный аудит). Расчёт принимает обе формы.
"""
import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def _preview(client, headers, wtype, config):
    return await client.post("/widgets/preview", headers=headers,
                             json={"widget_type": wtype, "name": wtype, "config": config})


@pytest.mark.parametrize("wtype", ["compare", "heatmap", "pivot"])
async def test_multi_field_widgets_accept_single_value_field(client, admin_headers, seed_dataset, wtype):
    r = await _preview(client, admin_headers, wtype,
                       {"dataset_code": seed_dataset["code"], "value_field": "plan"})
    assert r.status_code == 200, r.text


@pytest.mark.parametrize("wtype", ["kpi", "bar", "line", "pie"])
async def test_single_field_widgets_accept_value_fields_list(client, admin_headers, seed_dataset, wtype):
    r = await _preview(client, admin_headers, wtype,
                       {"dataset_code": seed_dataset["code"], "value_fields": ["plan"]})
    assert r.status_code == 200, r.text


async def test_native_forms_still_work(client, admin_headers, seed_dataset):
    r = await _preview(client, admin_headers, "kpi",
                       {"dataset_code": seed_dataset["code"], "value_field": "plan"})
    assert r.status_code == 200, r.text
    r = await _preview(client, admin_headers, "compare",
                       {"dataset_code": seed_dataset["code"], "value_fields": ["plan", "fact"]})
    assert r.status_code == 200, r.text
