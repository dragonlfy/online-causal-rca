# OnlineCausalRCA

Public reference implementation for **Online Causal-Graph Maintenance and Interactive Querying for Root-Cause Analysis in Microservice Systems**.


<p align="center">
  <img src="onlinecausalrca_repro.pdf" width="900">
</p>

OnlineCausalRCA treats service-fault causality as an **online maintained data structure** rather than an offline model that must be rebuilt after every topology change. The repository implements the core mechanisms described in the paper:

- **Topology-bounded online causal-graph maintenance** over a dynamic service call graph.
- **Streaming lagged-correlation statistics** with Fisher z-test pruning.
- **Multimodal alignment index** for trace, metric, and log evidence.
- **Causally-gated neighborhood retrieval** that skips topology hops confidently vetoed by the causal graph.
- **RCQL**, a small diagnostic query interface with `WHY` and `WHAT-IF` statements.

> Status: this is a clean, dependency-light public research prototype. It is intended for review, extension, and GitHub release. It does **not** bundle private RCAEval datasets or claim to reproduce the exact paper tables out of the box.

---

## Why this repository exists

Microservice incidents are hard because service topology drifts while evidence is spread across traces, metrics, and logs. Offline causal discovery over all telemetry columns is expensive and often stale. OnlineCausalRCA uses the observation that fault evidence is usually concentrated in a bounded service-call neighborhood, denoted as a D-hop ball around the symptom service.

Instead of scanning all telemetry dimensions, this implementation maintains local lagged-correlation statistics and retrieves root-cause candidates from a topology-bounded, multimodal index.

---

## Repository layout

```text
online-causal-rca/
├── online_causal_rca/
│   ├── models.py       # Event, Anomaly, CausalNode, Candidate, query results
│   ├── topology.py     # Dynamic call graph and D-hop neighborhood operations
│   ├── causal.py       # Lagged stats, Fisher z-test, causal graph maintenance
│   ├── index.py        # Multimodal alignment index and candidate scoring
│   ├── anomaly.py      # Lightweight streaming anomaly detector
│   ├── query.py        # RCQL parser and executor
│   ├── engine.py       # End-to-end pipeline orchestration
│   ├── storage.py      # JSONL event store
│   ├── synthetic.py    # Synthetic microservice incident generator
│   └── cli.py          # Command line interface
├── examples/
│   └── run_demo.py     # Minimal end-to-end demo
├── scripts/
│   ├── benchmark_incremental.py
│   └── export_synthetic_jsonl.py
├── tests/
│   └── test_core.py
├── pyproject.toml
├── requirements.txt
├── CITATION.cff
└── LICENSE
```

---

## Installation

### Option A: editable install

```bash
git clone https://github.com/<your-org>/online-causal-rca.git
cd online-causal-rca
python -m pip install -e .
```

### Option B: run directly from source

The core implementation uses only the Python standard library.

```bash
cd online-causal-rca
python examples/run_demo.py
```

Python 3.10+ is recommended.

---

## Quick start

Run the synthetic incident demo:

```bash
python -m online_causal_rca.cli demo
```

or:

```bash
python examples/run_demo.py
```

Expected output is a JSON or compact terminal report containing:

- number of ingested telemetry events,
- number of detected anomalies,
- `WHY web.span_latency_ms > 500 ms?` root-cause candidates,
- `WHAT-IF rollback payment?` blast-radius estimate.

Example Python usage:

```python
from online_causal_rca import OnlineCausalRCAEngine
from online_causal_rca.synthetic import generate_incident

engine = OnlineCausalRCAEngine(depth=3, lookback=120.0)
events = generate_incident(seed=7)
engine.ingest_many(events)

why = engine.run_rcql("WHY web.span_latency_ms > 500 ms?")
for i, cand in enumerate(why.candidates, 1):
    print(i, cand.service, cand.signal, round(cand.score, 3), cand.features)

what_if = engine.run_rcql("WHAT-IF rollback payment?")
print(what_if.to_json())
```

---

## Input event format

Events are represented by the `Event` dataclass:

```python
Event(
    t=123.0,
    service="payment",
    modality="metric",          # "metric", "trace", or "log"
    signal="cpu",
    value=87.2,
    attributes={}
)
```

JSONL input uses the same fields:

```json
{"t": 123.0, "service": "payment", "modality": "metric", "signal": "cpu", "value": 87.2, "attributes": {}}
```

Trace events can update the dynamic topology when `attributes` includes `caller` and `callee`:

```json
{"t": 1.0, "service": "checkout", "modality": "trace", "signal": "call", "value": 1.0, "attributes": {"caller": "checkout", "callee": "payment"}}
```

Export a sample JSONL incident:

```bash
python scripts/export_synthetic_jsonl.py --output data/sample/incident.jsonl
```

Then query it:

```bash
python -m online_causal_rca.cli query \
  --input data/sample/incident.jsonl \
  --statement "WHY web.span_latency_ms > 500 ms?"
```

---

## RCQL

