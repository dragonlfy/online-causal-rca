from __future__ import annotations

import unittest

from online_causal_rca import CausalNode, DynamicTopology, Event, OnlineCausalRCAEngine
from online_causal_rca.causal import LaggedEdgeStats, OnlineCausalGraph
from online_causal_rca.query import parse_rcql, WhatIfStatement, WhyStatement
from online_causal_rca.synthetic import generate_incident


class TestCore(unittest.TestCase):
    def test_fisher_edge_stats(self):
        s = LaggedEdgeStats()
        for i in range(20):
            s.update(float(i), float(i) * 2.0, 1.0)
        self.assertGreater(s.pearson(), 0.99)
        self.assertTrue(s.is_significant(alpha=0.10, min_samples=5))

    def test_topology_ball(self):
        topo = DynamicTopology.from_edges([("a", "b"), ("b", "c"), ("c", "d")])
        self.assertEqual(topo.d_hop_ball("a", 2), {"a", "b", "c"})
        self.assertEqual(topo.downstream("b", 2), {"c", "d"})

    def test_rcql_parse(self):
        why = parse_rcql("WHY web.span_latency_ms > 500 ms?")
        self.assertIsInstance(why, WhyStatement)
        self.assertEqual(why.service, "web")
        self.assertEqual(why.signal, "span_latency_ms")
        what = parse_rcql("WHAT-IF rollback payment?")
        self.assertIsInstance(what, WhatIfStatement)

    def test_engine_demo(self):
        engine = OnlineCausalRCAEngine(depth=3, lookback=120)
        anomalies = engine.ingest_many(generate_incident(seed=13))
        self.assertGreater(len(anomalies), 0)
        res = engine.run_rcql("WHY web.span_latency_ms > 500 ms?")
        self.assertGreater(len(res.candidates), 0)
        # Root service should be visible in the evidence set for the synthetic incident.
        self.assertIn("payment", {c.service for c in res.candidates})
        blast = engine.run_rcql("WHAT-IF rollback payment?")
        self.assertGreaterEqual(len(blast.blast_radius), 1)


if __name__ == "__main__":
    unittest.main()
