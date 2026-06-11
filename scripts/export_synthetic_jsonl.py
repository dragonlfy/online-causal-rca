"""Export a synthetic incident as JSONL for CLI tests."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import argparse
import json

from online_causal_rca.synthetic import generate_incident


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--output", default="data/sample/incident.jsonl")
    p.add_argument("--seed", type=int, default=7)
    args = p.parse_args()
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for e in generate_incident(seed=args.seed):
            f.write(json.dumps(e.to_json()) + "\n")
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
