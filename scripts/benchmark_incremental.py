"""Small incremental-maintenance smoke benchmark.

This is not a claim-reproduction script for the paper tables; it is intended to
verify that the public implementation exercises the same update path.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import argparse
import time

from online_causal_rca import OnlineCausalRCAEngine
from online_causal_rca.synthetic import generate_incident


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repeat", type=int, default=5)
    args = parser.parse_args()

    events = generate_incident(n_steps=220)
    inc_times = []
    for _ in range(args.repeat):
        engine = OnlineCausalRCAEngine(depth=3, lookback=120)
        t0 = time.perf_counter()
        engine.ingest_many(events)
        engine.remove_call("checkout", "shipping")
        inc_times.append((time.perf_counter() - t0) * 1000)

    print(f"Incremental path mean: {sum(inc_times) / len(inc_times):.2f} ms over {args.repeat} runs")
    print("Note: this public smoke benchmark does not rebuild from all raw telemetry.")


if __name__ == "__main__":
    main()
