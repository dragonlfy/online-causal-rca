"""Simple streaming anomaly detectors used by the public reference code."""

from __future__ import annotations

from collections import defaultdict, deque
from statistics import mean, pstdev
from typing import Deque, Dict, Optional, Tuple

from .models import Anomaly, CausalNode, Event


class StreamingZScoreDetector:
    """Rolling z-score detector with a small log-event heuristic.

    This detector is intentionally lightweight.  For production use, replace it
    with a phase-aware detector or your existing observability platform while
    keeping the same ``observe(event) -> Optional[Anomaly]`` interface.
    """

    def __init__(self, *, window: int = 64, warmup: int = 12, z_threshold: float = 3.0) -> None:
        self.window = window
        self.warmup = warmup
        self.z_threshold = z_threshold
        self.history: Dict[CausalNode, Deque[float]] = defaultdict(lambda: deque(maxlen=window))

    def observe(self, event: Event) -> Optional[Anomaly]:
        if event.modality == "log":
            severity = str(event.attributes.get("severity", "")).lower()
            if severity in {"error", "fatal", "critical"}:
                return Anomaly(
                    t=event.t,
                    service=event.service,
                    modality=event.modality,
                    signal=event.signal,
                    score=1.0,
                    value=event.value,
                    threshold=None,
                    attributes={"reason": f"log severity={severity}"},
                )
            return None

        if event.value is None:
            return None

        node = event.node
        hist = self.history[node]
        anomaly: Optional[Anomaly] = None
        if len(hist) >= self.warmup:
            mu = mean(hist)
            sd = pstdev(hist) or 1e-9
            z = abs((float(event.value) - mu) / sd)
            if z >= self.z_threshold:
                anomaly = Anomaly(
                    t=event.t,
                    service=event.service,
                    modality=event.modality,
                    signal=event.signal,
                    score=z,
                    value=float(event.value),
                    threshold=self.z_threshold,
                    attributes={"mean": mu, "std": sd, "z": z},
                )
        hist.append(float(event.value))
        return anomaly
