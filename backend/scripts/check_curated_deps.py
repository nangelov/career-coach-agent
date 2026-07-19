#!/usr/bin/env python3
"""Guard against curated-CI-dependency drift.

Backend CI (``.github/workflows/backend-ci.yml``) and ``backend/Makefile``'s
``install`` target deliberately do NOT run a full ``uv sync``. Instead they run
``uv sync --only-group dev`` plus a hand-curated ``uv pip install <light-deps>``
list, so the heavy ML stack (torch via sentence-transformers, docling, …) is not
pulled into the lint/type-check/test venv — that stack is never exercised there
and is wasteful on a free CI tier.

The recurring failure mode this script exists to kill (it has broken the real
pipeline six times — FIX-01/02/03/04/09/11, most recently ``reportlab`` in P7):
a new *always-imported* runtime dependency lands in ``pyproject.toml`` but nobody
adds it to the curated list, so it only blows up later as a cryptic
``ModuleNotFoundError`` deep in ``pytest`` collection on ``main``/``version-2``.

This is a *static* check (no third-party imports — stdlib ``tomllib`` only, so it
can run as an early CI step BEFORE any dependency is installed). It:

  1. Reads ``[project].dependencies`` from ``backend/pyproject.toml``.
  2. Reads the curated ``uv pip install`` package list from BOTH the CI workflow
     and the Makefile ``install`` target.
  3. Fails, naming the exact package(s), if a declared runtime dependency is
     absent from the curated list(s) and is not covered by the dev group or the
     documented intentional-exclusion allowlist below.
  4. Fails if the CI and Makefile curated lists have drifted apart from each
     other (the workflow comment says "keep in sync" — this enforces it).

It does NOT flag curated-but-undeclared extras (e.g. ``aiosqlite``, a test-only
driver): the recurring bug is always "declared but not curated", never the
reverse.

Exit 0 = clean; exit 1 = drift (with an actionable message).

    python scripts/check_curated_deps.py     # from backend/
"""

from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path

# ---------------------------------------------------------------------------
# Intentional-exclusion allowlist: runtime deps declared in pyproject.toml that
# are DELIBERATELY kept out of the curated CI/Makefile venv. Each entry needs a
# one-line reason so the next person adding a light dep knows why the guard lets
# these through (and why *their* new dep probably shouldn't be added here).
#
# The rule for a new dependency: if app/ imports it at module scope (so pytest
# hits it during collection) and it has no heavy/ML/C-extension transitives, it
# belongs in the CURATED LIST, not on this allowlist.
# ---------------------------------------------------------------------------
INTENTIONAL_EXCLUSIONS: dict[str, str] = {
    "uvicorn": "ASGI server; only referenced in docstrings, never imported at test collection.",
    "redis": "imported at module scope but installed transitively via the curated 'celery[redis]'.",
    "sentence-transformers": "heavy ML stack (torch); lazily imported by embeddings, excluded.",
    "transformers": "heavy ML stack (torch); lazily imported by the injection classifier (S8).",
    "docling": "heavy ML doc-intelligence stack; lazily imported (see FIX-04 import guard).",
    "langmem": "P9 teachable memory; declared but not yet imported anywhere in app/.",
    "pillow": "imaging lib; only a deferred import inside app/ingestion/ocr_parser.py.",
    "pytesseract": "OCR fallback; lazily imported, needs the system 'tesseract' binary.",
    "ocrmypdf": "OCR fallback; lazily imported, needs Ghostscript + qpdf.",
    "google-search-results": "serpapi client; not yet imported at module scope in app/.",
}


def normalize(name: str) -> str:
    """PEP 503-ish name normalisation: drop extras/version/markers, lower-case, '_'->'-'."""
    # Strip a leading/trailing quote left by tokenising (e.g. "celery[redis]").
    token = name.strip().strip("\"'")
    # Cut off at the first extras bracket / version specifier / env marker char.
    base = re.split(r"[\[<>=!~; ]", token, maxsplit=1)[0]
    return base.strip().lower().replace("_", "-")


def _join_continuations(text: str) -> list[str]:
    """Collapse shell/YAML backslash line-continuations into single logical lines.

    Full-line comments (``#`` after optional whitespace — YAML and Makefile alike)
    are dropped first, so a stray ``uv pip install`` mention in a comment cannot be
    mistaken for the real curated command.
    """
    logical: list[str] = []
    buffer = ""
    for raw in text.splitlines():
        if raw.lstrip().startswith("#"):
            continue
        stripped = raw.rstrip()
        if stripped.endswith("\\"):
            buffer += stripped[:-1] + " "
        else:
            logical.append(buffer + stripped)
            buffer = ""
    if buffer:
        logical.append(buffer)
    return logical


