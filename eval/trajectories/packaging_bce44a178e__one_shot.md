# packaging_bce44a178e — one_shot

- repository: `pypa/packaging` at `e7f035135278`
- workload: `benchmarks.markers.TimeMarkerSuite.time_constructor`
- starting point: **33,757,056** instructions
- the maintainer's patch: **32,740,814** instructions
- outcome: kept round 1, 29,372,743 instructions
- stopped because: one attempt, by design

Every measurement below was taken by the harness in a container the agent cannot reach. The agent proposed patches and was told the resulting count; it never measured anything itself.

### Round 1  ← kept

29,372,743 instructions (+13.0%), 431% of the expert's reduction

```diff
-import contextlib
-    from collections.abc import Generator, Mapping
+    from collections.abc import Mapping
+    from types import TracebackType
+    __slots__ = ("name", "position", "text")
+
+    __slots__ = ("next_token", "position", "rules", "source")
+
-        if self.check(name):
-            self.read()
+        assert self.next_token is None, (
+            f"Cannot check for {name!r}, already have {self.next_token!r}"
… and 100 more changed line(s)
```
