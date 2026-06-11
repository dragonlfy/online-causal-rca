"""Online lagged-correlation graph maintenance.

This module implements the sufficient statistics, Fisher z-test pruning, causal
edge lookup, causal-path scoring, and the gate veto test used by the alignment
index.  It deliberately models *directed temporal association* rather than
claiming interventional causality.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from math import atanh, isfinite, prod, sqrt
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

from .models import CausalNode, Event
from .topology import DynamicTopology


def _zcrit(alpha: float) -> float:
    """Two-sided normal critical value for common alpha choices.

    The paper uses alpha=0.10 -> 1.645.  A small table avoids adding SciPy as a
    dependency.  Unknown values fall back to the default used in the paper.
    """
    table = {
        0.20: 1.282,
        0.10: 1.645,
        0.05: 1.960,
        0.02: 2.326,
        0.01: 2.576,
        0.001: 3.291,
    }
    return table.get(round(alpha, 3), 1.645)


@dataclass
class LaggedEdgeStats:
    """Sufficient statistics for one ordered source -> destination pair."""

    n: int = 0
    sum_x: float = 0.0
    sum_y: float = 0.0
    sum_x2: float = 0.0
    sum_y2: float = 0.0
    sum_xy: float = 0.0
    sum_lag: float = 0.0
    anomaly_count: int = 0

    def update(self, x: float, y: float, lag: float, *, anomaly_pair: bool = False) -> None:
        self.n += 1
        self.sum_x += x
        self.sum_y += y
        self.sum_x2 += x * x
        self.sum_y2 += y * y
        self.sum_xy += x * y
        self.sum_lag += lag
        if anomaly_pair:
            self.anomaly_count += 1

    @property
    def avg_lag(self) -> float:
        return self.sum_lag / self.n if self.n else 0.0

    def pearson(self) -> float:
        if self.n < 2:
            return 0.0
        num = self.n * self.sum_xy - self.sum_x * self.sum_y
        den_x = self.n * self.sum_x2 - self.sum_x * self.sum_x
        den_y = self.n * self.sum_y2 - self.sum_y * self.sum_y
        den = den_x * den_y
        if den <= 1e-12:
            return 0.0
        r = num / sqrt(den)
        return max(-0.999999, min(0.999999, r))

    def fisher_z(self) -> float:
        if self.n < 5:
            return 0.0
        r = abs(self.pearson())
        return atanh(r) * sqrt(max(1, self.n - 3))

    def is_significant(self, *, alpha: float = 0.10, min_samples: int = 5) -> bool:
        return self.n >= min_samples and self.fisher_z() >= _zcrit(alpha)

    def weight(self, *, alpha: float = 0.10, min_samples: int = 5) -> float:
        if not self.is_significant(alpha=alpha, min_samples=min_samples):
            return 0.0
        support = min(1.0, self.n / max(float(min_samples), 1.0))
        return abs(self.pearson()) * support


class OnlineCausalGraph:
    """Maintained directed lagged-correlation graph over ``CausalNode`` objects."""

    def __init__(self, *, alpha: float = 0.10, min_samples: int = 5) -> None:
        self.alpha = alpha
        self.min_samples = min_samples
        self.stats: Dict[Tuple[CausalNode, CausalNode], LaggedEdgeStats] = {}

    def update_stats(
        self,
        source: CausalNode,
        target: CausalNode,
        x: float,
        y: float,
        lag: float,
        *,
        anomaly_pair: bool = False,
    ) -> None:
        if source == target:
            return
        rec = self.stats.setdefault((source, target), LaggedEdgeStats())
        rec.update(x=x, y=y, lag=lag, anomaly_pair=anomaly_pair)

    def edge_stats(self, source: CausalNode, target: CausalNode) -> Optional[LaggedEdgeStats]:
        return self.stats.get((source, target))

    def significant_edges(self) -> List[Tuple[CausalNode, CausalNode, float]]:
        out: List[Tuple[CausalNode, CausalNode, float]] = []
        for (u, v), s in self.stats.items():
            w = s.weight(alpha=self.alpha, min_samples=self.min_samples)
            if w > 0:
                out.append((u, v, w))
        return out

    def predecessors(self, node: CausalNode) -> List[Tuple[CausalNode, float]]:
        return [(u, w) for u, v, w in self.significant_edges() if v == node]

    def successors(self, node: CausalNode) -> List[Tuple[CausalNode, float]]:
        return [(v, w) for u, v, w in self.significant_edges() if u == node]

    def edge_weight(self, source: CausalNode, target: CausalNode) -> float:
        rec = self.stats.get((source, target))
        return 0.0 if rec is None else rec.weight(alpha=self.alpha, min_samples=self.min_samples)

    def service_successors(self, service: str) -> Set[str]:
        return {v.service for u, v, _ in self.significant_edges() if u.service == service}

    def prune_by_topology(self, topology: DynamicTopology, *, depth: int = 2) -> int:
        """Remove causal edges outside the D-hop topology neighbourhood.

        Returns the number of removed edge-stat records.
        """
        to_delete: List[Tuple[CausalNode, CausalNode]] = []
        cache: Dict[str, Set[str]] = {}
        for u, v in self.stats:
            if u.service == v.service:
                continue
            if v.service not in cache:
                cache[v.service] = topology.d_hop_ball(v.service, depth, undirected=True)
            if u.service not in cache[v.service]:
                to_delete.append((u, v))
        for key in to_delete:
            del self.stats[key]
        return len(to_delete)

    def observe_event(
        self,
        event: Event,
        topology: DynamicTopology,
        history: Dict[CausalNode, Sequence[Tuple[float, float]]],
        *,
        depth: int,
        lookback: float,
    ) -> None:
        """Algorithm-1-style update from a numeric event.

        ``history`` maps causal nodes to recent ``(timestamp, value)`` pairs and
        should not include ``event`` itself yet.
        """
        if not event.is_numeric():
            return
        target = event.node
        neighbourhood = topology.d_hop_ball(event.service, depth, undirected=True)
        left = event.t - lookback
        for node, samples in history.items():
            if node.service not in neighbourhood:
                continue
            for t_prev, x_prev in samples:
                if left <= t_prev <= event.t:
                    self.update_stats(node, target, x_prev, float(event.value), event.t - t_prev)

    def _adjacency(self) -> Dict[CausalNode, List[Tuple[CausalNode, float]]]:
        adj: Dict[CausalNode, List[Tuple[CausalNode, float]]] = defaultdict(list)
        for u, v, w in self.significant_edges():
            adj[u].append((v, w))
        return adj

    def shortest_path_score(
        self, source: CausalNode, target: CausalNode, *, max_depth: int = 4
    ) -> Tuple[float, List[str]]:
        """Return geometric-mean edge score and path from ``source`` to ``target``."""
        if source == target:
            return 0.0, [str(source)]
        adj = self._adjacency()
        q = deque([(source, [source], [])])
        seen = {source}
        while q:
            u, path, weights = q.popleft()
            if len(path) - 1 >= max_depth:
                continue
            for v, w in sorted(adj.get(u, []), key=lambda x: -x[1]):
                if v in seen:
                    continue
                new_path = path + [v]
                new_weights = weights + [max(w, 1e-9)]
                if v == target:
                    geom = prod(new_weights) ** (1.0 / len(new_weights))
                    return geom, [str(n) for n in new_path]
                seen.add(v)
                q.append((v, new_path, new_weights))
        return 0.0, []

    def stats_between_services(self, a: str, b: str) -> List[LaggedEdgeStats]:
        return [
            rec
            for (u, v), rec in self.stats.items()
            if {u.service, v.service} == {a, b}
        ]

    def hop_confidently_vetoed(self, a: str, b: str, *, min_gate_support: int = 8) -> bool:
        """Return True only when all observed service-level edges are supported and non-significant.

        No observed edge or insufficient support is deliberately *not* a veto.
        """
        records = self.stats_between_services(a, b)
        if not records:
            return False
        if any(r.n < min_gate_support for r in records):
            return False
        return all(not r.is_significant(alpha=self.alpha, min_samples=self.min_samples) for r in records)
