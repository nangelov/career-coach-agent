"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { type Session } from "@/lib/auth";
import { safeHttpUrl } from "@/lib/url";
import {
  getRoleGap,
  getRoleRequirements,
  isAbortError,
  pollJobUntilTerminal,
  RolesApiError,
  type JobStatus,
  type RoleRequirement,
  type RoleRequirements as RoleRequirementsData,
  type SkillGap,
  type SkillsGap,
} from "@/lib/roles";

/**
 * Role-requirements surface (design §5.6 / §9; backend P6-07). A target-role search that renders
 * the role's **frequency-ranked, cited** market requirements and — for a logged-in user — the
 * read-only **skills gap** between those requirements and their profile.
 *
 * This is deliberately **not** a job board (§1.1): no listings, no apply, no save/track — only the
 * ranked requirement list with citations and the gap. The cold-role case (`202`, never mined) shows
 * a "gathering market data…" state and polls the generic job endpoint via {@link pollJobUntilTerminal}
 * (reused from the profile/CV flow), then re-fetches — no page reload.
 *
 * Guest vs. user (§5.6): `/requirements` needs no account, so a guest sees the ranked list; the
 * personal gap needs a persisted profile, so a guest gets a plain "log in" prompt instead of a
 * silent 403 (we never call `/gap` for a guest).
 */
export interface RoleRequirementsProps {
  /** The current session (guest or user); gates whether the personal gap is fetched/shown. */
  session: Session;
}

type Phase = "idle" | "loading" | "mining" | "ready" | "error";

const GENERIC_ERROR = "Something went wrong loading market data. Please try again.";

function errorMessage(err: unknown, fallback: string): string {
  if (err instanceof RolesApiError) {
    return err.message;
  }
  if (err instanceof Error && err.message) {
    return err.message;
  }
  return fallback;
}

/** Render a requirement's frequency (0-1) as a whole-percent share of the role's evidence. */
function frequencyPct(frequency: number): number {
  return Math.round(Math.max(0, Math.min(1, frequency)) * 100);
}

