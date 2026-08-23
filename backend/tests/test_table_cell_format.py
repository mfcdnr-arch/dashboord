"""Условное форматирование ячеек таблицы (п. 2 списка предложений).

Главное, что проверяем: у таблицы НЕТ своих правил. Цвет считается той же
`config["alerts"]` и тем же сравнением, что красит карточку показателя, —
иначе одно и то же число окрасилось бы в карточке одним цветом, а в таблице
другим, и спорить пришлось бы уже о цветах, а не о данных.
"""
import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")

from app.modules.dashboards._alerts import cell_alert_levels, evaluate_alert
from conftest import purge_dashboard

# Ниже 60 — красный, ниже 100 — жёлтый, дальше зелёный. Порядок значим:
# срабатывает ПЕРВОЕ подошедшее правило.
RULES = [
    {"level": "danger", "op": "lt", "value": 60},
    {"level": "warn", "op": "lt", "value": 100},
    {"level": "good", "op": "gte", "value": 100},
]


def test_cells_use_the_same_rules_as_the_kpi_card():
    """Одно и то же число в таблице и на карточке получает ОДИН уровень."""
    cfg = {"alerts": RULES, "cell_format": {"fact": "alert"}}
    rows = [{"row": "Паспорт", "plan": 100, "fact": 90},
            {"row": "ИНН", "plan": 50, "fact": 55},
            {"row": "СНИЛС", "plan": 30, "fact": 28}]
    cell_alert_levels(cfg, rows)
    assert [r.get("__fmt", {}).get("fact") for r in rows] == ["warn", "danger", "danger"]
    # Столбец без оформления не размечается вовсе — иначе таблица красилась бы
    # там, где человек этого не просил.
    assert all("plan" not in r.get("__fmt", {}) for r in rows)
    # Тот же уровень даёт и карточка показателя по тем же порогам.
    for r in rows:
        card = evaluate_alert("kpi", {"alerts": RULES}, {"value": r["fact"]})
        assert card["level"] == r["__fmt"]["fact"]


def test_no_rules_or_no_columns_means_no_marks():
    """Без порогов и без выбранных столбцов разметки нет: «цвет по порогам»
    без самих порогов должен молчать, а не красить всё подряд."""
    rows = [{"row": "Паспорт", "fact": 10}]
    cell_alert_levels({"cell_format": {"fact": "alert"}}, rows)   # порогов нет
    assert "__fmt" not in rows[0]
    cell_alert_levels({"alerts": RULES}, rows)                    # столбцов нет
    assert "__fmt" not in rows[0]
    # «Полоска» уровнями не размечается: в ней нет правила, только соотношение
    # чисел, и считает её клиент от максимума столбца.
    cell_alert_levels({"alerts": RULES, "cell_format": {"fact": "bar"}}, rows)
    assert "__fmt" not in rows[0]


async def test_table_widget_returns_format_and_palette(client, admin_headers, seed_dataset):
    """Сквозь виджет: настройка доезжает до данных вместе с палитрой уровней."""
    did = (await client.post("/dashboards", headers=admin_headers,
                             json={"name": "ztest_cellfmt"})).json()["id"]
    try:
        page = (await client.post(f"/dashboards/{did}/pages", headers=admin_headers,
                                  json={"name": "Стр"})).json()
        w = (await client.post(f"/dashboard-pages/{page['id']}/widgets", headers=admin_headers, json={
            "name": "Таблица", "widget_type": "table",
            "config": {"dataset_code": seed_dataset["code"], "alerts": RULES,
                       "cell_format": {"fact": "alert", "plan": "bar"}},
        })).json()
        # Через HTTP, а не прямым вызовом расчёта: там проверка доступа
        # устроена fail-closed и без пользователя виджет «не найден» —
        # проверять надо тот путь, которым ходит интерфейс.
        data = (await client.get(f"/widgets/{w['id']}/data", headers=admin_headers)).json()
        assert data["cell_format"] == {"fact": "alert", "plan": "bar"}
        # Палитра приходит ОДИН раз на виджет, а не в каждой ячейке.
        assert data["alert_styles"]["danger"]["bg"] and data["alert_styles"]["good"]["color"]
        marks = {r["row"]: r.get("__fmt", {}) for r in data["rows"]}
        assert marks["Паспорт"]["fact"] == "warn" and marks["ИНН"]["fact"] == "danger"
        # Столбец с полоской уровня не получает: её рисует клиент.
        assert all("plan" not in m for m in marks.values())
    finally:
        await purge_dashboard(did)


def test_fit_layout_keeps_matrix_and_dynamics_tall_enough():
    """«↕ Подогнать размеры» не должна ломать то, что собрал мастер.

    Раньше кнопка ставила матрице табличный размер из `WIDGET_SIZE`, и матрица
    на тринадцать показателей ужималась до двух видимых строк — ровно того, из-за
    чего её и растягивали при сборке. Плюс «Динамика»: замер показал, что в
    шести рядах она стоит впритык (график уже на своём минимуме), поэтому
    высота поднята до семи.
    """
    from app.modules.dashboards._suggest import WIDGET_SIZE, fit_layout, matrix_height

    widgets = [
        {"id": "1", "widget_type": "matrix",
         "config": {"by": "fields", "value_fields": [f"f{i}" for i in range(13)]}},
        {"id": "2", "widget_type": "dynamics", "config": {}},
    ]
    laid = {w["id"]: w for w in fit_layout(widgets)}
    assert laid["1"]["height"] == matrix_height(13) == 18, "матрица должна растянуться под 13 показателей"
    assert laid["1"]["height"] > WIDGET_SIZE["matrix"][1], "иначе подгонка ужимает матрицу обратно"
    assert laid["2"]["height"] == 7, "«Динамика» в шести рядах режется — замер 24.08"
    # Конфигурация приходит из БД строкой jsonb — разбор не должен падать.
    laid_str = {w["id"]: w for w in fit_layout(
        [{"id": "1", "widget_type": "matrix",
          "config": '{"by": "fields", "value_fields": ["a", "b", "c"]}'}])}
    assert laid_str["1"]["height"] == matrix_height(3)
