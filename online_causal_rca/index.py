"""Multimodal alignment index and root-cause candidate retrieval."""

from __future__ import annotations

from bisect import bisect_left, bisect_right, insort
from collections import defaultdict, deque
from typing import DefaultDict, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from .causal import OnlineCausalGraph
from .models import Anomaly, Candidate, CausalNode, Event
from .topology import DynamicTopology


class AlignmentIndex:
    """Per-service sorted lists for events and anomalies.

    Range queries are implemented by binary search over ``(timestamp, seq, obj)``
    tuples. In-order streaming insertion is O(1); out-of-order insertion uses
    ``insort``.
    """

    def __init__(self) -> None:
        self._seq = 0
        self.events: DefaultDict[str, List[Tuple[float, int, Event]]] = defaultdict(list)
        self.anomalies: DefaultDict[str, List[Tuple[float, int, Anomaly]]] = defaultdict(list)
        self.latest_anomaly: Dict[CausalNode, Anomaly] = {}

    def _next_seq(self) -> int:
        self._seq += 1
        return self._seq

    def insert_event(self, event: Event) -> None:
        seq = self._next_seq()
        row = (event.t, seq, event)
        lst = self.events[event.service]
        if not lst or lst[-1][0] <= event.t:
            lst.append(row)
        else:
            insort(lst, row)

    def insert_anomaly(self, anomaly: Anomaly) -> None:
        seq = self._next_seq()
        row = (anomaly.t, seq, anomaly)
        lst = self.anomalies[anomaly.service]
        if not lst or lst[-1][0] <= anomaly.t:
            lst.append(row)
        else:
            insort(lst, row)
        prev = self.latest_anomaly.get(anomaly.node)
        if prev is None or anomaly.t >= prev.t:
            self.latest_anomaly[anomaly.node] = anomaly

    @staticmethod
    def _range(rows: List[Tuple[float, int, object]], left: float, right: float) -> List[object]:
        lo = bisect_left(rows, (left, -1, None))
        hi = bisect_right(rows, (right, 10**18, None))
        return [obj for _, _, obj in rows[lo:hi]]

    def query_events(self, service: str, left: float, right: float) -> List[Event]:
        return list(self._range(self.events.get(service, []), left, right))  # type: ignore[arg-type]

    def query_anomalies(self, service: str, left: float, right: float) -> List[Anomaly]:
        return list(self._range(self.anomalies.get(service, []), left, right))  # type: ignore[arg-type]

    def latest_for_node(self, node: CausalNode) -> Optional[Anomaly]:
        return self.latest_anomaly.get(node)

    def latest_event_time(self) -> float:
        latest = 0.0
        for rows in self.events.values():
            if rows:
                latest = max(latest, rows[-1][0])
        return latest


def causally_gated_neighbourhood(
    symptom_service: str,
    topology: DynamicTopology,
    causal_graph: OnlineCausalGraph,
    *,
    depth: int,
    min_gate_support: int = 8,
) -> Set[str]:
    """D-hop topology BFS with causal vetoes.

    A topology hop is skipped only if the causal graph has enough observations
    between the two services and every such edge fails the Fisher test.
    """
    seen: Set[str] = {symptom_service}
    q = deque([(symptom_service, 0)])
    while q:
        service, dist = q.popleft()
        if dist >= depth:
            continue
        for nb in topology.neighbours_undirected(service):
            if nb in seen:
                continue
            if causal_graph.hop_confidently_vetoed(service, nb, min_gate_support=min_gate_support):
                continue
            seen.add(nb)
            q.append((nb, dist + 1))
    return seen


def _unit_score(raw: float, *, scale: float = 4.0) -> float:
    """Map detector z-score-like values to [0, 1]."""
    if raw <= 1.0:
        return max(0.0, raw)
    return max(0.0, min(1.0, raw / scale))


def upstream_candidates(
    symptom: Anomaly,
    index: AlignmentIndex,
    topology: DynamicTopology,
    causal_graph: OnlineCausalGraph,
    *,
    lookback: float = 300.0,
    depth: int = 2,
    limit: int = 5,
    use_gate: bool = True,
    min_gate_support: int = 8,
    causal_path_depth: int = 4,
) -> List[Candidate]:
    """Algorithm-3-style root-cause candidate retrieval and scoring."""
    left = symptom.t - lookback
    if use_gate:
        services = causally_gated_neighbourhood(
            symptom.service,
            topology,
            causal_graph,
            depth=depth,
            min_gate_support=min_gate_support,
        )
    else:
        services = topology.d_hop_ball(symptom.service, depth, undirected=True)

    grouped: Dict[CausalNode, List[Anomaly]] = defaultdict(list)
    service_modalities: Dict[str, Set[str]] = defaultdict(set)
    for service in services:
        anoms = index.query_anomalies(service, left, symptom.t)
        for anom in anoms:
            grouped[anom.node].append(anom)
            service_modalities[service].add(anom.modality)

    candidates: List[Candidate] = []
    for node, anoms in grouped.items():
        best_anom = max(anoms, key=lambda a: (a.score, a.t))
        f1 = _unit_score(best_anom.score)
        if node == symptom.node:
            f1 *= 0.55

        f2, path = causal_graph.shortest_path_score(node, symptom.node, max_depth=causal_path_depth)
        f2 = max(0.0, min(1.0, f2))

        dt = abs(symptom.t - best_anom.t)
        f3 = max(0.0, 1.0 - dt / max(lookback, 1e-9))

        # Reward multi-modal evidence. One modality -> 0.33, three -> 1.0.
        f4 = min(1.0, max(1, len(service_modalities[node.service])) / 3.0)

        dist = topology.distance(node.service, symptom.service, max_depth=max(depth + 3, 8), undirected=True)
        if node.service == symptom.service:
            f5 = 0.25
        elif dist is None:
            f5 = 0.50
        else:
            f5 = max(0.25, 1.0 - 0.12 * dist)

        score = 0.35 * f1 + 0.30 * f2 + 0.18 * f3 + 0.10 * f4 + 0.07 * f5
        supporting_events = index.query_events(node.service, left, symptom.t)[-5:]
        evidence = [
            {
                "type": "anomaly",
                "node": str(node),
                "time": best_anom.t,
                "score": best_anom.score,
                "value": best_anom.value,
                "modality": best_anom.modality,
            }
        ]
        if path:
            evidence.append({"type": "causal_path", "path": path, "path_score": f2})
        if supporting_events:
            evidence.append(
                {
                    "type": "supporting_events",
                    "count": len(supporting_events),
                    "examples": [
                        {
                            "time": e.t,
                            "modality": e.modality,
                            "signal": e.signal,
                            "value": e.value,
                        }
                        for e in supporting_events
                    ],
                }
            )

        candidates.append(
            Candidate(
                service=node.service,
                signal=node.signal,
                score=score,
                features={"f1": f1, "f2": f2, "f3": f3, "f4": f4, "f5": f5},
                evidence_chain=evidence,
            )
        )

    candidates.sort(key=lambda c: (-c.score, c.service, c.signal))
    return candidates[:limit]
