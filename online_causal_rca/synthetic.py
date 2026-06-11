"""Synthetic microservice telemetry for smoke tests and demos."""

from __future__ import annotations

import random
from typing import Iterable, List, Sequence, Tuple

from .models import Event


DEFAULT_TOPOLOGY: List[Tuple[str, str]] = [
    ("web", "checkout"),
    ("checkout", "payment"),
    ("checkout", "shipping"),
    ("payment", "payment-db"),
    ("shipping", "shipping-db"),
    ("web", "catalog"),
    ("catalog", "catalog-db"),
]


def topology_events(edges: Sequence[Tuple[str, str]], *, t: float = 0.0) -> List[Event]:
    """Trace events that initialise the dynamic topology."""
    return [
        Event(
            t=t + i * 0.001,
            service=caller,
            modality="trace",
            signal="call",
            value=1.0,
            attributes={"caller": caller, "callee": callee},
        )
        for i, (caller, callee) in enumerate(edges)
    ]


def generate_incident(
    *,
    n_steps: int = 180,
    fault_start: int = 95,
    fault_service: str = "payment",
    symptom_service: str = "web",
    seed: int = 7,
) -> List[Event]:
    """Generate a small correlated metric/trace/log incident.

    The true root cause is ``fault_service``.  A resource spike appears there
    first, then service latency propagates toward ``symptom_service`` with a few
    ticks of lag.
    """
    rng = random.Random(seed)
    services = sorted({s for edge in DEFAULT_TOPOLOGY for s in edge})
    events: List[Event] = []
    events.extend(topology_events(DEFAULT_TOPOLOGY, t=0.0))

    # Baseline metric streams.
    for t in range(1, n_steps + 1):
        for svc in services:
            cpu = 35.0 + rng.gauss(0, 2.0)
            latency = 80.0 + rng.gauss(0, 4.0)

            # Root service spikes first.
            if svc == fault_service and t >= fault_start:
                cpu += 45.0 + 0.25 * (t - fault_start)
                latency += 120.0 + rng.gauss(0, 8.0)

            # Propagated latency effects.
            if svc == "checkout" and t >= fault_start + 4:
                latency += 75.0 + rng.gauss(0, 6.0)
            if svc == symptom_service and t >= fault_start + 8:
                latency += 55.0 + rng.gauss(0, 6.0)

            events.append(Event(float(t), svc, "metric", "cpu", cpu))
            events.append(Event(float(t) + 0.01, svc, "trace", "span_latency_ms", latency))

        if t == fault_start + 5:
            events.append(
                Event(
                    float(t) + 0.02,
                    fault_service,
                    "log",
                    "error_template",
                    None,
                    {"severity": "error", "message": "payment timeout to downstream db"},
                )
            )
    events.sort(key=lambda e: e.t)
    return events
