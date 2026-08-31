# packaging_bce44a178e — one_shot_profile

- repository: `pypa/packaging` at `e7f035135278`
- workload: `benchmarks.markers.TimeMarkerSuite.time_constructor`
- starting point: **33,757,056** instructions
- the maintainer's patch: **32,740,814** instructions
- outcome: kept round 1, 32,094,655 instructions
- stopped because: one attempt, by design

Every measurement below was taken by the harness in a container the agent cannot reach. The agent proposed patches and was told the resulting count; it never measured anything itself.

### Round 1  ← kept

32,094,655 instructions (+4.9%), 164% of the expert's reduction

```diff
-from dataclasses import dataclass
-from typing import TYPE_CHECKING, NoReturn
+from typing import TYPE_CHECKING, NamedTuple, NoReturn
-@dataclass
-class Token:
+class Token(NamedTuple):
-        self.next_token: Token | None = None
+        # The pending token is held as the match that produced it. Most tokens
+        # are only stepped over, never looked at, and holding the match means
+        # those never have to be built into a Token at all.
+        self.next_match: re.Match[str] | None = None
+        self.next_name = ""
… and 30 more changed line(s)
```
