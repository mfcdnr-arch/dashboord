"""
Dependency cycle detection for metric_dependencies.
Used by NestJS MetricValidationService before allowing metric_version.status -> 'validated'.
Algorithm: DFS with recursion-stack coloring (white/gray/black), O(V+E).
Also returns a valid topological order for recompute scheduling.
"""
from collections import defaultdict

class CycleError(Exception):
    def __init__(self, cycle_path):
        self.cycle_path = cycle_path
        super().__init__(f"Circular dependency detected: {' -> '.join(cycle_path)}")

def build_graph(edges):
    graph = defaultdict(list)
    for src, dst in edges:
        graph[src].append(dst)
    return graph

WHITE, GRAY, BLACK = 0, 1, 2

def validate_and_topo_sort(nodes, edges):
    graph = build_graph(edges)
    color = {n: WHITE for n in nodes}
    order = []
    stack_path = []

    def dfs(node):
        color[node] = GRAY
        stack_path.append(node)
        for neighbor in graph.get(node, []):
            if color.get(neighbor, WHITE) == GRAY:
                cycle_start = stack_path.index(neighbor)
                raise CycleError(stack_path[cycle_start:] + [neighbor])
            if color.get(neighbor, WHITE) == WHITE:
                dfs(neighbor)
        stack_path.pop()
        color[node] = BLACK
        order.append(node)

    for n in nodes:
        if color[n] == WHITE:
            dfs(n)
    return order  # dependency-first order: compute leftmost first

if __name__ == "__main__":
    nodes = ["sales_amount", "cogs_amount", "gross_margin", "gross_margin_pct", "gross_margin_pct_mom"]
    edges = [
        ("gross_margin", "sales_amount"),
        ("gross_margin", "cogs_amount"),
        ("gross_margin_pct", "gross_margin"),
        ("gross_margin_pct_mom", "gross_margin_pct"),
    ]
    print("Valid graph, compute order:", validate_and_topo_sort(nodes, edges))

    try:
        bad_edges = edges + [("sales_amount", "gross_margin_pct_mom")]
        validate_and_topo_sort(nodes, bad_edges)
    except CycleError as e:
        print("Correctly caught cycle:", e)
