---
name: project-rowcount-and-cast-collision
description: Reading rowcount off an async delete needs a CursorResult cast; watch the sqlalchemy.cast vs typing.cast name clash
metadata:
  type: project
---

Bulk `delete()`/`update()` via `await session.execute(...)` returns a `Result` typed object;
`result.rowcount` fails mypy with `"Result[Any]" has no attribute "rowcount"`. Cast to
`CursorResult[Any]` (precedent: `app/repositories/dashboard_store.py`).

**Gotcha:** `app/repositories/vector_search.py` already imports `cast` from **sqlalchemy** (the
SQL `cast(expr, Float)` used in RRF). So `typing.cast` collides — import it aliased
(`from typing import cast as type_cast`) and put `from sqlalchemy import CursorResult` under
`TYPE_CHECKING`. Don't blindly copy `cast("CursorResult[Any]", result)` into a module that uses
sqlalchemy.cast.

**How to apply:** when a repo primitive returns affected-row counts, cast; check which `cast` the
module's namespace already holds before adding the typing one.
