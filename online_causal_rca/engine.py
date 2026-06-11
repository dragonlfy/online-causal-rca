"""End-to-end OnlineCausalRCA engine."""

from __future__ import annotations

import time
from collections import defaultdict, deque
from typing import Deque, Dict, Iterable, List, Optional, Tuple

from .anomaly import StreamingZScoreDetector
from .causal import OnlineCausalGraph
from .index import AlignmentIndex, upstream_candidates
from .models import Anomaly, CausalNode, Event, WhatIfResult, WhyResult
from .storage import JsonlEventStore
from .topology import DynamicTopology


class OnlineCausalRCAEngine:
    """Composes topology, causal maintenance, alignment index, and RCQL helpers."""

    def __init__(
        self,
        *,
        depth: int = 2,
        lookback: float = 300.0,
        history_size: int = 128,
        alpha: float = 0.10,
        min_samples: int = 5,
        anomaly_detector: Optional[StreamingZScoreDetector] = None,
        event_store: Optional[JsonlEventStore] = None,
    ) -> None:
        self.depth = depth
        self.lookback = lookback
        self.history_size = history_size
        self.topology = DynamicTopology()
        self.causal_graph = OnlineCausalGraph(alpha=alpha, min_samples=min_samples)
        self.index = AlignmentIndex()
        self.detector = anomaly_detector or StreamingZScoreDetector()
        self.event_store = event_store or JsonlEventStore()
        self.history: Dict[CausalNode, Deque[Tuple[float, float]]] = defaultdict(
            lambda: deque(maxlen=history_size)
        )

    def add_call(self, caller: str, callee: str) -> None:
        self.topology.upsert_call(caller, callee)

    def remove_call(self, caller: str, callee: str) -> int:
        self.topology.remove_call(caller, callee)
        return self.causal_graph.prune_by_topology(self.topology, depth=self.depth)

    def ingest_event(self, event: Event) -> Optional[Anomaly]:
        """Ingest one telemetry event and return a detected anomaly if any."""
        self.topology.add_service(event.service)
        # Trace events can carry live topology updates.
        caller = event.attributes.get("caller")
        callee = event.attributes.get("callee")
        if caller and callee:
            self.topology.upsert_call(str(caller), str(callee))

        # Update causal stats before appending the current event to history.
        if event.is_numeric():
            self.causal_graph.observe_event(
                event,
                self.topology,
                self.history,
                depth=self.depth,
                lookback=self.lookback,
            )

        self.index.insert_event(event)
        self.event_store.append(event)

        anomaly = self.detector.observe(event)
        if anomaly is not None:
            self.index.insert_anomaly(anomaly)

        if event.is_numeric():
            self.history[event.node].append((event.t, float(event.value)))
        return anomaly

    def ingest_many(self, events: Iterable[Event], *, sort: bool = True) -> List[Anomaly]:
        rows = list(events)
        if sort:
            rows.sort(key=lambda e: e.t)
        out: List[Anomaly] = []
        for event in rows:
            anom = self.ingest_event(event)
            if anom is not None:
                out.append(anom)
        return out

    def explain_why(
        self,
        service: str,
        signal: str,
        *,
        op: Optional[str] = None,
        threshold: Optional[float] = None,
        t: Optional[float] = None,
        limit: int = 5,
        use_gate: bool = True,
        query: Optional[str] = None,
    ) -> WhyResult:
        start = time.perf_counter()
        node = CausalNode(service, signal)
        symptom = self.index.latest_for_node(node)
        if symptom is None:
            symptom = Anomaly(
                t=t if t is not None else self.index.latest_event_time(),
                service=service,
                modality="metric",
                signal=signal,
                score=1.0 if threshold is not None else 0.0,
                threshold=threshold,
                attributes={"constructed_at_query_time": True, "op": op},
            )
        cands = upstream_candidates(
            symptom,
            self.index,
            self.topology,
            self.causal_graph,
            lookback=self.lookback,
            depth=self.depth,
            limit=limit,
            use_gate=use_gate,
        )
        latency_ms = (time.perf_counter() - start) * 1000.0
        return WhyResult(
            query=query or f"WHY {service}.{signal}?",
            symptom=symptom,
            candidates=cands,
            used_gate=use_gate,
            latency_ms=latency_ms,
        )

    def what_if(self, action: str, service: str, *, depth: int = 4, query: Optional[str] = None) -> WhatIfResult:
        start = time.perf_counter()
        topology_blast = self.topology.downstream(service, depth)
        causal_blast = self.causal_graph.service_successors(service)
        blast = sorted((topology_blast | causal_blast) - {service})
        severed = sum(1 for u, _v, _w in self.causal_graph.significant_edges() if u.service == service)
        latency_ms = (time.perf_counter() - start) * 1000.0
        return WhatIfResult(
            query=query or f"WHAT-IF {action} {service}?",
            action=action,
            service=service,
            blast_radius=blast,
            severed_causal_edges=severed,
            latency_ms=latency_ms,
        )

    def run_rcql(self, statement: str):
        from .query import RCQLExecutor

        return RCQLExecutor(self).execute(statement)
