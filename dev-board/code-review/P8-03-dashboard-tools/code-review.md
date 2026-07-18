# Code review — P8-03-dashboard-tools · engineer revision 2

## Verdict: APPROVED

## Findings
| id | severity | file:line | issue | required change |
|----|----------|-----------|-------|-----------------|
| C1 | major → **fixed** | app/agents/dashboard_agent.py:174-264 | Read path now surfaces dashboard contents to the responder. `_summarize` renders the `read_dashboard` payload via the new `_render_dashboard_digest` and folds it into `WorkerResult.content` (goals with status/target_role/task-completion %, nested milestones + tasks, progress/streak rollup). Verified the digest keys (`goals[].title/status/target_role/task_completion_pct/milestones/tasks`, `progress.total_entries/current_streak_days/last_entry_date`) match the real `DashboardSummary`/`GoalSummary`/`ProgressSummary` schema — not decorative. Since responder `_worker_texts` grounds on `.content` only, an informational turn is now answerable. `test_node_read_turn_folds_dashboard_data_into_content` asserts both the goal title and task title reach `WorkerResult.content`. | resolved |
| C2 | nit → **fixed** | app/tools/dashboard.py:206-219 | `ProposeMilestoneTool.run` now `args.pop("goal_id", None)` and type-guards it (non-empty str) before `MilestoneCreate.model_validate(args)`. No longer relies on pydantic's `extra="ignore"` default; correct under `extra="forbid"`. | resolved |
| C3 | nit → **addressed** | app/agents/dashboard_agent.py:64 | `_MAX_TOKENS` raised to `1024` with an explanatory comment (room for several parallel tool calls' `arguments` JSON plus a wrap-up). | resolved |

## Notes
- Re-verified: `pytest tests/test_dashboard_tools.py tests/test_dashboard_agent.py -q` → **18 passed**. The C1 fix is the exact "read/informational worker stashes data in `.data` but responder grounds only on `.content`" class of bug — now closed and regression-tested at the content level (not just `data["read"]`).
- No regressions in the fix: `data` payload unchanged (`{read, proposed}`), guest/unconfigured/`LLMError` fail-soft paths untouched, `source="ai"`-only attribution preserved. Digest reads defensively (`isinstance` guards, `.get` with fallbacks) so a partial/odd summary can't raise out of the node.
- Pre-existing P8-02 `ruff format --check .` drift on 7 unrelated files persists (not this diff's regression) — still worth a separate FIX task, as noted in rev 1.

## Verdict: APPROVED