def curated_from_text(text: str) -> set[str]:
    """Extract normalised package names from a file's ``uv pip install ...`` command.

    Works for both the YAML ``run:`` block and the Makefile recipe: join backslash
    continuations, find the ``uv pip install`` line, then take every token that is
    not a flag. Tokens keep their quoting from the source (e.g. ``"celery[redis]"``);
    ``normalize`` strips quotes/extras/versions.
    """
    packages: set[str] = set()
    for line in _join_continuations(text):
        marker = "uv pip install"
        idx = line.find(marker)
        if idx == -1:
            continue
        remainder = line[idx + len(marker) :]
        for token in remainder.split():
            if token.startswith("-"):  # flags like --no-sync
                continue
            name = normalize(token)
            if name:
                packages.add(name)
    return packages


def deps_from_pyproject(data: dict[str, object]) -> tuple[set[str], set[str]]:
    """Return (runtime deps, dev-group deps) as normalised name sets."""
    project = data.get("project", {})
    runtime_raw = project.get("dependencies", []) if isinstance(project, dict) else []
    groups = data.get("dependency-groups", {})
    dev_raw = groups.get("dev", []) if isinstance(groups, dict) else []
    runtime = {normalize(d) for d in runtime_raw if isinstance(d, str)}
    dev = {normalize(d) for d in dev_raw if isinstance(d, str)}
    return runtime, dev


def find_problems(
    runtime: set[str],
    dev: set[str],
    curated_ci: set[str],
    curated_make: set[str],
    allowlist: dict[str, str],
) -> list[str]:
    """Return a list of human-readable problem messages (empty == clean)."""
    problems: list[str] = []

    # (1) The two curated lists must be identical to each other.
    only_ci = curated_ci - curated_make
    only_make = curated_make - curated_ci
    if only_ci or only_make:
        detail = []
        if only_ci:
            detail.append(f"only in backend-ci.yml: {sorted(only_ci)}")
        if only_make:
            detail.append(f"only in backend/Makefile: {sorted(only_make)}")
        problems.append(
            "Curated install lists have drifted between backend-ci.yml and "
            "backend/Makefile (they must be identical): " + "; ".join(detail)
        )

    curated = curated_ci | curated_make
    covered = curated | dev | set(allowlist)

    # (2) Every declared runtime dep must be curated, dev-installed, or allowlisted.
    missing = sorted(runtime - covered)
    for pkg in missing:
        problems.append(
            f"'{pkg}' is a declared runtime dependency in pyproject.toml but is NOT in the "
            "curated CI/Makefile install list (and not on the intentional-exclusion allowlist). "
            "Add it to BOTH the 'uv pip install' line in .github/workflows/backend-ci.yml and "
            "backend/Makefile's 'install' target, or — if it is lazily imported / part of the "
            "heavy ML stack — add it to INTENTIONAL_EXCLUSIONS in scripts/check_curated_deps.py "
            "with a reason."
        )

    # (3) Keep the allowlist honest: an entry no longer declared is stale.
    stale = sorted(set(allowlist) - runtime)
    for pkg in stale:
        problems.append(
            f"'{pkg}' is on the intentional-exclusion allowlist but is no longer a declared "
            "runtime dependency in pyproject.toml. Remove it from INTENTIONAL_EXCLUSIONS in "
            "scripts/check_curated_deps.py."
        )

    return problems


def run_check(backend_dir: Path, repo_root: Path) -> list[str]:
    """Load the real project files and return any problems."""
    with (backend_dir / "pyproject.toml").open("rb") as fh:
        data = tomllib.load(fh)
    runtime, dev = deps_from_pyproject(data)
    curated_ci = curated_from_text(
        (repo_root / ".github" / "workflows" / "backend-ci.yml").read_text(encoding="utf-8")
    )
    curated_make = curated_from_text((backend_dir / "Makefile").read_text(encoding="utf-8"))
    return find_problems(runtime, dev, curated_ci, curated_make, INTENTIONAL_EXCLUSIONS)


def main() -> int:
    here = Path(__file__).resolve()
    backend_dir = here.parents[1]
    repo_root = here.parents[2]
    problems = run_check(backend_dir, repo_root)
    if problems:
        print("Curated-dependency guard FAILED:\n", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}\n", file=sys.stderr)
        return 1
    print("Curated-dependency guard OK: curated CI/Makefile lists cover every runtime dep.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
