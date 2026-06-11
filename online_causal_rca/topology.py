"""Dynamic service call graph.

The topology graph stores directed call edges (caller -> callee) but exposes an
undirected D-hop ball for root-cause maintenance because symptoms and root
causes can be separated by upstream or downstream propagation paths.
"""

from __future__ import annotations

from collections import defaultdict, deque
from typing import Dict, Iterable, Iterator, List, Optional, Set, Tuple


class DynamicTopology:
    """Incrementally maintained service call graph."""

    def __init__(self) -> None:
        self.outgoing: Dict[str, Set[str]] = defaultdict(set)
        self.incoming: Dict[str, Set[str]] = defaultdict(set)
        self.delta_log: List[Tuple[str, str, str]] = []

    def add_service(self, service: str) -> None:
        self.outgoing.setdefault(service, set())
        self.incoming.setdefault(service, set())

    def upsert_call(self, caller: str, callee: str) -> None:
        self.add_service(caller)
        self.add_service(callee)
        if callee not in self.outgoing[caller]:
            self.outgoing[caller].add(callee)
            self.incoming[callee].add(caller)
            self.delta_log.append(("add", caller, callee))

    def remove_call(self, caller: str, callee: str) -> None:
        if callee in self.outgoing.get(caller, set()):
            self.outgoing[caller].remove(callee)
            self.incoming[callee].discard(caller)
            self.delta_log.append(("remove", caller, callee))

    def edges(self) -> List[Tuple[str, str]]:
        return [(u, v) for u, nbrs in self.outgoing.items() for v in sorted(nbrs)]

    def services(self) -> Set[str]:
        return set(self.outgoing) | set(self.incoming)

    def neighbours_undirected(self, service: str) -> Set[str]:
        return set(self.outgoing.get(service, set())) | set(self.incoming.get(service, set()))

    # American spelling alias for users who expect it.
    neighbors_undirected = neighbours_undirected

    def d_hop_ball(self, start: str | Iterable[str], depth: int, *, undirected: bool = True) -> Set[str]:
        """Return services within ``depth`` hops of ``start``.

        ``start`` may be one service or an iterable of services. The result
        always includes the start service(s).
        """
        if isinstance(start, str):
            starts = [start]
        else:
            starts = list(start)
        seen: Set[str] = set(starts)
        q = deque((s, 0) for s in starts)
        while q:
            u, d = q.popleft()
            if d >= depth:
                continue
            if undirected:
                nbrs = self.neighbours_undirected(u)
            else:
                nbrs = set(self.outgoing.get(u, set()))
            for v in nbrs:
                if v not in seen:
                    seen.add(v)
                    q.append((v, d + 1))
        return seen

    def downstream(self, service: str, depth: int) -> Set[str]:
        """Return services reachable downstream from ``service`` up to depth."""
        seen: Set[str] = set()
        q = deque([(service, 0)])
        while q:
            u, d = q.popleft()
            if d >= depth:
                continue
            for v in self.outgoing.get(u, set()):
                if v not in seen:
                    seen.add(v)
                    q.append((v, d + 1))
        seen.discard(service)
        return seen

    def distance(self, source: str, target: str, *, max_depth: int = 8, undirected: bool = True) -> Optional[int]:
        if source == target:
            return 0
        q = deque([(source, 0)])
        seen = {source}
        while q:
            u, d = q.popleft()
            if d >= max_depth:
                continue
            nbrs = self.neighbours_undirected(u) if undirected else self.outgoing.get(u, set())
            for v in nbrs:
                if v == target:
                    return d + 1
                if v not in seen:
                    seen.add(v)
                    q.append((v, d + 1))
        return None

    def average_degree(self) -> float:
        services = self.services()
        if not services:
            return 0.0
        return sum(len(self.neighbours_undirected(s)) for s in services) / len(services)

    @classmethod
    def from_edges(cls, edges: Iterable[Tuple[str, str]]) -> "DynamicTopology":
        topo = cls()
        for u, v in edges:
            topo.upsert_call(u, v)
        return topo
