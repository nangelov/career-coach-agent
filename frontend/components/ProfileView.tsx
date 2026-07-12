"use client";

import { useCallback, useEffect, useState } from "react";

import { type Session } from "@/lib/auth";
import {
  getProfile,
  isProfileEmpty,
  ProfileApiError,
  updateProfile,
  type EducationItem,
  type ExperienceItem,
  type Profile,
} from "@/lib/profile";

/**
 * Structured-profile view/edit (design §4 / §5.1; backend `GET/PUT /api/profile`).
 *
 * Reads the caller's profile with {@link getProfile} (an empty profile when none exists yet — the
 * backend returns 200-empty, not 404 — so we prompt the user to upload a CV) and lets them edit
 * skills/experience/education/goals and save with {@link updateProfile}. Skills and goals are
 * edited as one-item-per-line text areas; experience/education are add/remove entry rows.
 *
 * Guest vs. user (§7): the backend rejects a guest `PUT` with 403. We show a clear inline note for
 * guests up front and, if a save is attempted, surface the backend's sign-in message via the typed
 * {@link ProfileApiError} rather than a generic error.
 */
export interface ProfileViewProps {
  session: Session;
  /** Bump to force a re-fetch (e.g. after a CV upload parses). */
  reloadKey?: number;
}

const EMPTY_EXPERIENCE: ExperienceItem = {
  title: null,
  company: null,
  start_date: null,
  end_date: null,
  description: null,
};

const EMPTY_EDUCATION: EducationItem = {
  institution: null,
  degree: null,
  field: null,
  start_date: null,
  end_date: null,
};

/** Split a one-item-per-line textarea into a trimmed, non-empty string list. */
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

