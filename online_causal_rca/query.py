"""RCQL parser and executor.

Supported statements::

    WHY service.signal [> 500 ms]?
    WHAT-IF rollback service?
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional


@dataclass
class WhyStatement:
    service: str
    signal: str
    op: Optional[str] = None
    threshold: Optional[float] = None
    unit: Optional[str] = None


@dataclass
class WhatIfStatement:
    action: str
    service: str


WHY_RE = re.compile(
    r"^\s*WHY\s+(?P<node>[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-.]+)"
    r"(?:\s*(?P<op>>=|<=|>|<|=)\s*(?P<thr>[0-9]+(?:\.[0-9]+)?)\s*(?P<unit>ms|s|%)?)?\s*\?\s*$",
    re.IGNORECASE,
)
WHATIF_RE = re.compile(
    r"^\s*WHAT-IF\s+(?P<action>rollback|disable|remove)\s+(?P<service>[A-Za-z0-9_\-]+)\s*\?\s*$",
    re.IGNORECASE,
)


def parse_rcql(statement: str) -> WhyStatement | WhatIfStatement:
    m = WHY_RE.match(statement)
    if m:
        node = m.group("node")
        service, signal = node.split(".", 1)
        thr = m.group("thr")
        return WhyStatement(
            service=service,
            signal=signal,
            op=m.group("op"),
            threshold=None if thr is None else float(thr),
            unit=m.group("unit"),
        )
    m = WHATIF_RE.match(statement)
    if m:
        return WhatIfStatement(action=m.group("action").lower(), service=m.group("service"))
    raise ValueError(f"invalid RCQL statement: {statement!r}")


class RCQLExecutor:
    """Thin executor delegating to ``OnlineCausalRCAEngine``."""

    def __init__(self, engine) -> None:
        self.engine = engine

    def execute(self, statement: str):
        parsed = parse_rcql(statement)
        if isinstance(parsed, WhyStatement):
            return self.engine.explain_why(
                parsed.service,
                parsed.signal,
                op=parsed.op,
                threshold=parsed.threshold,
                query=statement,
            )
        return self.engine.what_if(parsed.action, parsed.service, query=statement)
