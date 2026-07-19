"use client";

import { useCallback, useEffect, useState } from "react";

import { type Session } from "@/lib/auth";
import {
  deleteMemory,
  getMemory,
  MemoryApiError,
  updatePreferences,
  type LearnedMemory,
  type Preferences,
} from "@/lib/memory";

/**
 * "What the coach knows about you" panel (design §5.4 point 4 / §6.10; backend `GET/PUT/DELETE
 * /api/memory`).
 *
 * Reads the caller's explicit {@link Preferences} (editable) + inferred {@link LearnedMemory} list
 * with {@link getMemory} and lets them edit/save preferences ({@link updatePreferences}) and delete
 * individual learned memories ({@link deleteMemory}) — immediately, with **no per-fact confirmation
 * or approve/reject workflow** (§6.10, contrast the dashboard's propose/approve UI).
 *
 * Guest vs. user (§5.4 / P9-07): memory is durable-only, so the backend rejects a guest with 403.
 * Rather than surface a raw error, we render a clear "sign in to see what the coach has learned"
 * state — a guest is detected up front (session role) so we never even issue the 403 call.
 */
export interface MemoryPanelProps {
  session: Session;
}

/** Split a one-item-per-line textarea into a trimmed, non-empty string list (mirrors ProfileView). */
function linesToArray(text: string): string[] {
  return text
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line.length > 0);
}

/** Empty string ⇄ null, so a cleared input is stored as null (matching the backend shape). */
function orNull(value: string): string | null {
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : null;
}

