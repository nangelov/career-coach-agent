import type { Metadata } from "next";

import LegalPage from "@/components/LegalPage";

/**
 * Public Terms of Service (design §1.1 product scope, §7.6). Static server component, no
 * auth — linked from the login screen's consent checkbox, so it must render before any
 * session exists. Acceptable-use scope mirrors the §1.1 definition and the cross-cutting
 * scope-discipline line in dev-board/tasks.md.
 */
export const metadata: Metadata = {
  title: "Terms of Service — Career Coach",
  description: "The terms under which you may use Career Coach.",
};

export default function TermsPage() {
  return (
    <LegalPage title="Terms of Service" siblingHref="/privacy" siblingLabel="Privacy Notice">
      <p>
        These terms govern your use of Career Coach (&ldquo;the app&rdquo;), a free,
        hobby-scale career-coaching assistant. By accepting them at sign-in you agree to what
        follows.
      </p>

      <section className="space-y-2">
        <h2>What the app is for</h2>
        <p>
          Career Coach helps you with <strong>career coaching and personal development</strong>:
          analysing your skills gap against a role you want to grow into, building a personal
          development plan, and tracking goals and progress. It may also summarise what the
          labour market expects for a given role.
        </p>
      </section>

      <section className="space-y-2">
        <h2>What the app is not</h2>
        <p>The app is deliberately narrow. It is <strong>not</strong>:</p>
        <ul>
          <li>
            a <strong>job board or job-hunting tool</strong> — it does not list, search, save, or
            apply to job postings;
          </li>
          <li>
            a source of <strong>medical, legal, financial, or therapeutic advice</strong> — such
            requests are out of scope and will be declined;
          </li>
          <li>a general-purpose chat assistant — off-topic requests are redirected to coaching.</li>
        </ul>
      </section>

      <section className="space-y-2">
        <h2>Acceptable use</h2>
        <p>
          Use the app only for its intended coaching purpose and in a lawful way. Do not attempt
          to misuse, overload, reverse-engineer, or extract data from the service, and do not
          upload content you have no right to share. AI-generated coaching is guidance only —
          use your own judgement before acting on it.
        </p>
      </section>

      <section className="space-y-2">
        <h2>No warranty</h2>
        <p>
          The app is provided free of charge, &ldquo;as is&rdquo; and &ldquo;as available&rdquo;,
          with <strong>no warranties</strong> of any kind. It may be unavailable, and — as
          explained in the Privacy Notice — your data may be lost at any time (there are no
          backups). To the fullest extent permitted by law, the operator is not liable for any
          loss arising from your use of the app.
        </p>
      </section>

      <section className="space-y-2">
        <h2>Accounts and termination</h2>
        <p>
          Sign-in is single-sign-on only (Google or LinkedIn); there are no passwords. You may
          end your session at any time and delete your account and data immediately (see the
          Privacy Notice). The operator may suspend or terminate access, or discontinue the
          service, at any time — including for misuse of the terms above.
        </p>
      </section>

      <section className="space-y-2">
        <h2>Privacy</h2>
        <p>
          Your use of the app is also governed by our <a href="/privacy">Privacy Notice</a>,
          which explains what data is collected, how your CV is processed, how long data is
          kept, and how to export or erase it.
        </p>
      </section>

      <section className="space-y-2">
        <h2>Changes</h2>
        <p>
          If these terms change materially, the version above is bumped and signed-in users are
          asked to accept the new version on their next sign-in.
        </p>
      </section>
    </LegalPage>
  );
}
