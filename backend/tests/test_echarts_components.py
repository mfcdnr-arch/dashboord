"""Каждая часть ECharts, которой пользуются графики, обязана быть подключена.

Фронт подключает ECharts выборочно (`echarts.use([...])` в EChart.tsx), чтобы
не тащить мегабайт кода. Цена — тихий отказ: опция, чей компонент не
подключён, просто НЕ РИСУЕТСЯ, без ошибки в консоли. Так линии порога
(`markLine`) на «Динамике» с 12.10.2026 не появлялись ни разу, и заметили это
только на точечной диаграмме. Тест читает исходники фронта тем же приёмом,
что test_widget_registry_consistency.
"""
import re
from pathlib import Path

FRONT = Path(__file__).resolve().parents[2] / "frontend/src"
ECHART = FRONT / "components/EChart.tsx"

# опция в конфиге графика → компонент, без которого она молча пропадает
NEEDS = {
    "markLine": "MarkLineComponent",
    "markArea": "MarkAreaComponent",
    "markPoint": "MarkPointComponent",
    "dataZoom": "DataZoomComponent",
    "visualMap": "VisualMapComponent",
    "legend": "LegendComponent",
    "tooltip": "TooltipComponent",
}
CHARTS = {"bar": "BarChart", "line": "LineChart", "pie": "PieChart", "gauge": "GaugeChart",
          "heatmap": "HeatmapChart", "scatter": "ScatterChart", "radar": "RadarChart",
          "sankey": "SankeyChart", "treemap": "TreemapChart", "funnel": "FunnelChart"}


def _sources() -> str:
    return "\n".join(p.read_text(encoding="utf-8") for p in FRONT.rglob("*.tsx")
                     if ".test." not in p.name and p.name != "EChart.tsx")


def _registered() -> str:
    src = ECHART.read_text(encoding="utf-8")
    m = re.search(r"echarts\.use\(\[(.*?)\]\)", src, re.S)
    assert m, "не нашли echarts.use([...]) в EChart.tsx — файл переехал?"
    return m.group(1)


def test_every_used_option_has_its_component():
    used, reg = _sources(), _registered()
    missing = [f"{opt} → {comp}" for opt, comp in NEEDS.items()
               if re.search(rf"\b{opt}\s*[:=](?!=)", used) and comp not in reg]
    assert not missing, f"опции графиков без подключённого компонента ECharts (молча не рисуются): {missing}"


def test_every_used_series_type_is_registered():
    used, reg = _sources(), _registered()
    missing = [f"{t} → {c}" for t, c in CHARTS.items()
               if re.search(rf"type:\s*'{t}'", used) and c not in reg]
    assert not missing, f"виды рядов без подключённого графика ECharts: {missing}"