export default function MemoryPanel({ session }: MemoryPanelProps) {
  const isGuest = session.role === "guest";

  const [loading, setLoading] = useState(!isGuest);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [memories, setMemories] = useState<LearnedMemory[]>([]);

  // Editable preference fields.
  const [tone, setTone] = useState("");
  const [formality, setFormality] = useState("");
  const [language, setLanguage] = useState("");
  const [focusText, setFocusText] = useState("");
  const [avoidText, setAvoidText] = useState("");

  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  const hydrate = useCallback((prefs: Preferences) => {
    setTone(prefs.tone ?? "");
    setFormality(prefs.formality ?? "");
    setLanguage(prefs.language ?? "");
    setFocusText(prefs.focus_areas.join("\n"));
    setAvoidText(prefs.avoid.join("\n"));
  }, []);

  useEffect(() => {
    // Guests have no durable memory (P9-07) — skip the call and show the sign-in state.
    if (isGuest) {
      return;
    }
    let cancelled = false;
    setLoading(true);
    setLoadError(null);
    setSaved(false);
    setSaveError(null);
    setDeleteError(null);
    getMemory()
      .then((view) => {
        if (!cancelled) {
          hydrate(view.preferences);
          setMemories(view.memories);
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setLoadError(
            err instanceof MemoryApiError
              ? err.message
              : "Couldn't load what the coach knows. Please try again.",
          );
        }
      })
      .finally(() => {
        if (!cancelled) {
          setLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [hydrate, isGuest, session]);

  const handleSave = useCallback(async () => {
    if (saving) {
      return;
    }
    setSaving(true);
    setSaveError(null);
    setSaved(false);
    const next: Preferences = {
      tone: orNull(tone),
      formality: orNull(formality),
      language: orNull(language),
      focus_areas: linesToArray(focusText),
      avoid: linesToArray(avoidText),
    };
    try {
      const stored = await updatePreferences(next);
      hydrate(stored);
      setSaved(true);
    } catch (err) {
      setSaveError(
        err instanceof MemoryApiError
          ? err.message
          : "Couldn't save your preferences. Please try again.",
      );
    } finally {
      setSaving(false);
    }
  }, [avoidText, focusText, formality, hydrate, language, saving, tone]);

  const handleDelete = useCallback(async (id: string) => {
    setDeleteError(null);
    // Optimistic removal — immediate, per §6.10 (no confirmation). Restore on failure.
    let removed: LearnedMemory | undefined;
    setMemories((prev) => {
      removed = prev.find((m) => m.id === id);
      return prev.filter((m) => m.id !== id);
    });
    try {
      await deleteMemory(id);
    } catch (err) {
      if (removed) {
        setMemories((prev) => [removed as LearnedMemory, ...prev]);
      }
      setDeleteError(
        err instanceof MemoryApiError
          ? err.message
          : "Couldn't delete that memory. Please try again.",
      );
    }
  }, []);

  // Guest: durable memory is account-only (§5.4 / P9-07) — a clear informative state, not an error.
  if (isGuest) {
    return (
      <section
        className="space-y-3 rounded-xl border border-gray-200 p-5"
        data-testid="memory-guest"
      >
        <h2 className="text-lg font-semibold">What the coach knows about you</h2>
        <p className="rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-800">
          Sign in to see what the coach has learned. As a guest, personalization lasts only for
          this session and isn&apos;t saved.
        </p>
      </section>
    );
  }

  if (loading) {
    return (
      <section className="rounded-xl border border-gray-200 p-5" aria-busy="true">
        <p className="text-sm text-gray-500" role="status">
          Loading what the coach knows…
        </p>
      </section>
    );
  }

  if (loadError) {
    return (
      <section className="rounded-xl border border-gray-200 p-5">
        <p
          className="rounded-md border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-700"
          role="alert"
          data-testid="memory-load-error"
        >
          {loadError}
        </p>
      </section>
    );
  }

  return (
    <section
      className="space-y-6 rounded-xl border border-gray-200 p-5"
      aria-labelledby="memory-heading"
      data-testid="memory-panel"
    >
      <header className="space-y-1">
        <h2 id="memory-heading" className="text-lg font-semibold">
          What the coach knows about you
        </h2>
        <p className="text-sm text-gray-500">
          Set explicit preferences the coach should follow, and review or remove anything it has
          learned about you.
        </p>
      </header>

      {/* Explicit preferences (editable) */}
      <div className="space-y-4" data-testid="memory-preferences">
        <h3 className="text-sm font-semibold text-gray-700">Your preferences</h3>
        <div className="grid gap-3 sm:grid-cols-3">
          <div className="space-y-1">
            <label htmlFor="pref-tone" className="text-sm font-medium">
              Tone
            </label>
            <input
              id="pref-tone"
              className="w-full rounded-md border border-gray-300 p-2 text-sm"
              placeholder="e.g. encouraging"
              value={tone}
              onChange={(event) => setTone(event.target.value)}
            />
          </div>
          <div className="space-y-1">
            <label htmlFor="pref-formality" className="text-sm font-medium">
              Formality
            </label>
            <input
              id="pref-formality"
              className="w-full rounded-md border border-gray-300 p-2 text-sm"
              placeholder="e.g. casual"
              value={formality}
              onChange={(event) => setFormality(event.target.value)}
            />
          </div>
          <div className="space-y-1">
            <label htmlFor="pref-language" className="text-sm font-medium">
              Language
            </label>
            <input
              id="pref-language"
              className="w-full rounded-md border border-gray-300 p-2 text-sm"
              placeholder="e.g. en"
              value={language}
              onChange={(event) => setLanguage(event.target.value)}
            />
          </div>
        </div>
        <div className="space-y-1">
          <label htmlFor="pref-focus" className="text-sm font-medium">
            Focus areas <span className="text-gray-400">(one per line)</span>
          </label>
          <textarea
            id="pref-focus"
            className="w-full resize-y rounded-md border border-gray-300 p-2 text-sm"
            rows={3}
            value={focusText}
            onChange={(event) => setFocusText(event.target.value)}
          />
        </div>
        <div className="space-y-1">
          <label htmlFor="pref-avoid" className="text-sm font-medium">
            Don&apos;t do <span className="text-gray-400">(one per line)</span>
          </label>
          <textarea
            id="pref-avoid"
            className="w-full resize-y rounded-md border border-gray-300 p-2 text-sm"
            rows={3}
            value={avoidText}
            onChange={(event) => setAvoidText(event.target.value)}
          />
        </div>

        {saveError ? (
          <p
            className="rounded-md border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-700"
            role="alert"
            data-testid="memory-save-error"
          >
            {saveError}
          </p>
        ) : null}
        {saved ? (
          <p
            className="rounded-md border border-green-300 bg-green-50 px-3 py-2 text-sm text-green-800"
            role="status"
            data-testid="memory-saved"
          >
            Preferences saved.
          </p>
        ) : null}

        <button
          type="button"
          className="rounded-md bg-blue-600 px-4 py-2 font-medium text-white hover:bg-blue-700 disabled:opacity-50"
          disabled={saving}
          onClick={() => void handleSave()}
        >
          {saving ? "Saving…" : "Save preferences"}
        </button>
      </div>

      {/* Learned memories (view + delete) */}
      <div className="space-y-3" data-testid="memory-learned">
        <h3 className="text-sm font-semibold text-gray-700">Learned about you</h3>
        {deleteError ? (
          <p
            className="rounded-md border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-700"
            role="alert"
            data-testid="memory-delete-error"
          >
            {deleteError}
          </p>
        ) : null}
        {memories.length === 0 ? (
          <p className="text-sm text-gray-400" data-testid="memory-empty">
            The coach hasn&apos;t learned anything about you yet. As you chat, useful facts will
            appear here — you can remove any of them.
          </p>
        ) : (
          <ul className="space-y-2">
            {memories.map((memory) => (
              <li
                key={memory.id}
                className="flex items-start justify-between gap-3 rounded-md border border-gray-200 p-3"
                data-testid="memory-item"
              >
                <div className="space-y-1">
                  <p className="text-sm text-gray-900">{memory.text}</p>
                  <p className="text-xs text-gray-500">
                    <span className="font-medium">{memory.memory_type}</span>
                    {" · "}
                    confidence {Math.round(memory.confidence * 100)}%
                    {memory.created_at ? ` · ${memory.created_at}` : ""}
                  </p>
                </div>
                <button
                  type="button"
                  className="shrink-0 text-sm text-red-600 hover:text-red-800"
                  aria-label={`Delete memory: ${memory.text}`}
                  onClick={() => void handleDelete(memory.id)}
                >
                  Delete
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}
