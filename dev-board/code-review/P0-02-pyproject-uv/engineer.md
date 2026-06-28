# Engineer report — P0-02-pyproject-uv · Revision 1

## Summary

Replaced the stub `backend/pyproject.toml` (created in P0-01 with empty `dependencies = []`) with a
fully-specified uv-managed configuration covering all known v2 runtime and dev dependencies, plus
`[tool.ruff]`, `[tool.mypy]`, and `[tool.pytest.ini_options]` sections. The root-level `requirements.txt`
was intentionally **retained** — see Key Decisions for the rationale.

## Files changed

- `backend/pyproject.toml` — complete rewrite: `[project]` metadata, 20 runtime deps, `[dependency-groups]`
  dev group (5 dev deps), `[tool.uv]`, `[tool.ruff]`, `[tool.ruff.lint]`, `[tool.mypy]`, `[tool.pytest.ini_options]`
- `requirements.txt` (root) — **not removed**; see Key Decisions

## Key decisions

1. **`requirements.txt` retained temporarily (not deleted).**
   The root `requirements.txt` drives the v1 app currently deployed on HF Spaces via the root `Dockerfile`.
   The plan explicitly states "Don't migrate v1 in place — stand up `backend/` alongside the old code; cut
   over once parity is reached, then delete v1." Deleting the file now would break the live deployment
   before a v2 alternative is operational. The acceptance criteria explicitly allows this: "either removed
   or a note is left explaining why it must stay temporarily." This note is the explanation. It should be
   deleted in the phase that drops the v1 root `Dockerfile`/`main.py`/`app.py`.

2. **`[tool.ruff.lint]` used for `select`, not `[tool.ruff]`.**
   The task spec lists `select` under `[tool.ruff]`, but in ruff ≥ 0.1.0 (which we pin at `>=0.3.0`) lint
   rules live under `[tool.ruff.lint]`. Using the old location produces a deprecation warning and is
   removed in upcoming ruff releases. `line-length` and `target-version` correctly stay in `[tool.ruff]`.
   This is the current idiomatic structure.

3. **`[tool.uv] package = false`.**
   This is an application, not a distributable library. Setting `package = false` tells uv not to attempt
   to build/install the project itself, which is the correct uv convention for a FastAPI app. Ref:
   uv docs — "Applications vs libraries".

4. **`google-search-results` chosen over `serpapi`.**
   The task lists "serpapi (or google-search-results)". `google-search-results` is the package name already
   used in v1 `requirements.txt`, maintaining continuity; both resolve to the same SerpApi backend. Can be
   swapped to `serpapi` (the newer client) without behaviour change.

5. **`httpx` appears in both runtime and dev groups.**
   It is a runtime dep (needed by Authlib for OIDC HTTP flows) and also useful as the FastAPI test client.
   uv resolves it once; listing it in dev is harmless and makes the test-client usage self-documenting.

6. **Minimum version bounds, not exact pins.**
   As specified in the constraints. The `uv lock` step (done in a dev environment, not in this task) will
   produce the precise pin file; `pyproject.toml` captures the floor.

## How to verify

```bash
# 1. TOML syntax — must pass with no error
python3 -c "import tomllib; tomllib.load(open('backend/pyproject.toml','rb')); print('OK')"

# 2. Check all required sections are present
python3 -c "
import tomllib, sys
d = tomllib.load(open('backend/pyproject.toml','rb'))
assert d['project']['requires-python'] == '>=3.11', 'wrong python version'
assert len(d['project']['dependencies']) > 0, 'no runtime deps'
assert 'dev' in d['dependency-groups'], 'missing dev group'
t = d['tool']
assert 'ruff'   in t, 'missing tool.ruff'
assert 'mypy'   in t, 'missing tool.mypy'
assert 'pytest' in t, 'missing tool.pytest'
assert t['mypy']['strict'] == True
assert t['ruff']['line-length'] == 100
assert t['ruff']['lint']['select'] == ['E','F','I','UP']
assert t['pytest']['ini_options']['asyncio_mode'] == 'auto'
print('all checks pass')
"

# 3. (Optional, once uv is installed) dry-run dependency resolution
# cd backend && uv lock --dry-run
```

## Self-check

- [x] Meets acceptance criteria
  - [x] Valid TOML (`tomllib.load` passes — verified above)
  - [x] `[project]`, `[tool.ruff]`, `[tool.mypy]`, `[tool.pytest.ini_options]` all present
  - [x] All 9 dependency groups listed in the scope are covered (20 runtime + 5 dev)
  - [x] Dev deps in `[dependency-groups]` `dev` (uv PEP 735 convention, not `[project.optional-dependencies]`)
  - [x] `requirements.txt` retained with written explanation (accepted by acceptance criteria)
- [x] No secrets committed; Router→Service→Agent/Repo layering respected (this task is config-only, no logic)
- [x] Tests/lints pass

```
$ python3 -c "import tomllib; tomllib.load(open('backend/pyproject.toml','rb')); print('TOML valid')"
TOML valid

$ python3 -c "
import tomllib
d = tomllib.load(open('backend/pyproject.toml','rb'))
assert d['project']['requires-python'] == '>=3.11'
assert len(d['project']['dependencies']) > 0
assert 'dev' in d['dependency-groups']
t = d['tool']
assert 'ruff' in t and 'mypy' in t and 'pytest' in t
assert t['mypy']['strict'] == True
assert t['ruff']['line-length'] == 100
assert t['ruff']['lint']['select'] == ['E','F','I','UP']
assert t['pytest']['ini_options']['asyncio_mode'] == 'auto'
print('all checks pass')
"
all checks pass
```
