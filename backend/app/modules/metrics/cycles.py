"""Детектор циклов зависимостей метрик + топологический порядок пересчёта.

Порт cycle_detection.py: DFS с раскраской (white/gray/black), O(V+E).
Используется перед сохранением/одобрением версии метрики: круговая зависимость
недопустима. Возвращаемый порядок (dependency-first) задаёт последовательность пересчёта.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Dict, Iterable, List, Tuple

WHITE, GRAY, BLACK = 0, 1, 2


class CycleError(Exception):
    def __init__(self, cycle_path: List[str]):
        self.cycle_path = cycle_path
        super().__init__("Обнаружена циклическая зависимость: " + " → ".join(cycle_path))


def validate_and_topo_sort(nodes: Iterable[str], edges: Iterable[Tuple[str, str]]) -> List[str]:
    """nodes — коды метрик; edges — (метрика, от_которой_зависит). Топопорядок или CycleError."""
    graph: Dict[str, List[str]] = defaultdict(list)
    for src, dst in edges:
        graph[src].append(dst)

    nodes = list(nodes)
    color = {n: WHITE for n in nodes}
    order: List[str] = []
    stack_path: List[str] = []

    def dfs(node: str) -> None:
        color[node] = GRAY
        stack_path.append(node)
        for neighbor in graph.get(node, []):
            c = color.get(neighbor, WHITE)
            if c == GRAY:
                start = stack_path.index(neighbor)
                raise CycleError(stack_path[start:] + [neighbor])
            if c == WHITE:
                color.setdefault(neighbor, WHITE)
                dfs(neighbor)
        stack_path.pop()
        color[node] = BLACK
        order.append(node)

    for n in nodes:
        if color[n] == WHITE:
            dfs(n)
    return order  # dependency-first: считать самые левые (листовые) первыми
