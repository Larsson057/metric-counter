"""Metric Counter: bounded-cardinality counters and histograms.

This package provides simple metric primitives — a Counter and a Histogram —
that enforce a fixed upper bound on the number of distinct label values they
will track. The bound is the defining feature: it makes the memory footprint
predictable and prevents accidental cardinality explosions from unbounded
inputs (e.g. user IDs, trace IDs) from consuming all available memory.

Only the two classes below are part of the public API:
    Counter, Histogram

Design trade-off: when the bound is exceeded the new label value is silently
ignored and a separate overflow counter is incremented. An alternative would
be to raise or to evict the least-recently-used entry, but silent ignore keeps
the hot path allocation-free and branch-light, which matters when metrics sit
on a request critical path.
"""

from .core import Counter, Histogram

__all__ = ["Counter", "Histogram"]