export default function RoleRequirements({ session }: RoleRequirementsProps) {
  const isGuest = session.role === "guest";

  const [roleInput, setRoleInput] = useState("");

  const [reqPhase, setReqPhase] = useState<Phase>("idle");
  const [requirements, setRequirements] = useState<RoleRequirementsData | null>(null);
  const [reqError, setReqError] = useState<string | null>(null);
  const [reqProgress, setReqProgress] = useState<JobStatus | null>(null);

  const [gapPhase, setGapPhase] = useState<Phase>("idle");
  const [gap, setGap] = useState<SkillsGap | null>(null);
  const [gapError, setGapError] = useState<string | null>(null);

  const abortRef = useRef<AbortController | null>(null);

  // Stop any in-flight polling loop if the component unmounts mid-search.
  useEffect(() => () => abortRef.current?.abort(), []);

  // Resolve requirements, transparently polling the cold-role mine job to completion and
  // re-fetching until the profile is available (a 202 carries no requirements to render).
  const resolveRequirements = useCallback(
    async (role: string, signal: AbortSignal): Promise<RoleRequirementsData> => {
      let outcome = await getRoleRequirements(role);
      while (outcome.kind === "mining") {
        setReqPhase("mining");
        const terminal = await pollJobUntilTerminal(outcome.taskId, {
          onUpdate: setReqProgress,
          signal,
        });
        if (terminal.status === "failure") {
          throw new Error(
            terminal.error ?? "We couldn't gather market data for that role.",
          );
        }
        outcome = await getRoleRequirements(role);
      }
      return outcome.requirements;
    },
    [],
  );

  // Resolve the logged-in user's gap, polling the cold-role mine job the same way.
  const resolveGap = useCallback(
    async (role: string, signal: AbortSignal): Promise<SkillsGap> => {
      let outcome = await getRoleGap(role);
      while (outcome.kind === "mining") {
        setGapPhase("mining");
        const terminal = await pollJobUntilTerminal(outcome.taskId, { signal });
        if (terminal.status === "failure") {
          throw new Error(
            terminal.error ?? "We couldn't gather market data for that role.",
          );
        }
        outcome = await getRoleGap(role);
      }
      return outcome.gap;
    },
    [],
  );

  const handleSubmit = useCallback(async () => {
    const role = roleInput.trim();
    if (!role || reqPhase === "loading" || reqPhase === "mining") {
      return;
    }

    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    // Reset both panels for the new search.
    setRequirements(null);
    setReqError(null);
    setReqProgress(null);
    setGap(null);
    setGapError(null);
    setGapPhase("idle");
    setReqPhase("loading");

    try {
      const resolved = await resolveRequirements(role, controller.signal);
      setRequirements(resolved);
      setReqPhase("ready");
    } catch (err) {
      if (isAbortError(err)) {
        return; // superseded / unmounted — drop silently
      }
      setReqError(errorMessage(err, GENERIC_ERROR));
      setReqPhase("error");
      return;
    }

    // The personal gap needs a persisted profile — only logged-in users have one, so we never
    // call /gap for a guest (it would 403); the guest sees a "log in" prompt instead.
    if (isGuest) {
      return;
    }
    setGapPhase("loading");
    try {
      const resolvedGap = await resolveGap(role, controller.signal);
      setGap(resolvedGap);
      setGapPhase("ready");
    } catch (err) {
      if (isAbortError(err)) {
        return;
      }
      setGapError(errorMessage(err, GENERIC_ERROR));
      setGapPhase("error");
    }
  }, [isGuest, reqPhase, resolveGap, resolveRequirements, roleInput]);

  const reqBusy = reqPhase === "loading" || reqPhase === "mining";

  return (
    <section
      className="space-y-5 rounded-xl border border-gray-200 p-5"
      aria-labelledby="roles-heading"
      data-testid="role-requirements"
    >
      <header className="space-y-1">
        <h2 id="roles-heading" className="text-lg font-semibold">
          Explore a role
        </h2>
        <p className="text-sm text-gray-500">
          See the most in-demand skills for a target role — frequency-ranked and cited from
          real market data.
        </p>
      </header>

      <form
        className="flex flex-wrap items-center gap-3"
        onSubmit={(event) => {
          event.preventDefault();
          void handleSubmit();
        }}
      >
        <input
          type="text"
          className="min-w-0 flex-1 rounded-md border border-gray-300 p-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          placeholder="e.g. AI Solution Architect"
          aria-label="Target role"
          value={roleInput}
          disabled={reqBusy}
          onChange={(event) => setRoleInput(event.target.value)}
        />
        <button
          type="submit"
          className="rounded-md bg-blue-600 px-4 py-2 font-medium text-white hover:bg-blue-700 disabled:opacity-50"
          disabled={!roleInput.trim() || reqBusy}
        >
          {reqBusy ? "Searching…" : "Find requirements"}
        </button>
      </form>

      {reqBusy ? (
        <div
          className="flex items-center gap-2 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800"
          role="status"
          aria-live="polite"
          data-testid="requirements-progress"
        >
          <span
            className="h-3 w-3 animate-spin rounded-full border-2 border-amber-400 border-t-transparent"
            aria-hidden="true"
          />
          <span>
            {reqPhase === "mining"
              ? reqProgress?.message ??
                "We're gathering market data for this role for the first time — this can take a moment…"
              : "Loading market requirements…"}
          </span>
        </div>
      ) : null}

      {reqPhase === "error" && reqError ? (
        <div
          className="rounded-md border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-700"
          role="alert"
          data-testid="requirements-error"
        >
          {reqError}
        </div>
      ) : null}

      {reqPhase === "ready" && requirements ? (
        <RequirementsPanel data={requirements} />
      ) : null}

      {reqPhase === "ready" && requirements ? (
        <GapSection
          isGuest={isGuest}
          gapPhase={gapPhase}
          gap={gap}
          gapError={gapError}
        />
      ) : null}
    </section>
  );
}

/** The frequency-ranked, cited requirement list (§5.6 — never a bare skill list). */
function RequirementsPanel({ data }: { data: RoleRequirementsData }) {
  return (
    <div className="space-y-3" data-testid="requirements-panel">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-base font-semibold">
          In-demand skills for {data.role}
        </h3>
        <span className="text-xs text-gray-500" data-testid="evidence-count">
          Based on {data.evidence_count} evidence source
          {data.evidence_count === 1 ? "" : "s"}
          {data.refreshed_at
            ? ` · updated ${formatRefreshed(data.refreshed_at)}`
            : ""}
        </span>
      </div>

      {data.requirements.length === 0 ? (
        <p className="text-sm text-gray-500" data-testid="requirements-empty">
          No specific requirements were found for this role yet.
        </p>
      ) : (
        <ol className="space-y-2" data-testid="requirements-list">
          {data.requirements.map((req, index) => (
            <RequirementRow key={`${req.skill}-${index}`} req={req} rank={index + 1} />
          ))}
        </ol>
      )}
    </div>
  );
}

function RequirementRow({ req, rank }: { req: RoleRequirement; rank: number }) {
  return (
    <li
      className="rounded-md border border-gray-200 p-3"
      data-testid="requirement"
    >
      <div className="flex items-center justify-between gap-2">
        <span className="font-medium">
          {rank}. {req.skill}
        </span>
        <span
          className="shrink-0 rounded-full bg-blue-50 px-2 py-0.5 text-xs font-medium text-blue-700"
          data-testid="requirement-frequency"
        >
          {frequencyPct(req.frequency)}% of postings
        </span>
      </div>
      <Citations evidence={req.evidence} />
    </li>
  );
}

