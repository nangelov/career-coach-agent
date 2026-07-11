---
name: feedback-sqlalchemy-columnelement
description: strict mypy widening error when reassigning a SQLAlchemy where-condition from a BinaryExpression to an or_/and_ result
metadata:
  type: feedback
---

When you build a WHERE condition incrementally and reassign it — e.g. start with
`cond = Model.col.is_(None)` then `cond = or_(cond, Model.col == x)` — strict mypy fails with
`Incompatible types in assignment (expression has type "ColumnElement[bool]", variable has
type "BinaryExpression[bool]")`. `is_()`/`==` infer the narrow `BinaryExpression[bool]`, but
`or_()`/`and_()` return the wider `ColumnElement[bool]`.

**Why:** mypy pins the variable's type to the first (narrower) assignment.

**How to apply:** annotate the variable up front as the wider type —
`cond: ColumnElement[bool] = Model.col.is_(None)` (import `from sqlalchemy import
ColumnElement`). Applies to any repository/agent code that composes filters conditionally.
