"""Minimal end-to-end OnlineCausalRCA demo.

Run with:
    python examples/run_demo.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from online_causal_rca import OnlineCausalRCAEngine
from online_causal_rca.synthetic import generate_incident


engine = OnlineCausalRCAEngine(depth=3, lookback=120.0)
events = generate_incident(seed=11)
anomalies = engine.ingest_many(events)

why = engine.run_rcql("WHY web.span_latency_ms > 500 ms?")
what_if = engine.run_rcql("WHAT-IF rollback payment?")

print(f"Ingested {len(events)} events; detected {len(anomalies)} anomalies.")
print("\nWHY result:")
for i, cand in enumerate(why.candidates, start=1):
    print(f"{i}. {cand.service}.{cand.signal} score={cand.score:.3f} features={cand.features}")

print("\nWHAT-IF result:")
print(json.dumps(what_if.to_json(), indent=2))