RCQL is intentionally small. It exposes two diagnostic statements.

### WHY

```text
WHY service.signal [op threshold unit]?
```

Examples:

```text
WHY web.span_latency_ms > 500 ms?
WHY checkout.cpu?
```

A `WHY` query returns ranked root-cause candidates. Each candidate contains:

- candidate service and signal,
- total score,
- five score components,
- evidence chain containing anomaly evidence, causal path evidence, and supporting telemetry examples.

The public implementation follows this score decomposition:

```text
score = 0.35*f1 + 0.30*f2 + 0.18*f3 + 0.10*f4 + 0.07*f5
```

where:

- `f1`: anomaly strength,
- `f2`: causal-path score,
- `f3`: temporal proximity to the symptom,
- `f4`: modality coverage,
- `f5`: topology-distance prior.

### WHAT-IF

```text
WHAT-IF rollback service?
WHAT-IF disable service?
WHAT-IF remove service?
```

A `WHAT-IF` query estimates the affected service set by combining downstream call-graph reachability and causal successors from the maintained lagged-correlation graph.

---

## Core algorithmic components

### 1. Dynamic topology

`DynamicTopology` maintains directed call edges:

```python
engine.add_call("web", "checkout")
engine.add_call("checkout", "payment")
```

The maintenance and retrieval code uses a D-hop neighborhood around the symptom service:

```python
ball = engine.topology.d_hop_ball("web", depth=3)
```

### 2. Lagged-correlation graph

`OnlineCausalGraph` stores sufficient statistics for ordered node pairs:

```text
n, sum_x, sum_y, sum_x2, sum_y2, sum_xy, sum_lag, anomaly_count
```

Pearson correlation is computed from the sufficient statistics without materializing sample vectors. Fisher z-test pruning keeps only statistically reliable directed temporal associations.

### 3. Multimodal alignment index

`AlignmentIndex` stores per-service sorted lists of events and anomalies. Range queries use binary search:

```python
events = engine.index.query_events("payment", left=100.0, right=200.0)
anoms = engine.index.query_anomalies("payment", left=100.0, right=200.0)
```

### 4. Causally-gated retrieval

The gated neighborhood is a strict subset of the D-hop topology ball. A hop is skipped only when the causal graph has enough observations between two services and all observed edges fail the Fisher test. Cold start is safe: if no edge has been observed, the gate does not prune.

```python
from online_causal_rca.index import causally_gated_neighbourhood

services = causally_gated_neighbourhood(
    "web",
    engine.topology,
    engine.causal_graph,
    depth=3,
)
```

---

## Running tests

Using the standard library:

```bash
python -m unittest discover -s tests
```

With pytest, if installed:

```bash
pytest -q
```

---

## Benchmark scripts

The scripts are smoke benchmarks for the public implementation, not exact paper-table reproduction scripts.

```bash
python scripts/benchmark_incremental.py --repeat 5
```

The benchmark validates that ingestion, local causal-stat updates, topology pruning, and query paths execute successfully on generated telemetry.

---

## Extending to real observability data

To use this code with real traces, metrics, and logs:

1. Convert telemetry into `Event` records.
2. Emit trace call edges through `attributes={"caller": ..., "callee": ...}`.
3. Replace or tune `StreamingZScoreDetector` for your anomaly detector.
4. Set `depth` according to expected propagation radius.
5. Query symptoms through RCQL.

A practical deployment adapter usually maps:

| Source | Event fields |
|---|---|
| Prometheus / OpenTelemetry metrics | `modality="metric"`, `signal=<metric_name>`, numeric `value` |
| Distributed traces | `modality="trace"`, `signal="span_latency_ms"`, numeric latency plus caller/callee attributes |
| Structured logs | `modality="log"`, `signal=<template_or_error_type>`, severity/message attributes |

---

## Design notes and limitations

- The causal graph represents **directed temporal association**. It should not be interpreted as interventional causality without additional assumptions.
- The default anomaly detector is intentionally simple. It is suitable for demos and smoke tests, not as a production-grade detector.
- The repository does not include RCAEval datasets or private benchmark artifacts.
- The synthetic generator is only for validating the mechanics of the pipeline.
- The code favors readability and public reproducibility over micro-optimized performance.

---

## Public release checklist

Before uploading to GitHub, consider updating:

- author names and affiliations in `pyproject.toml` and `CITATION.cff`,
- repository URL in this README,
- paper BibTeX once the final title/venue is fixed,
- optional badges for CI, license, and Python version,
- real benchmark adapters if data licensing permits release.

---

## Citation

If this repository helps your work, please cite the corresponding paper:

```bibtex
@inproceedings{onlinecausalrca2026,
  title     = {Online Causal-Graph Maintenance and Interactive Querying for Root-Cause Analysis in Microservice Systems},
  author    = {Anonymous Authors},
  booktitle = {Proceedings of the IEEE International Conference on Data Engineering},
  year      = {2026},
  note      = {Public reference implementation}
}
```

---

## License

MIT License. See [`LICENSE`](LICENSE).
