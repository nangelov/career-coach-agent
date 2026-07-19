# Architecture review — P10-04-repl-removal-confirm · engineer revision 1

## Verdict: APPROVED

## Design conformance
| id | area | expected (design ref) | observed | gap / required change |
|----|------|-----------------------|----------|-----------------------|
| A1 | §7 Tool isolation | v1 `run_python_code` REPL removed; no arbitrary-code-execution surface in v2 tool set | Verified independently: grep of `backend/app/` for `exec(`/`eval(`/`subprocess`/`os.system`/`__import__`/`PythonREPL`/`run_python`/`pty.spawn`/`popen` returns nothing (excluding legitimate `re.compile`/`.execute()`/`.compile()`). Registered tools are exactly the known-good 7 (`current_date_and_time`, `internet_search` + dashboard bundle) — none code-exec. | none |
| A2 | Phase-fit / legacy isolation (P0-12) | v1 REPL confined to `legacy-code/`, out of the v2 tree | `legacy-code/tools/python_repl.py` still holds the v1 REPL; it sits at repo root, outside `backend/app/`. Test scans `app.__file__` parent (`backend/app`) only, so legacy code is correctly excluded from the guard's scope. | none |
| A3 | §8 target structure | change lands in the right place | Confirmation task; sole change is `backend/tests/test_no_code_exec_tool.py`. No production surface added — appropriate. | none |
| A4 | KISS / YAGNI | do not add a sandboxed evaluator speculatively | No evaluator built; engineer confirmed no current tool needs bounded math before declining. Matches task constraint + YAGNI. | none |

## Cross-cutting checks
- [x] Fits target structure (§8) + layering — test-only, no layer touched.
- [x] Honors locked decisions — v1 ReAct/REPL surface stays deleted; tool set unchanged.
- [x] Interfaces-before-implementations — n/a (no new code).
- [x] Budget posture — n/a.

## Notes
Strong regression posture: three complementary guards (exact known-good name set forcing a conscious update on any new tool; name+description denylist; source-tree scan for code-exec builtins). The source scan is the durable guarantee since a REPL cannot exist without one of those builtins. No design risks or follow-ups.