export default function ProfileView({ session, reloadKey = 0 }: ProfileViewProps) {
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [profile, setProfile] = useState<Profile | null>(null);
  const [skillsText, setSkillsText] = useState("");
  const [goalsText, setGoalsText] = useState("");
  const [experience, setExperience] = useState<ExperienceItem[]>([]);
  const [education, setEducation] = useState<EducationItem[]>([]);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  const hydrate = useCallback((next: Profile) => {
    setProfile(next);
    setSkillsText(next.skills.join("\n"));
    setGoalsText(next.goals.join("\n"));
    setExperience(next.experience);
    setEducation(next.education);
  }, []);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setLoadError(null);
    setSaveError(null);
    setSaved(false);
    getProfile(session)
      .then((next) => {
        if (!cancelled) {
          hydrate(next);
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setLoadError(
            err instanceof ProfileApiError
              ? err.message
              : "Couldn't load your profile. Please try again.",
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
  }, [hydrate, session, reloadKey]);

  const updateExperience = useCallback(
    (index: number, patch: Partial<ExperienceItem>) => {
      setExperience((prev) =>
        prev.map((item, i) => (i === index ? { ...item, ...patch } : item)),
      );
    },
    [],
  );

  const updateEducation = useCallback(
    (index: number, patch: Partial<EducationItem>) => {
      setEducation((prev) =>
        prev.map((item, i) => (i === index ? { ...item, ...patch } : item)),
      );
    },
    [],
  );

  const handleSave = useCallback(async () => {
    if (saving) {
      return;
    }
    setSaving(true);
    setSaveError(null);
    setSaved(false);
    const next: Profile = {
      skills: linesToArray(skillsText),
      goals: linesToArray(goalsText),
      experience,
      education,
    };
    try {
      const stored = await updateProfile(next, session);
      hydrate(stored);
      setSaved(true);
    } catch (err) {
      setSaveError(
        err instanceof ProfileApiError
          ? err.message
          : "Couldn't save your profile. Please try again.",
      );
    } finally {
      setSaving(false);
    }
  }, [education, experience, goalsText, hydrate, saving, session, skillsText]);

  if (loading) {
    return (
      <section className="rounded-xl border border-gray-200 p-5" aria-busy="true">
        <p className="text-sm text-gray-500" role="status">
          Loading your profile…
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
          data-testid="profile-load-error"
        >
          {loadError}
        </p>
      </section>
    );
  }

  const isGuest = session.role === "guest";
  const showEmptyPrompt = profile != null && isProfileEmpty(profile);

  return (
    <section
      className="space-y-5 rounded-xl border border-gray-200 p-5"
      aria-labelledby="profile-heading"
      data-testid="profile-view"
    >
      <header className="space-y-1">
        <h2 id="profile-heading" className="text-lg font-semibold">
          Your profile
        </h2>
        {showEmptyPrompt ? (
          <p
            className="rounded-md border border-blue-200 bg-blue-50 px-3 py-2 text-sm text-blue-800"
            data-testid="profile-empty"
          >
            You don&apos;t have a profile yet. Upload a CV above to get started, or add
            details manually below.
          </p>
        ) : null}
      </header>

      {/* Skills */}
      <div className="space-y-1">
        <label htmlFor="profile-skills" className="text-sm font-medium">
          Skills <span className="text-gray-400">(one per line)</span>
        </label>
        <textarea
          id="profile-skills"
          className="w-full resize-y rounded-md border border-gray-300 p-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          rows={4}
          value={skillsText}
          onChange={(event) => setSkillsText(event.target.value)}
        />
      </div>

      {/* Experience */}
      <fieldset className="space-y-3">
        <legend className="text-sm font-medium">Experience</legend>
        {experience.length === 0 ? (
          <p className="text-sm text-gray-400">No experience entries yet.</p>
        ) : null}
        {experience.map((item, index) => (
          <div
            key={index}
            className="space-y-2 rounded-md border border-gray-200 p-3"
            data-testid="experience-entry"
          >
            <div className="grid gap-2 sm:grid-cols-2">
              <input
                className="rounded-md border border-gray-300 p-2 text-sm"
                placeholder="Title"
                aria-label={`Experience ${index + 1} title`}
                value={item.title ?? ""}
                onChange={(event) =>
                  updateExperience(index, { title: orNull(event.target.value) })
                }
              />
              <input
                className="rounded-md border border-gray-300 p-2 text-sm"
                placeholder="Company"
                aria-label={`Experience ${index + 1} company`}
                value={item.company ?? ""}
                onChange={(event) =>
                  updateExperience(index, { company: orNull(event.target.value) })
                }
              />
              <input
                className="rounded-md border border-gray-300 p-2 text-sm"
                placeholder="Start (e.g. Jan 2020)"
                aria-label={`Experience ${index + 1} start date`}
                value={item.start_date ?? ""}
                onChange={(event) =>
                  updateExperience(index, { start_date: orNull(event.target.value) })
                }
              />
              <input
                className="rounded-md border border-gray-300 p-2 text-sm"
                placeholder="End (e.g. Present)"
                aria-label={`Experience ${index + 1} end date`}
                value={item.end_date ?? ""}
                onChange={(event) =>
                  updateExperience(index, { end_date: orNull(event.target.value) })
                }
              />
            </div>
            <textarea
              className="w-full resize-y rounded-md border border-gray-300 p-2 text-sm"
              rows={2}
              placeholder="Description"
              aria-label={`Experience ${index + 1} description`}
              value={item.description ?? ""}
              onChange={(event) =>
                updateExperience(index, { description: orNull(event.target.value) })
              }
            />
            <button
              type="button"
              className="text-sm text-red-600 hover:text-red-800"
              onClick={() =>
                setExperience((prev) => prev.filter((_, i) => i !== index))
              }
            >
              Remove
            </button>
          </div>
        ))}
        <button
          type="button"
          className="rounded-md border border-gray-300 px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50"
          onClick={() => setExperience((prev) => [...prev, { ...EMPTY_EXPERIENCE }])}
        >
          Add experience
        </button>
      </fieldset>

      {/* Education */}
      <fieldset className="space-y-3">
        <legend className="text-sm font-medium">Education</legend>
        {education.length === 0 ? (
          <p className="text-sm text-gray-400">No education entries yet.</p>
        ) : null}
        {education.map((item, index) => (
          <div
            key={index}
            className="space-y-2 rounded-md border border-gray-200 p-3"
            data-testid="education-entry"
          >
            <div className="grid gap-2 sm:grid-cols-2">
              <input
                className="rounded-md border border-gray-300 p-2 text-sm"
                placeholder="Institution"
                aria-label={`Education ${index + 1} institution`}
                value={item.institution ?? ""}
                onChange={(event) =>
                  updateEducation(index, { institution: orNull(event.target.value) })
                }
              />
              <input
                className="rounded-md border border-gray-300 p-2 text-sm"
                placeholder="Degree"
                aria-label={`Education ${index + 1} degree`}
                value={item.degree ?? ""}
                onChange={(event) =>
                  updateEducation(index, { degree: orNull(event.target.value) })
                }
              />
              <input
                className="rounded-md border border-gray-300 p-2 text-sm"
                placeholder="Field of study"
                aria-label={`Education ${index + 1} field`}
                value={item.field ?? ""}
                onChange={(event) =>
                  updateEducation(index, { field: orNull(event.target.value) })
                }
              />
              <div className="grid grid-cols-2 gap-2">
                <input
                  className="rounded-md border border-gray-300 p-2 text-sm"
                  placeholder="Start"
                  aria-label={`Education ${index + 1} start date`}
                  value={item.start_date ?? ""}
                  onChange={(event) =>
                    updateEducation(index, { start_date: orNull(event.target.value) })
                  }
                />
                <input
                  className="rounded-md border border-gray-300 p-2 text-sm"
                  placeholder="End"
                  aria-label={`Education ${index + 1} end date`}
                  value={item.end_date ?? ""}
                  onChange={(event) =>
                    updateEducation(index, { end_date: orNull(event.target.value) })
                  }
                />
              </div>
            </div>
            <button
              type="button"
              className="text-sm text-red-600 hover:text-red-800"
              onClick={() =>
                setEducation((prev) => prev.filter((_, i) => i !== index))
              }
            >
              Remove
            </button>
          </div>
        ))}
        <button
          type="button"
          className="rounded-md border border-gray-300 px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50"
          onClick={() => setEducation((prev) => [...prev, { ...EMPTY_EDUCATION }])}
        >
          Add education
        </button>
      </fieldset>

      {/* Goals */}
      <div className="space-y-1">
        <label htmlFor="profile-goals" className="text-sm font-medium">
          Career goals <span className="text-gray-400">(one per line)</span>
        </label>
        <textarea
          id="profile-goals"
          className="w-full resize-y rounded-md border border-gray-300 p-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          rows={3}
          value={goalsText}
          onChange={(event) => setGoalsText(event.target.value)}
        />
      </div>

      {isGuest ? (
        <p
          className="rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-800"
          data-testid="guest-note"
        >
          You&apos;re browsing as a guest. Sign in to save and reuse your profile across chats.
        </p>
      ) : null}

      {saveError ? (
        <p
          className="rounded-md border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-700"
          role="alert"
          data-testid="profile-save-error"
        >
          {saveError}
        </p>
      ) : null}

      {saved ? (
        <p
          className="rounded-md border border-green-300 bg-green-50 px-3 py-2 text-sm text-green-800"
          role="status"
          data-testid="profile-saved"
        >
          Profile saved.
        </p>
      ) : null}

      <button
        type="button"
        className="rounded-md bg-blue-600 px-4 py-2 font-medium text-white hover:bg-blue-700 disabled:opacity-50"
        disabled={saving}
        onClick={() => void handleSave()}
      >
        {saving ? "Saving…" : "Save profile"}
      </button>
    </section>
  );
}
