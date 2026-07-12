"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { type Session } from "@/lib/auth";
import {
  isAbortError,
  pollJobUntilTerminal,
  ProfileApiError,
  uploadCv,
  type JobStatus,
} from "@/lib/profile";

/**
 * CV upload + async-parse progress (design §5.1 / §5.3; backend P5-04/06).
 *
 * The parse runs off the request path: {@link uploadCv} returns a Celery `task_id`, then this
 * polls {@link pollJobUntilTerminal} and renders the live stage/message until the job succeeds or
 * fails — no page reload. On success it calls `onParsed` so the parent can refresh the profile
 * view. Errors (413 too-large, 415 unsupported, 429 over-limit, …) are surfaced from the typed
 * {@link ProfileApiError}, preferring the backend's message rather than a raw HTTP error.
 *
 * Guests may upload once per session (P3-04 rate limit); the 429 message makes that explicit.
 */
export interface CvUploadProps {
  /** The current session (guest or user); the bearer token authenticates the upload/poll. */
  session: Session;
  /** Called once the parse job succeeds, so the parent can reload the parsed profile. */
  onParsed?: () => void;
}

type UploadPhase = "idle" | "uploading" | "processing" | "success" | "error";

/** File types the backend document parser accepts (§5.1). */
const ACCEPT = ".pdf,.docx,.pptx,image/*";

function progressLabel(phase: UploadPhase, status: JobStatus | null): string {
  if (phase === "uploading") {
    return "Uploading your CV…";
  }
  if (status?.message) {
    return status.message;
  }
  if (status?.stage) {
    return `Working: ${status.stage}…`;
  }
  return status?.status === "pending" ? "Waiting to start…" : "Parsing your CV…";
}

export default function CvUpload({ session, onParsed }: CvUploadProps) {
  const [file, setFile] = useState<File | null>(null);
  const [phase, setPhase] = useState<UploadPhase>("idle");
  const [progress, setProgress] = useState<JobStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const busy = phase === "uploading" || phase === "processing";

  // Stop any in-flight polling loop if the component unmounts mid-parse.
  useEffect(() => () => abortRef.current?.abort(), []);

  const handleFileChange = useCallback(
    (event: React.ChangeEvent<HTMLInputElement>) => {
      setFile(event.target.files?.[0] ?? null);
      setError(null);
      setPhase("idle");
      setProgress(null);
    },
    [],
  );

  const handleUpload = useCallback(async () => {
    if (!file || busy) {
      return;
    }
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    setError(null);
    setProgress(null);
    setPhase("uploading");
    try {
      const { taskId } = await uploadCv(file, session);
      setPhase("processing");
      const status = await pollJobUntilTerminal(taskId, session, {
        onUpdate: setProgress,
        signal: controller.signal,
      });
      if (status.status === "success") {
        setPhase("success");
        onParsed?.();
      } else {
        setPhase("error");
        setError(
          status.error ?? "We couldn't parse that CV. Please try a different file.",
        );
      }
    } catch (err) {
      if (isAbortError(err)) {
        return; // component unmounted / superseded — drop silently
      }
      setPhase("error");
      setError(
        err instanceof ProfileApiError
          ? err.message
          : "Something went wrong uploading your CV. Please try again.",
      );
    }
  }, [busy, file, onParsed, session]);

  return (
    <section
      className="space-y-3 rounded-xl border border-gray-200 p-5"
      aria-labelledby="cv-upload-heading"
    >
      <header className="space-y-1">
        <h2 id="cv-upload-heading" className="text-lg font-semibold">
          Upload your CV
        </h2>
        <p className="text-sm text-gray-500">
          We&apos;ll parse it into a structured profile (skills, experience, education,
          goals) you can review and edit.
          {session.role === "guest"
            ? " Guests can upload one CV per session — sign in to upload more."
            : ""}
        </p>
      </header>

      <div className="flex flex-wrap items-center gap-3">
        <input
          type="file"
          accept={ACCEPT}
          aria-label="CV file"
          disabled={busy}
          onChange={handleFileChange}
          className="text-sm"
        />
        <button
          type="button"
          className="rounded-md bg-blue-600 px-4 py-2 font-medium text-white hover:bg-blue-700 disabled:opacity-50"
          disabled={!file || busy}
          onClick={() => void handleUpload()}
        >
          {busy ? "Uploading…" : "Upload"}
        </button>
      </div>

      {busy ? (
        <div
          className="flex items-center gap-2 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800"
          role="status"
          aria-live="polite"
          data-testid="cv-progress"
        >
          <span
            className="h-3 w-3 animate-spin rounded-full border-2 border-amber-400 border-t-transparent"
            aria-hidden="true"
          />
          <span>{progressLabel(phase, progress)}</span>
        </div>
      ) : null}

      {phase === "success" ? (
        <div
          className="rounded-md border border-green-300 bg-green-50 px-3 py-2 text-sm text-green-800"
          role="status"
          data-testid="cv-success"
        >
          Your CV was parsed. Review and edit your profile below.
        </div>
      ) : null}

      {phase === "error" && error ? (
        <div
          className="rounded-md border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-700"
          role="alert"
          data-testid="cv-error"
        >
          {error}
        </div>
      ) : null}
    </section>
  );
}
