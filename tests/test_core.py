import threading
import unittest
from metric_counter import Counter, Histogram


class TestCounter(unittest.TestCase):
    def test_basic_increment(self):
        c = Counter("requests", max_labels=10)
        c.inc("200")
        c.inc("200")
        c.inc("500", 3)
        values, overflow = c.snapshot()
        self.assertEqual(values, {"200": 2.0, "500": 3.0})
        self.assertEqual(overflow, 0.0)

    def test_max_labels_enforced(self):
        c = Counter("routes", max_labels=2)
        c.inc("a")
        c.inc("b")
        c.inc("c", 5)
        values, overflow = c.snapshot()
        self.assertEqual(set(values.keys()), {"a", "b"})
        self.assertEqual(overflow, 5.0)

    def test_existing_key_not_dropped_at_cap(self):
        c = Counter("routes", max_labels=2)
        c.inc("a")
        c.inc("b")
        c.inc("a", 10)
        values, overflow = c.snapshot()
        self.assertEqual(values, {"a": 11.0, "b": 1.0})
        self.assertEqual(overflow, 0.0)

    def test_negative_increment_rejected(self):
        c = Counter("x", max_labels=1)
        with self.assertRaises(ValueError):
            c.inc("k", -1)

    def test_zero_max_labels(self):
        c = Counter("x", max_labels=0)
        c.inc("a")
        c.inc("b", 4)
        values, overflow = c.snapshot()
        self.assertEqual(values, {})
        self.assertEqual(overflow, 5.0)

    def test_negative_max_labels_rejected(self):
        with self.assertRaises(ValueError):
            Counter("x", max_labels=-1)

    def test_concurrent_increment(self):
        c = Counter("jobs", max_labels=1000)
        def worker(n):
            for _ in range(n):
                c.inc("shared")
        threads = [threading.Thread(target=worker, args=(500,)) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        values, _ = c.snapshot()
        self.assertEqual(values["shared"], 2000.0)


class TestHistogram(unittest.TestCase):
    def test_observe_placement(self):
        h = Histogram("latency", buckets=[0.1, 0.5, 1.0], max_labels=5)
        h.observe("api", 0.05)
        h.observe("api", 0.3)
        h.observe("api", 0.7)
        h.observe("api", 2.0)
        snap = h.snapshot()
        self.assertEqual(snap["api"]["counts"], (1, 1, 1, 1))
        self.assertEqual(snap["api"]["sum"], 3.05)
        self.assertEqual(snap["api"]["count"], 4)

    def test_observe_on_edge_goes_to_that_bucket(self):
        h = Histogram("lat", buckets=[1, 2], max_labels=2)
        h.observe("k", 1.0)
        h.observe("k", 2.0)
        snap = h.snapshot()
        self.assertEqual(snap["k"]["counts"], (1, 1, 0))

    def test_max_labels_enforced(self):
        h = Histogram("lat", buckets=[1.0], max_labels=2)
        h.observe("a", 0.5)
        h.observe("b", 0.5)
        h.observe("c", 0.5)
        snap = h.snapshot()
        self.assertEqual(set(snap.keys()), {"a", "b"})
        self.assertEqual(h.overflow, 1)

    def test_existing_label_not_dropped_at_cap(self):
        h = Histogram("lat", buckets=[1.0], max_labels=2)
        h.observe("a", 0.5)
        h.observe("b", 0.5)
        h.observe("a", 0.5)
        snap = h.snapshot()
        self.assertEqual(snap["a"]["counts"], (2, 0))
        self.assertEqual(snap["a"]["count"], 2)
        self.assertEqual(h.overflow, 0)

    def test_nan_rejected(self):
        h = Histogram("lat", buckets=[1.0], max_labels=2)
        with self.assertRaises(ValueError):
            h.observe("a", float("nan"))

    def test_inf_rejected(self):
        h = Histogram("lat", buckets=[1.0], max_labels=2)
        with self.assertRaises(ValueError):
            h.observe("a", float("inf"))
        with self.assertRaises(ValueError):
            h.observe("a", float("-inf"))

    def test_buckets_must_be_strictly_ascending(self):
        with self.assertRaises(ValueError):
            Histogram("lat", buckets=[1.0, 1.0], max_labels=2)
        with self.assertRaises(ValueError):
            Histogram("lat", buckets=[2.0, 1.0], max_labels=2)

    def test_empty_buckets_rejected(self):
        with self.assertRaises(ValueError):
            Histogram("lat", buckets=[], max_labels=2)

    def test_non_finite_buckets_rejected(self):
        with self.assertRaises(ValueError):
            Histogram("lat", buckets=[1.0, float("inf")], max_labels=2)

    def test_zero_max_labels(self):
        h = Histogram("lat", buckets=[1.0], max_labels=0)
        h.observe("a", 0.5)
        h.observe("b", 0.5)
        self.assertEqual(h.snapshot(), {})
        self.assertEqual(h.overflow, 2)

    def test_concurrent_observe(self):
        h = Histogram("lat", buckets=[0.5], max_labels=1000)
        def worker(n):
            for _ in range(n):
                h.observe("shared", 0.1)
        threads = [threading.Thread(target=worker, args=(500,)) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        snap = h.snapshot()
        self.assertEqual(snap["shared"]["counts"], (2000, 0))
        self.assertEqual(snap["shared"]["count"], 2000)


if __name__ == "__main__":
    unittest.main()
