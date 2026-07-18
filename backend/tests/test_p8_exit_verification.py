"""P8 phase-exit verification (P8-06) — the living-PDP dashboard, end to end.

A **verification-only** module (no product code changed): it ties the P8 building blocks
together and drives them as a single story, proving the plan.md P8 exit criterion:

    "user edits a plan in the UI; assistant proposes tasks from chat/PDP and the user
     approves; progress renders."

The prior per-task suites prove each piece in isolation (``test_dashboard_api`` — the CRUD
router; ``test_dashboard_service`` — the policy/summary arithmetic; ``test_dashboard_agent`` —
the chat worker/graph; ``test_pdp_service`` — the PDP loop; frontend ``Dashboard.test.tsx`` /
``dashboard.test.ts`` — the UI). **This** module proves they *compose* across the whole chain,
faking only the true external edges (the LLM completions and the DB sessions), mirroring the
P6-09 / P7-05 posture ("real stack, in-memory/fake ports, no live HF / live Postgres").

Coverage of the P8-06 task's seven points (see the per-test docstrings):

1. **User edits a plan directly** — hand-built human CRUD scenario over the real ``/api/dashboard``
   router → correct nesting + ``time_progress_pct`` / ``task_completion_pct`` in the summary.
2. **Assistant proposes tasks from chat** — a turn through the compiled graph
   (``Intent.DASHBOARD`` → the dashboard worker) lands ``source="ai"`` / ``status="proposed"`` and
   the answer says it is pending approval (never silently active).
3. **Assistant proposes tasks from a generated PDP** — the real :class:`PdpService.generate`
   seeds an AI-``proposed`` goal + milestones + tasks; a regeneration does not duplicate the goal.
4. **Approval flow** — a ``PATCH`` off ``proposed`` (approve) and a ``DELETE`` of a ``proposed``
   row (reject) both work over the real API, and the frontend client/component target exactly
   those verbs+endpoints (source scan of ``lib/dashboard.ts`` + ``GoalCard.tsx``).
5. **Progress renders** — POSTed progress entries feed ``GET /api/dashboard``'s progress summary;
   a multi-day fixture exercises the streak/last-7 arithmetic through the real aggregation.
6. **Guests correctly excluded** — the API 403s, the chat worker fails soft (no model call, no
   crash), and the frontend renders a sign-in gate (source scan of ``Dashboard.tsx``).
7. **Cross-task consistency** — only :meth:`DashboardService._resolve_status` maps source→status;
   no AI-write caller (tools / PDP seed) re-implements the ``proposed`` attribution.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable, Iterator, Sequence
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
import pytest_asyncio
from httpx import ASGITransport

from app.agents.graph import build_graph
from app.agents.state import AgentState, Intent, PlannerDecision, WorkerName
from app.api.dashboard import get_dashboard_service
from app.ingestion.profile import EducationItem, ExperienceItem, ProfileSchema
from app.llm.types import ChatMessage, CompletionResult, FunctionCall, ToolCall, ToolSchema
from app.main import app
from app.schemas.auth import CurrentUser
from app.schemas.dashboard import GoalCreate, ProgressEntryResponse
from app.security.dependencies import require_auth
from app.services.dashboard import DashboardService
from app.services.dashboard_store import InMemoryDashboardStore
from app.services.pdp import PdpGenerated, PdpService
from app.services.pdp_store import InMemoryPdpStore
from app.services.profile_store import InMemoryProfileStore
from app.services.skills_gap import SkillsGapService
from app.tools.dashboard import PROPOSE_TASK_TOOL
from tests.fakes import (
    FakeDBProvider,
    FakeExecuteResult,
    FakeSession,
    FreshSessionDBProvider,
    fake_current_user,
)

_USER = "11111111-1111-1111-1111-111111111111"
_FRONTEND = Path(__file__).resolve().parents[2] / "frontend"


# =========================================================================== #
# Shared test doubles (edges only — the dashboard chain in between is real).   #
# =========================================================================== #
class _ScriptedCompleter:
    """A scripted ``LLMCompleter``: replays queued results, one per call (records call count).

    The last queued result repeats once exhausted (a no-tool wrap-up), mirroring the
    ``test_dashboard_agent`` fake. The only faked edge is the model; the tools/service are real.
    """

    def __init__(self, results: Sequence[CompletionResult]) -> None:
        self._results = list(results)
        self.calls = 0

    async def complete(
        self,
        messages: Sequence[ChatMessage],
        *,
        tools: Sequence[ToolSchema] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> CompletionResult:
        self.calls += 1
        return self._results.pop(0) if len(self._results) > 1 else self._results[0]


def _tool_call(name: str, arguments: dict[str, Any]) -> CompletionResult:
    return CompletionResult(
        content=None,
        tool_calls=[
            ToolCall(id="c1", function=FunctionCall(name=name, arguments=json.dumps(arguments)))
        ],
        model="fake",
    )


def _final(content: str = "Done.") -> CompletionResult:
    return CompletionResult(content=content, tool_calls=[], finish_reason="stop", model="fake")


class _PdpSectionCompleter:
    """Forces the ``record_pdp`` tool call, returning a fixed six-section plan (for PdpService).

    ``learning_objectives`` and ``timeline_action_steps`` carry bullet lists (what the P8-04 seed
    parses into milestones/tasks); the other four sections are padded so the plan clears the
    ``validate_pdp_content`` length gate. The real agent fence + forced-tool-choice + parse path
    runs over it — the model is the only faked edge.
    """

    def __init__(self, sections: dict[str, str]) -> None:
        self._sections = sections

    async def complete(
        self,
        messages: Sequence[ChatMessage],
        *,
        tools: Sequence[ToolSchema] | None = None,
        tool_choice: Any = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> CompletionResult:
        from app.agents.pdp_agent import PDP_TOOL_NAME

        return CompletionResult(
            content=None,
            tool_calls=[
                ToolCall(
                    id="c1",
                    function=FunctionCall(name=PDP_TOOL_NAME, arguments=json.dumps(self._sections)),
                )
            ],
            model="fake",
        )


def _service() -> DashboardService:
    return DashboardService(InMemoryDashboardStore())


def _state(user_id: str | None = _USER, message: str = "add these tasks to my plan") -> AgentState:
    return AgentState(session_id="s", user_id=user_id, user_message=message)


def _planner_selecting_dashboard() -> Any:
    def planner(state: AgentState) -> dict[str, Any]:
        return {"plan": PlannerDecision(intent=Intent.DASHBOARD, workers=[WorkerName.DASHBOARD])}

    return planner


@pytest_asyncio.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
def wire() -> Iterator[Callable[[DashboardService, CurrentUser], None]]:
    """Point the API at a real in-memory-backed service + a chosen caller; clean up after."""

    def _as(service: DashboardService, user: CurrentUser) -> None:
        app.dependency_overrides[get_dashboard_service] = lambda: service
        app.dependency_overrides[require_auth] = lambda: user

    yield _as
    app.dependency_overrides.clear()


def _user(user_id: str = _USER, session_id: str = "s1") -> CurrentUser:
    return fake_current_user(session_id, role="user", user_id=user_id)


# =========================================================================== #
# 1. User edits a plan directly (human CRUD → correct summary).                #
# =========================================================================== #
async def test_user_edits_plan_directly_and_summary_is_correct(
    client: httpx.AsyncClient, wire: Callable[[DashboardService, CurrentUser], None]
) -> None:
    """A human builds a plan through ``/api/dashboard`` with no AI involvement: every row is
    ``source="user"`` with its normal starting status, and the summary nests it and derives
    ``time_progress_pct`` (elapsed time toward the target) + ``task_completion_pct`` correctly.

    Fixture: a goal created today with a target 100 days out (→ ~0% elapsed at creation, so a
    small non-null percentage), one milestone, two tasks, one of them completed (→ 50% done).
    """
    service = _service()
    wire(service, _user())
    target = (datetime.now(UTC).date() + timedelta(days=100)).isoformat()

    goal = (
        await client.post(
            "/api/dashboard/goals",
            json={"title": "Become a Data Engineer", "target_date": target},
        )
    ).json()
    assert goal["source"] == "user" and goal["status"] == "active"

    await client.post(f"/api/dashboard/goals/{goal['id']}/milestones", json={"title": "M1"})
    t1 = (
        await client.post("/api/dashboard/tasks", json={"goal_id": goal["id"], "title": "T1"})
    ).json()
    await client.post("/api/dashboard/tasks", json={"goal_id": goal["id"], "title": "T2"})
    assert t1["source"] == "user"

    # Human completes one of the two tasks (a plain edit).
    done = await client.patch(f"/api/dashboard/tasks/{t1['id']}", json={"status": "done"})
    assert done.status_code == 200 and done.json()["status"] == "done"

    summary = (await client.get("/api/dashboard")).json()
    assert len(summary["goals"]) == 1
    g = summary["goals"][0]
    assert len(g["milestones"]) == 1 and len(g["tasks"]) == 2  # correct nesting
    assert g["task_completion_pct"] == 50.0  # exactly one of two done
    # Elapsed time toward a 100-day-out target is a small, non-null, in-range percentage.
    assert g["time_progress_pct"] is not None and 0.0 <= g["time_progress_pct"] < 5.0


# =========================================================================== #
# 2. Assistant proposes tasks from chat (graph → source=ai/proposed, pending). #
# =========================================================================== #
async def test_assistant_proposes_from_chat_lands_proposed_and_says_pending() -> None:
    """A chat turn drives the compiled graph: the planner routes ``Intent.DASHBOARD`` and the
    dashboard worker calls ``propose_task``. The row lands ``source="ai"`` / ``status="proposed"``
    (never silently active) and the responder's answer tells the user it is pending approval.
    """
    service = _service()
    goal = await service.create_goal(_USER, GoalCreate(title="Become a Data Engineer"))
    router = _ScriptedCompleter(
        [_tool_call(PROPOSE_TASK_TOOL, {"goal_id": goal.id, "title": "Learn SQL"}), _final()]
    )
    compiled = build_graph(
        planner=_planner_selecting_dashboard(), dashboard_service=service, router=router
    )

    final = await compiled.ainvoke(_state())
    state = AgentState.model_validate(final)

    # The AI write is a pending proposal, never silently active.
    tasks = await service.list_tasks(_USER, goal.id)
    assert len(tasks) == 1
    assert tasks[0].source == "ai" and tasks[0].status == "proposed"

    # The responder's answer frames it as pending the user's approval.
    assert state.response is not None
    answer = state.response.lower()
    assert "proposed" in answer and ("approv" in answer or "pending" in answer)


# =========================================================================== #
# 3. Assistant proposes tasks from a generated PDP (seed + de-dup on regen).   #
# =========================================================================== #
def _fixture_profile() -> ProfileSchema:
    return ProfileSchema(
        skills=["Python", "Pandas"],
        goals=["Grow into a senior data role"],
        experience=[
            ExperienceItem(
                title="Data Analyst",
                company="Acme",
                start_date="2021",
                end_date="2024",
                description="Built reporting pipelines.",
            )
        ],
        education=[EducationItem(institution="State Uni", degree="BSc", field="Statistics")],
    )


def _pdp_sections() -> dict[str, str]:
    """A six-section plan whose two action sections carry bullet lists (seeded), the rest padded."""
    padded = "This section describes the plan in detail. " * 6
    return {
        "current_skills_assessment": padded,
        "skills_gap_analysis": padded,
        "learning_objectives": (
            "Milestones to reach:\n"
            "- Master Kubernetes fundamentals\n"
            "- Complete a data-engineering capstone\n"
        ),
        "recommended_training": padded,
        "timeline_action_steps": (
            "Action steps:\n"
            "- Enroll in the SQL course this month\n"
            "- Ship a portfolio project\n"
            "- Set up a CI pipeline\n"
        ),
        "progress_tracking_kpis": padded,
    }


def _pdp_service(dashboard: DashboardService, store: InMemoryPdpStore) -> PdpService:
    """The **real** :class:`PdpService` with fakes only at the LLM + DB edges (unmined role)."""
    profile_store = InMemoryProfileStore()
    profile_store._by_user[_USER] = _fixture_profile()  # noqa: SLF001 - seed the double
    # A fresh empty role read per compute() call — role never mined (best-effort plan), and the
    # regeneration below runs the gap arithmetic a second time (a single shared session would be
    # exhausted after the first generate()).
    role_db = FreshSessionDBProvider(lambda: FakeSession([FakeExecuteResult([])]))
    skills_gap = SkillsGapService(profile_store, role_db)
    return PdpService(
        profile_store=profile_store,
        skills_gap=skills_gap,
        pdp_store=store,
        router=_PdpSectionCompleter(_pdp_sections()),
        db=FakeDBProvider(FakeSession([])),  # empty gap → no resource lookup
        dashboard=dashboard,
    )


async def test_pdp_generation_seeds_proposed_rows_and_regeneration_does_not_duplicate() -> None:
    """The real PDP flow seeds an AI-``proposed`` goal + milestones (from ``learning_objectives``)
    + tasks (from ``timeline_action_steps``); regenerating the same career goal reuses the goal
    and adds no duplicates (the P8-04 de-dup rule holds after the P8-05 wiring — no regression).
    """
    dashboard = _service()
    store = InMemoryPdpStore()
    pdp = _pdp_service(dashboard, store)
    goal_text = "Data Engineer"

    result = await pdp.generate(user_id=_USER, career_goal=goal_text, target_date=date(2027, 1, 1))
    assert isinstance(result, PdpGenerated)

    goals = await dashboard.list_goals(_USER)
    assert len(goals) == 1
    goal = goals[0]
    assert goal.source == "ai" and goal.status == "proposed"  # never silently active

    milestones = await dashboard.list_milestones(_USER, goal.id) or []
    tasks = await dashboard.list_tasks(_USER, goal.id)
    assert {m.title for m in milestones} == {
        "Master Kubernetes fundamentals",
        "Complete a data-engineering capstone",
    }
    assert {t.title for t in tasks} == {
        "Enroll in the SQL course this month",
        "Ship a portfolio project",
        "Set up a CI pipeline",
    }
    assert all(m.source == "ai" and m.status == "proposed" for m in milestones)
    assert all(t.source == "ai" and t.status == "proposed" for t in tasks)

    # Regenerate the SAME goal → still one goal, no duplicate milestones/tasks (de-dup by title).
    again = await pdp.generate(user_id=_USER, career_goal=goal_text, target_date=date(2027, 1, 1))
    assert isinstance(again, PdpGenerated)
    assert len(await dashboard.list_goals(_USER)) == 1
    assert len(await dashboard.list_milestones(_USER, goal.id) or []) == len(milestones)
    assert len(await dashboard.list_tasks(_USER, goal.id)) == len(tasks)


# =========================================================================== #
# 4. Approval flow (approve = PATCH off proposed; reject = DELETE) end-to-end. #
# =========================================================================== #
async def test_approve_and_reject_proposed_rows_over_the_api(
    client: httpx.AsyncClient, wire: Callable[[DashboardService, CurrentUser], None]
) -> None:
    """The two approval actions work end-to-end over the real API, with **no** separate endpoint
    (P8-01/P8-02 ruling): approving a proposed goal is a ``PATCH`` moving it to a normal status;
    rejecting a proposed task is a ``DELETE``. AI-proposed rows are seeded via the service
    (the ``source="ai"`` path the router never exposes), then acted on through the human router.
    """
    service = _service()
    wire(service, _user())
    # Seed AI-proposed rows the way the chat/PDP path would (source="ai" → status="proposed").
    proposed_goal = await service.create_goal(_USER, GoalCreate(title="AI Goal"), source="ai")
    from app.schemas.dashboard import TaskCreate

    proposed_task = await service.create_task(
        _USER, TaskCreate(goal_id=proposed_goal.id, title="AI Task"), source="ai"
    )
    assert proposed_task is not None and proposed_task.status == "proposed"

    # Approve the goal = PATCH the proposed row to its normal status (active). Same generic route.
    approved = await client.patch(
        f"/api/dashboard/goals/{proposed_goal.id}", json={"status": "active"}
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "active" and approved.json()["source"] == "ai"

    # Reject the task = DELETE the proposed row. Same generic route.
    rejected = await client.delete(f"/api/dashboard/tasks/{proposed_task.id}")
    assert rejected.status_code == 204
    assert await service.get_task(_USER, proposed_task.id) is None


def test_frontend_approve_reject_target_the_same_verbs_and_endpoints() -> None:
    """Point 4 (frontend): the P8-05 client + card wire approve/reject to *exactly* those routes.

    Source scan (mirrors the P7-05 contract scans): ``GoalCard.tsx`` approves via ``updateGoal``/
    ``updateMilestone``/``updateTask`` with ``APPROVE_STATUS`` and rejects via ``deleteGoal``/
    ``deleteMilestone``/``deleteTask``; ``lib/dashboard.ts`` maps those to ``PATCH``/``DELETE`` on
    the same ``/api/dashboard/...`` paths the backend router serves — no dedicated approve endpoint.
    """
    card = (_FRONTEND / "components" / "dashboard" / "GoalCard.tsx").read_text(encoding="utf-8")
    for approve_call in (
        "actions.updateGoal(goal.id, { status: APPROVE_STATUS.goal })",
        "actions.updateMilestone(milestone.id, { status: APPROVE_STATUS.milestone })",
        "actions.updateTask(task.id, { status: APPROVE_STATUS.task })",
    ):
        assert approve_call in card, f"GoalCard approve should call {approve_call!r}"
    for reject_call in (
        "actions.deleteGoal(goal.id)",
        "actions.deleteMilestone(milestone.id)",
        "actions.deleteTask(task.id)",
    ):
        assert reject_call in card, f"GoalCard reject should call {reject_call!r}"

    lib = (_FRONTEND / "lib" / "dashboard.ts").read_text(encoding="utf-8")
    # Approve = PATCH the row; reject = DELETE the row — on the backend's exact paths.
    assert '"/api/dashboard/goals/${encodeURIComponent(goalId)}"' not in lib  # sanity: templated
    assert "`/api/dashboard/goals/${encodeURIComponent(goalId)}`" in lib
    assert "`/api/dashboard/tasks/${encodeURIComponent(taskId)}`" in lib
    assert "`/api/dashboard/milestones/${encodeURIComponent(milestoneId)}`" in lib
    assert 'method: "PATCH"' in lib and 'method: "DELETE"' in lib


# =========================================================================== #
# 5. Progress renders (POST feeds GET summary; multi-day streak arithmetic).   #
# =========================================================================== #
async def test_progress_entries_feed_the_summary_over_the_api(
    client: httpx.AsyncClient, wire: Callable[[DashboardService, CurrentUser], None]
) -> None:
    """POSTed progress entries feed ``GET /api/dashboard``'s progress rollup: today's two entries
    yield ``total_entries=2``, ``entries_last_7_days=2``, a live ``current_streak_days`` and a
    ``last_entry_date`` of today — the wiring the P8-05 ``ProgressPanel`` renders."""
    service = _service()
    wire(service, _user())
    await client.post("/api/dashboard/progress", json={"note": "did the SQL course"})
    await client.post("/api/dashboard/progress", json={"note": "shipped a project"})

    progress = (await client.get("/api/dashboard")).json()["progress"]
    assert progress["total_entries"] == 2
    assert progress["entries_last_7_days"] == 2
    assert progress["current_streak_days"] == 1  # both entries are today
    assert progress["last_entry_date"] == datetime.now(UTC).date().isoformat()


async def test_progress_summary_multi_day_streak_arithmetic() -> None:
    """A multi-day fixture (entries can only be *back*-dated at the store edge, since a live POST
    always stamps ``now``): three consecutive days ending today → a 3-day streak; the real
    :meth:`DashboardService.get_summary` aggregation computes it (not a hand-rolled copy)."""
    store = InMemoryDashboardStore()
    today = datetime.now(UTC)
    for offset in (0, 1, 2, 4):  # today, -1, -2 (streak of 3), then a gap at -3, an entry at -4
        created = today - timedelta(days=offset)
        entry = ProgressEntryResponse(
            id=f"p{offset}",
            goal_id=None,
            task_id=None,
            note=f"day-{offset}",
            source="user",
            created_at=created,
        )
        store._progress[entry.id] = entry  # noqa: SLF001 - back-date at the store edge
        store._progress_owner[entry.id] = _USER  # noqa: SLF001

    summary = await DashboardService(store).get_summary(_USER)
    assert summary.progress.total_entries == 4
    assert summary.progress.entries_last_7_days == 4
    assert summary.progress.current_streak_days == 3  # today, -1, -2; broken by the gap at -3
    assert summary.progress.last_entry_date == today.date()


# =========================================================================== #
# 6. Guests correctly excluded (API 403, chat fail-soft, frontend gate).       #
# =========================================================================== #
async def test_guest_is_rejected_across_the_api_surface(
    client: httpx.AsyncClient, wire: Callable[[DashboardService, CurrentUser], None]
) -> None:
    """Every dashboard API surface rejects a guest with 403 (§5.2 — needs an account), no crash."""
    wire(_service(), fake_current_user("guest-s", role="guest"))
    assert (await client.get("/api/dashboard")).status_code == 403
    assert (await client.get("/api/dashboard/goals")).status_code == 403
    assert (await client.post("/api/dashboard/goals", json={"title": "G"})).status_code == 403
    assert (await client.post("/api/dashboard/progress", json={"note": "x"})).status_code == 403


async def test_guest_chat_turn_fails_soft_without_calling_the_model() -> None:
    """A guest chat turn routed to the dashboard worker fails soft: no model call, no write, no
    crash — the answer invites the user to sign in (§5.2)."""
    service = _service()
    router = _ScriptedCompleter([_final()])
    compiled = build_graph(
        planner=_planner_selecting_dashboard(), dashboard_service=service, router=router
    )
    final = await compiled.ainvoke(_state(user_id=None))
    state = AgentState.model_validate(final)

    worker = state.worker_results[WorkerName.DASHBOARD.value]
    assert worker.error is not None and "account" in worker.error.lower()
    assert router.calls == 0  # the model was never called for a guest
    assert state.response is not None and "sign in" in state.response.lower()


def test_frontend_gates_guests_with_a_sign_in_prompt() -> None:
    """Point 6 (frontend): the P8-05 ``Dashboard`` renders a sign-in gate for a guest instead of
    hitting the 403-gated API (source scan — mirrors the P7-05 contract scans)."""
    dashboard = (_FRONTEND / "components" / "Dashboard.tsx").read_text(encoding="utf-8")
    assert 'session.role === "guest"' in dashboard and "GuestGate" in dashboard
    assert "dashboard-guest-gate" in dashboard


# =========================================================================== #
# 7. Cross-task consistency: one source→status resolver, no re-implementation. #
# =========================================================================== #
_APP_ROOT = Path(__file__).resolve().parents[1] / "app"


def test_only_dashboard_service_resolves_source_to_status() -> None:
    """The ``source="ai" → status="proposed"`` attribution lives in exactly one place
    (:meth:`DashboardService._resolve_status`); no AI-write caller re-implements it.

    Guards against the drift point 7 calls out: the propose tools (P8-03) and the PDP seed (P8-04)
    must pass only ``source="ai"`` and let the service resolve the status — they must never pass a
    ``status=`` (least of all a hardcoded ``"proposed"``) into a create call. We assert the
    resolver constant is defined only in the service, and that the two AI-write modules issue their
    ``create_*`` calls without a ``status=`` argument.
    """
    # The proposed-status constant is defined only in the service (its single home).
    definitions = [
        path
        for path in _APP_ROOT.rglob("*.py")
        if '_AI_PROPOSED_STATUS = "proposed"' in path.read_text(encoding="utf-8")
    ]
    assert definitions == [_APP_ROOT / "services" / "dashboard.py"]

    # The AI-write callers route through the service by source only — never set status themselves.
    for rel in ("tools/dashboard.py", "services/pdp_seed.py"):
        src = (_APP_ROOT / rel).read_text(encoding="utf-8")
        assert "source=_AI_SOURCE" in src, f"{rel} should attribute AI writes via source=_AI_SOURCE"
        # No create_* call passes a status= (that is the service's job).
        for kind in ("create_goal", "create_milestone", "create_task"):
            for chunk in src.split(f".{kind}(")[1:]:
                call = chunk.split(")")[0]
                assert "status=" not in call, (
                    f"{rel}: {kind} must not pass status= (service resolves it)"
                )
