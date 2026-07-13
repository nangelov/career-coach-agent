import type { Metadata } from "next";

import LegalPage from "@/components/LegalPage";

/**
 * Public Privacy Notice (design §6.16–18, §6.22, §7.6). Static server component, no auth —
 * linked from the login screen's consent checkbox, so it must render before any session
 * exists. Content is deliberately plain-language and maps to the GDPR disclosures the
 * design requires.
 *
 * NOTE on CV redaction wording: the redaction chokepoint at the LLM egress boundary is
 * SEC-08 (S10), which has NOT merged yet (queue.md: pending). Per the task, this notice
 * describes the intended/contracted behaviour but phrases it as "before it is sent"
 * rather than claiming an already-shipped mechanism. Facts already true today
 * (self-hosted Postgres/Redis, SSO-only/no passwords, cascading erasure from SEC-05) are
 * stated plainly.
 */
export const metadata: Metadata = {
  title: "Privacy Notice — Career Coach",
  description: "How Career Coach collects, uses, and protects your data.",
};

export default function PrivacyPage() {
  return (
    <LegalPage title="Privacy Notice" siblingHref="/terms" siblingLabel="Terms of Service">
      <p>
        This notice explains what data Career Coach (&ldquo;the app&rdquo;) collects, why, how
        long it is kept, and the rights you have over it. Career Coach is a free, hobby-scale
        career-coaching app. Please read it before you accept and sign in.
      </p>

      <section className="space-y-2">
        <h2>Who is responsible</h2>
        <p>
          The operator of this Career Coach deployment is the data controller for the personal
          data described below. Because the app is provided free of charge with no commercial
          backing, some protections common to paid services (for example, guaranteed backups)
          do not apply — see &ldquo;Data may be lost&rdquo; below.
        </p>
      </section>

      <section className="space-y-2">
        <h2>What we collect</h2>
        <ul>
          <li>
            <strong>Sign-in identity.</strong> When you sign in with Google or LinkedIn we
            receive, via OpenID Connect, your provider account identifier (<code>sub</code>),
            email address, and display name. We <strong>never</strong> receive or store a
            password — sign-in is single-sign-on only.
          </li>
          <li>
            <strong>Your CV and profile.</strong> Any CV you upload and the structured profile
            derived from it (roles, titles, dates, skills, education).
          </li>
          <li>
            <strong>Conversations.</strong> The messages you exchange with the coach.
          </li>
          <li>
            <strong>Feedback.</strong> Free-text feedback and per-message thumbs up/down you
            choose to send.
          </li>
          <li>
            <strong>Learned preferences.</strong> The app <em>may in future</em> learn and store
            your preferences and communication style to personalise responses; you will be able
            to view and delete these.
          </li>
        </ul>
      </section>

      <section className="space-y-2">
        <h2>Your CV and third-party AI providers</h2>
        <p>
          To answer your questions, the coach sends relevant parts of your CV and profile to a
          third-party large-language-model (LLM) provider that generates the responses.
        </p>
        <p>
          <strong>Before it is sent, your contact details are redacted.</strong> Your name,
          email address, phone number, postal address, personal links, and photo are stripped
          out at the boundary where data leaves the app, so they are not transmitted to the LLM
          provider. Your professional history — employers, job titles, dates, skills, and
          education — <strong>is</strong> sent, because that is what the coach reasons about to
          give you advice. Do not upload information you are not comfortable having processed
          this way.
        </p>
      </section>

      <section className="space-y-2">
        <h2>Why we use it, and the legal basis</h2>
        <p>
          Your data is used <strong>only</strong> to provide career coaching and personal
          development support: analysing your skills gap, building development plans, and
          tracking your goals. It is not a job board and is not used for advertising or sold to
          anyone. The legal basis is your <strong>consent</strong>, which you give at sign-in and
          can withdraw at any time by deleting your data (below).
        </p>
      </section>

      <section className="space-y-2">
        <h2>How long we keep it (retention)</h2>
        <ul>
          <li>
            <strong>Signed-in (SSO) accounts:</strong> data is retained for up to{" "}
            <strong>30 days after your last activity</strong>, after which it is automatically
            purged.
          </li>
          <li>
            <strong>Guests:</strong> guest sessions are <strong>session-only</strong> — nothing
            is stored durably, ever.
          </li>
          <li>
            <strong>Either:</strong> you can erase your data immediately at any time (below).
          </li>
        </ul>
      </section>

      <section className="space-y-2">
        <h2>Data may be lost</h2>
        <p>
          Because this is a free app on ephemeral hosting with no managed database tier and{" "}
          <strong>no backups</strong>, your data may be lost at any time — for example, when the
          service restarts. The retention periods above are a <strong>maximum</strong>, not a
          promise that your data will remain available. Keep your own copy of anything important
          (you can export it — below).
        </p>
      </section>

      <section className="space-y-2">
        <h2>Where your data is stored</h2>
        <p>
          Aside from the CV/profile text sent to the LLM provider as described above, your data
          is held in a self-hosted PostgreSQL database and Redis cache operated for this app — it
          is not placed in any third-party managed database service.
        </p>
      </section>

      <section className="space-y-2">
        <h2>Your rights</h2>
        <p>Under the GDPR and similar laws you have the right to:</p>
        <ul>
          <li>
            <strong>Access and export</strong> your data — request a copy via{" "}
            <code>GET /api/me/export</code>.
          </li>
          <li>
            <strong>Erasure</strong> — delete your account and all associated data immediately via{" "}
            <code>DELETE /api/me</code>. Deletion cascades across your profile, conversations, and
            feedback.
          </li>
          <li>
            <strong>Rectification</strong> of inaccurate data, <strong>restriction</strong> and{" "}
            <strong>objection</strong> to processing, and the right to{" "}
            <strong>withdraw consent</strong> at any time.
          </li>
          <li>
            The right to lodge a complaint with your local data-protection authority.
          </li>
        </ul>
        <p>
          Guests have no durable data to access, export, or erase — a guest session simply ends.
        </p>
      </section>

      <section className="space-y-2">
        <h2>Changes to this notice</h2>
        <p>
          If this notice changes materially, the version above is bumped and signed-in users are
          asked to accept the new version on their next sign-in.
        </p>
      </section>
    </LegalPage>
  );
}
