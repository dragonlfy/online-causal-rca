"""Shared data models for OnlineCausalRCA.

The classes in this file intentionally stay dependency-free so that the
research prototype can run on a bare Python installation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Tuple


@dataclass(frozen=True, order=True)
class CausalNode:
    """A node in the lagged-correlation graph: (service, signal)."""

    service: str
    signal: str

    @classmethod
    def parse(cls, text: str) -> "CausalNode":
        """Parse ``service.signal`` using the first dot as the separator."""
        if "." not in text:
            raise ValueError(f"node reference must be service.signal, got {text!r}")
        service, signal = text.split(".", 1)
        if not service or not signal:
            raise ValueError(f"invalid node reference {text!r}")
        return cls(service=service, signal=signal)

    def __str__(self) -> str:  # pragma: no cover - tiny convenience method
        return f"{self.service}.{self.signal}"


@dataclass
class Event:
    """Telemetry event.

    Parameters follow the notation in the paper: ``t`` is a timestamp,
    ``service`` identifies the emitting service, ``modality`` is one of
    ``trace``, ``metric`` or ``log``, ``signal`` is the observed signal name,
    and ``value`` is numeric for metric/trace events and usually ``None`` for
    logs. ``attributes`` can carry trace caller/callee, log severity, labels,
    etc.
    """

    t: float
    service: str
    modality: str
    signal: str
    value: Optional[float] = None
    attributes: Dict[str, Any] = field(default_factory=dict)

    @property
    def node(self) -> CausalNode:
        return CausalNode(self.service, self.signal)

    def is_numeric(self) -> bool:
        return self.value is not None and self.modality != "log"

    def to_json(self) -> Dict[str, Any]:
        return {
            "t": self.t,
            "service": self.service,
            "modality": self.modality,
            "signal": self.signal,
            "value": self.value,
            "attributes": self.attributes,
        }

    @classmethod
    def from_json(cls, obj: Dict[str, Any]) -> "Event":
        return cls(
            t=float(obj["t"]),
            service=str(obj["service"]),
            modality=str(obj["modality"]),
            signal=str(obj["signal"]),
            value=None if obj.get("value") is None else float(obj["value"]),
            attributes=dict(obj.get("attributes") or {}),
        )


@dataclass
class Anomaly:
    """A detected anomaly attached to a service-signal node."""

    t: float
    service: str
    modality: str
    signal: str
    score: float
    value: Optional[float] = None
    threshold: Optional[float] = None
    attributes: Dict[str, Any] = field(default_factory=dict)

    @property
    def node(self) -> CausalNode:
        return CausalNode(self.service, self.signal)

    def to_json(self) -> Dict[str, Any]:
        return {
            "t": self.t,
            "service": self.service,
            "modality": self.modality,
            "signal": self.signal,
            "score": self.score,
            "value": self.value,
            "threshold": self.threshold,
            "attributes": self.attributes,
        }


@dataclass
class Candidate:
    """Root-cause candidate returned by a WHY query."""

    service: str
    signal: str
    score: float
    features: Dict[str, float]
    evidence_chain: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def node(self) -> CausalNode:
        return CausalNode(self.service, self.signal)

    def to_json(self) -> Dict[str, Any]:
        return {
            "service": self.service,
            "signal": self.signal,
            "score": self.score,
            "features": self.features,
            "evidence_chain": self.evidence_chain,
        }


@dataclass
class WhyResult:
    """Result of an RCQL WHY statement."""

    query: str
    symptom: Anomaly
    candidates: List[Candidate]
    used_gate: bool = True
    latency_ms: Optional[float] = None

    def to_json(self) -> Dict[str, Any]:
        return {
            "query": self.query,
            "symptom": self.symptom.to_json(),
            "used_gate": self.used_gate,
            "latency_ms": self.latency_ms,
            "candidates": [c.to_json() for c in self.candidates],
        }


@dataclass
class WhatIfResult:
    """Result of an RCQL WHAT-IF statement."""

    query: str
    action: str
    service: str
    blast_radius: List[str]
    severed_causal_edges: int
    latency_ms: Optional[float] = None

    def to_json(self) -> Dict[str, Any]:
        return {
            "query": self.query,
            "action": self.action,
            "service": self.service,
            "blast_radius": self.blast_radius,
            "touched_services": len(self.blast_radius),
            "severed_causal_edges": self.severed_causal_edges,
            "latency_ms": self.latency_ms,
        }