/** Render a requirement's citations — the "every requirement is cited" contract (§5.6). */
function Citations({ evidence }: { evidence: string[] }) {
  if (evidence.length === 0) {
    return (
      <p className="mt-1 text-xs italic text-gray-400" data-testid="citations-empty">
        No sources cited.
      </p>
    );
  }
  return (
    <div className="mt-2 text-xs text-gray-600" data-testid="citations">
      <span className="font-medium text-gray-500">
        {evidence.length} source{evidence.length === 1 ? "" : "s"}:{" "}
      </span>
      <ul className="mt-1 flex flex-wrap gap-x-3 gap-y-1">
        {evidence.map((item, index) => (
          <li key={`${item}-${index}`} data-testid="evidence">
            <EvidenceLink evidence={item} index={index} />
          </li>
        ))}
      </ul>
    </div>
  );
}

// Evidence urls come from untrusted crawled content, so safeHttpUrl (lib/url) gates them: only
// parseable http(s) links become clickable anchors — anything else renders as plain text.
function EvidenceLink({ evidence, index }: { evidence: string; index: number }) {
  const href = safeHttpUrl(evidence);
  if (href) {
    return (
      <a
        href={href}
        target="_blank"
        rel="noopener noreferrer"
        className="text-blue-600 underline hover:text-blue-800"
      >
        Source {index + 1}
      </a>
    );
  }
  return <span>{evidence}</span>;
}

/** The read-only skills-gap panel: guest → log-in prompt, user → matched/missing (§5.6). */
function GapSection({
  isGuest,
  gapPhase,
  gap,
  gapError,
}: {
  isGuest: boolean;
  gapPhase: Phase;
  gap: SkillsGap | null;
  gapError: string | null;
}) {
  if (isGuest) {
    return (
      <div
        className="rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-800"
        data-testid="gap-login-prompt"
      >
        Log in to see your personal skills gap for this role.
      </div>
    );
  }

  if (gapPhase === "loading" || gapPhase === "mining") {
    return (
      <div
        className="flex items-center gap-2 rounded-md border border-gray-200 bg-gray-50 px-3 py-2 text-sm text-gray-600"
        role="status"
        aria-live="polite"
        data-testid="gap-progress"
      >
        <span
          className="h-3 w-3 animate-spin rounded-full border-2 border-gray-400 border-t-transparent"
          aria-hidden="true"
        />
        <span>Comparing the role against your profile…</span>
      </div>
    );
  }

  if (gapPhase === "error" && gapError) {
    return (
      <div
        className="rounded-md border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-700"
        role="alert"
        data-testid="gap-error"
      >
        {gapError}
      </div>
    );
  }

  if (gapPhase === "ready" && gap) {
    if (gap.status === "profile_missing") {
      return (
        <div
          className="rounded-md border border-blue-200 bg-blue-50 px-3 py-2 text-sm text-blue-800"
          data-testid="gap-profile-missing"
        >
          Upload a CV on your profile to see which of these skills you&apos;re missing.
        </div>
      );
    }
    return <GapPanel gap={gap} />;
  }

  return null;
}

function GapPanel({ gap }: { gap: SkillsGap }) {
  const missing: SkillGap[] = gap.gap ?? [];
  return (
    <div className="space-y-3 rounded-md border border-gray-200 p-3" data-testid="gap-panel">
      <h3 className="text-base font-semibold">Your skills gap</h3>

      {missing.length === 0 ? (
        <p className="text-sm text-green-700" data-testid="gap-none">
          You already have every ranked requirement for this role. 🎉
        </p>
      ) : (
        <div className="space-y-1">
          <p className="text-sm font-medium text-gray-700">
            Skills to develop ({missing.length}):
          </p>
          <ol className="space-y-2" data-testid="gap-list">
            {missing.map((item, index) => (
              <li
                key={`${item.skill}-${index}`}
                className="rounded-md border border-amber-200 bg-amber-50 p-2"
                data-testid="gap-item"
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="text-sm font-medium text-amber-900">
                    {item.skill}
                  </span>
                  <span className="shrink-0 text-xs text-amber-700">
                    {frequencyPct(item.frequency)}% of postings
                  </span>
                </div>
                <Citations evidence={item.evidence} />
              </li>
            ))}
          </ol>
        </div>
      )}

      {gap.matched.length > 0 ? (
        <p className="text-xs text-gray-500" data-testid="gap-matched">
          Already covered: {gap.matched.join(", ")}
        </p>
      ) : null}
    </div>
  );
}

/** Best-effort human date for the `refreshed_at` ISO marker; falls back to the raw string. */
function formatRefreshed(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) {
    return iso;
  }
  return date.toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}
