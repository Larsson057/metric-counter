from __future__ import annotations

import threading
from bisect import bisect_left
from typing import Callable, Dict, List, Optional, Sequence, Tuple


__all__ = ["Counter", "Histogram"]


class Counter:
    """A monotonic counter keyed by a single string label, with a hard cap on
    the number of distinct values.

    The cap (``max_labels``) is checked once per distinct key: the first time a
    new key is seen, the internal dict either grows to hold it or, if at the
    cap, the increment is dropped and ``overflow`` is bumped instead. This is a
    deliberate trade-off: the hot path for an existing key is a single dict
    lookup and an addition, with no allocation.

    A clock callable may be supplied purely so that tests can inject a fake
    clock; it is unused by the counter itself but is part of the signature so
    that subclasses (e.g. rate calculators) can share the same fake time.
    """

    def __init__(
        self,
        name: str,
        *,
        max_labels: int,
        clock: Optional[Callable[[], float]] = None,
    ) -> None:
        if max_labels < 0:
            raise ValueError("max_labels must be non-negative")
        self._name = name
        self._max = max_labels
        self._values: Dict[str, float] = {}
        self._overflow = 0.0
        # Lock guards _values and _overflow so inc() is safe to call from
        # multiple threads. A plain dict is not atomic across get-or-set.
        self._lock = threading.Lock()
        self._clock = clock or (lambda: 0.0)

    @property
    def name(self) -> str:
        return self._name

    @property
    def max_labels(self) -> int:
        return self._max

    def inc(self, label: str, amount: float = 1.0) -> None:
        """Increment ``label`` by ``amount``.

        If ``label`` is new and the distinct-count cap has been reached, the
        increment is discarded and ``overflow`` is incremented instead. A
        negative ``amount`` raises: counters are monotonic by contract, and
        allowing negatives would silently turn this into a gauge.
        """
        if amount < 0:
            raise ValueError("counter increments must be non-negative")
        with self._lock:
            existing = self._values.get(label)
            if existing is not None:
                self._values[label] = existing + amount
                return
            if len(self._values) < self._max:
                self._values[label] = amount
            else:
                self._overflow += amount

    @property
    def overflow(self) -> float:
        """Total mass of increments dropped due to the label cap."""
        return self._overflow

    def snapshot(self) -> Tuple[Dict[str, float], float]:
        """Return a shallow copy of the current values and the overflow total.

        The copy is shallow on purpose: callers are expected to treat the
        returned dict as read-only, and a deep copy of float values would buy
        nothing at real cost.
        """
        with self._lock:
            return dict(self._values), self._overflow


class Histogram:
    """A fixed-bucket histogram keyed by a single string label, with a hard
    cap on the number of distinct label values.

    Buckets are defined once at construction by their upper-bound edges. The
    edges must be strictly ascending and finite; an implicit ``+Inf`` bucket
    captures everything above the last edge. Each observation is routed to the
    smallest bucket whose edge is >= the value, using ``bisect`` for O(log n)
    placement.

    The cardinality cap applies to label values, not buckets: a histogram with
    10 buckets and ``max_labels=100`` holds at most 100*(10+1) counts plus 100
    sums and 100 observation totals.
    """

    def __init__(
        self,
        name: str,
        *,
        buckets: Sequence[float],
        max_labels: int,
        clock: Optional[Callable[[], float]] = None,
    ) -> None:
        if max_labels < 0:
            raise ValueError("max_labels must be non-negative")
        edges = list(buckets)
        if not edges:
            raise ValueError("buckets must not be empty")
        # Strictly-ascending check: duplicate or equal edges would make bucket
        # assignment ambiguous and waste a bucket slot.
        for i in range(1, len(edges)):
            if edges[i] <= edges[i - 1]:
                raise ValueError("buckets must be strictly ascending")
        if any(not _is_finite(e) for e in edges):
            raise ValueError("buckets must be finite")
        self._name = name
        self._edges: List[float] = edges
        self._max = max_labels
        self._counts: Dict[str, List[int]] = {}
        self._sums: Dict[str, float] = {}
        self._totals: Dict[str, int] = {}
        self._overflow = 0
        self._lock = threading.Lock()
        self._clock = clock or (lambda: 0.0)

    @property
    def name(self) -> str:
        return self._name

    @property
    def max_labels(self) -> int:
        return self._max

    @property
    def buckets(self) -> Tuple[float, ...]:
        """The configured upper-bound edges (without the implicit +Inf bucket)."""
        return tuple(self._edges)

    def observe(self, label: str, value: float) -> None:
        """Record ``value`` under ``label``.

        Non-finite values (NaN, +Inf, -Inf) are rejected with ValueError: a
        histogram cannot meaningfully place them in a finite bucket, and
        including them would poison the sum. If ``label`` is new and the cap is
        reached, the observation is dropped and ``overflow`` is incremented.
        """
        if not _is_finite(value):
            raise ValueError("observed value must be finite")
        idx = bisect_left(self._edges, value)
        with self._lock:
            counts = self._counts.get(label)
            if counts is not None:
                counts[idx] += 1
                self._sums[label] += value
                self._totals[label] += 1
                return
            if len(self._counts) < self._max:
                fresh = [0] * (len(self._edges) + 1)
                fresh[idx] = 1
                self._counts[label] = fresh
                self._sums[label] = value
                self._totals[label] = 1
            else:
                self._overflow += 1

    @property
    def overflow(self) -> int:
        """Number of observations dropped due to the label cap."""
        return self._overflow

    def snapshot(self) -> Dict[str, dict]:
        """Return a read-only view of the histogram state.

        Each label maps to a dict with keys ``counts`` (a tuple aligned with
        ``buckets`` plus a final +Inf entry), ``sum``, and ``count``. The
        structure is copied so callers can iterate safely while other threads
        observe.
        """
        with self._lock:
            out: Dict[str, dict] = {}
            for label in self._counts:
                out[label] = {
                    "counts": tuple(self._counts[label]),
                    "sum": self._sums[label],
                    "count": self._totals[label],
                }
            return out


def _is_finite(x: float) -> bool:
    """Local finite check so we do not pull in math just for isfinite."""
    return x == x and x not in (float("inf"), float("-inf"))
