# Metric Counter

Bounded-cardinality counters and histograms for Python. Keeps memory predictable by capping the number of distinct label values tracked per metric.

## Usage

```python
from metric_counter import Counter, Histogram

# Counter: at most 100 distinct label values
requests = Counter("requests", max_labels=100)
requests.inc("200")
requests.inc("500", 3)
values, dropped = requests.snapshot()  # (dict, float)

# Histogram: fixed buckets, capped label cardinality
latency = Histogram("latency", buckets=[0.1, 0.5, 1.0], max_labels=100)
latency.observe("/api", 0.27)
snapshot = latency.snapshot()  # dict[label] = {counts, sum, count}
```

## Why

Metrics libraries that accept arbitrary label values can have their memory blown up by a single high-cardinality field — a user ID, a trace ID, an unbounded path parameter. This library enforces the cap at the data-structure level: once `max_labels` distinct values have been seen, further new values are dropped and counted in `overflow`.

The trade-off is that dropped data is gone — there is no eviction, no sampling, no LRU. The win is that the hot path for an existing label is one dict lookup and one addition, with no allocation, which matters when the metric sits on a request critical path.

## Edge cases

- When the label cap is exceeded, the increment or observation is **silently** dropped and `overflow` is bumped. There is no exception. Check `overflow` if you need to detect this.
- `Counter.inc` rejects negative amounts (counters are monotonic). `Histogram.observe` rejects NaN and infinities — they cannot be placed in a finite bucket and would poison the sum.
- Bucket edges must be strictly ascending and finite. An implicit `+Inf` bucket captures values above the last edge; `snapshot().counts` has one more entry than `buckets`.

## API

### `Counter(name, *, max_labels, clock=None)`

- `.inc(label, amount=1.0)` — increment; new labels beyond the cap are dropped.
- `.snapshot()` → `(dict[label, float], float)` — copy of values and the overflow total.
- `.overflow` → float
- `.name`, `.max_labels`

### `Histogram(name, *, buckets, max_labels, clock=None)`

- `.observe(label, value)` — record; new labels beyond the cap are dropped.
- `.snapshot()` → `dict[label, {"counts": tuple, "sum": float, "count": int}]`
- `.overflow` → int
- `.buckets` → tuple of edges (without the implicit +Inf)
- `.name`, `.max_labels`

The `clock` argument is accepted for test injection and is unused by these two classes themselves.

## Running tests

```
PYTHONPATH=src python -m unittest discover -s tests
```

## Performance

The window keeps a bounded buffer, so `push` is constant time and memory does not
grow with the length of the stream. `peak` and `trough` are linear in the window
size, which is the trade that keeps `push` cheap.

