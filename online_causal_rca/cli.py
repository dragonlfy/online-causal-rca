"""Command line interface for the public OnlineCausalRCA prototype."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Iterable

from .engine import OnlineCausalRCAEngine
from .models import Event
from .synthetic import DEFAULT_TOPOLOGY, generate_incident


def _cmd_demo(args: argparse.Namespace) -> int:
    engine = OnlineCausalRCAEngine(depth=args.depth, lookback=args.lookback)
    events = generate_incident(seed=args.seed)
    anomalies = engine.ingest_many(events)
    # Synthetic topology goes web -> checkout -> payment, so web latency is a symptom.
    why = engine.run_rcql("WHY web.span_latency_ms > 500 ms?")
    whatif = engine.run_rcql("WHAT-IF rollback payment?")
    print(json.dumps({"anomalies": len(anomalies), "why": why.to_json(), "what_if": whatif.to_json()}, indent=2))
    return 0


def _iter_jsonl(path: Path) -> Iterable[Event]:
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield Event.from_json(json.loads(line))


def _cmd_query(args: argparse.Namespace) -> int:
    engine = OnlineCausalRCAEngine(depth=args.depth, lookback=args.lookback)
    engine.ingest_many(_iter_jsonl(Path(args.input)))
    result = engine.run_rcql(args.statement)
    print(json.dumps(result.to_json(), indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="OnlineCausalRCA reference implementation")
    sub = parser.add_subparsers(required=True)

    demo = sub.add_parser("demo", help="run a synthetic payment-root-cause incident")
    demo.add_argument("--seed", type=int, default=7)
    demo.add_argument("--depth", type=int, default=3)
    demo.add_argument("--lookback", type=float, default=120.0)
    demo.set_defaults(func=_cmd_demo)

    query = sub.add_parser("query", help="run RCQL on a JSONL event file")
    query.add_argument("--input", required=True, help="JSONL file with Event records")
    query.add_argument("--statement", required=True, help='e.g. "WHY web.span_latency_ms > 500 ms?"')
    query.add_argument("--depth", type=int, default=3)
    query.add_argument("--lookback", type=float, default=120.0)
    query.set_defaults(func=_cmd_query)
    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
