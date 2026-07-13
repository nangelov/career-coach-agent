---
name: project-privacy-ops-decisions
description: LOCKED §6.16-6.25 — contact-only CV redaction, data loss accepted, 30d/session retention, Tavily 3-key pool, Altcha PoW, consent gate, English-only, Sentry, no cover letters
metadata:
  type: project
---

Owner-decided 2026-07-13; written into design §6.16–§6.25, §5.7, §7.5–§7.7. Gate on these.

- **§6.16 CV redaction = contact details ONLY.** Strip name/email/phone/address/personal-links/photo **at the
  LLM egress boundary** (one chokepoint in `llm/`, NOT scattered across agents). **Keep** employers, titles,
  dates, skills, education — that's the substance the coach reasons on. Reject any PR that redacts more (guts
  the product) or redacts per-agent (DRY/SoC violation).
- **§6.17 Data loss ACCEPTED.** Free app, ephemeral HF Space, self-hosted PG+Redis, **no managed tier, no
  backups**. *The obligation this creates:* the UI + privacy notice must say **data may be lost on restart**.
  Reject any copy promising "your history is saved". P2's "survives restart" is best-effort, not a guarantee.
- **§6.18 Retention:** SSO = **30 days after last activity** (periodic Celery purge); guests = **session TTL
  only**. Retention is a *maximum*, not an availability promise (see §6.17).
- **§6.19 Search = Tavily, 3 rotating keys** (`TAVILY_API_KEY_1|2|3`, Space Secrets): ordered failover +
  **promote-survivor-to-primary persisted in Redis** (don't retry a dead/exhausted key every call). **MUST reuse
  the `llm/router.py` failover pattern** — reject a second, parallel failover mechanism. Replaces SerpAPI.
- **§6.20 Learning-resource corpus:** Coursera/Udacity/Udemy/edX via Tavily → normalized, **skill-keyed**, shared
  (`user_id IS NULL`), cited in the PDP. Prefer official catalogs/APIs over scraping. Amortized like
  `role_profiles` (see [[project-product-scope]]).
- **§6.21 Bot protection = per-IP limit + Altcha proof-of-work** (OSS, self-hosted, no account — no Turnstile,
  no third-party callout). ⚠️ HF Spaces is **behind a proxy**: per-IP limits MUST use a trusted-proxy
  `X-Forwarded-For` config or the header is spoofable and the limit is worthless.
- **§6.22 Consent gate:** no session is minted without ToS/privacy acceptance — checkbox at SSO login (persist
  policy version + timestamp → re-prompt on bump) and at **every** guest-session start. Ship with the BFF work
  (S4), which already rewrites session creation.
- **§6.23 English only** this iteration. i18n / TTS / STT / voice = future, not v2.
- **§6.24 Sentry free tier** with PII scrubbing — the one blessed external dependency. **§7.7: no IR programme,
  no rotation schedule.** Key rotation is a documented one-liner (rotate secret → restart → sessions invalidate);
  this is *right-sized*, not an oversight — don't let anyone gold-plate it.
- **§6.25 NO cover letters, NO CV tailoring, NO interview prep** — job-assistant features, out of scope.
- **Admin panel + audit trail: deferred** to a pre-go-live phase, by owner decision. Don't flag its absence.

**🛑 PRE-GO-LIVE REVIEW (blocking gate, before any P11 cutover task).** Owner + architect sit down together:
critical-gaps sweep (is [SEC] S1–S16 *genuinely* done, not just ticked?), security/privacy sign-off (**any
"fix it right after launch" item is a launch blocker by default**), honesty check on the user-facing notices
(data loss / CV→LLM provider / retention), scope check (no creep back to a job board), **admin panel + audit
trail design**, and **next-iteration planning** (parked: i18n/TTS/STT/voice, managed datastore tier, eval
gates, k8s only if traffic justifies). Ends in an explicitly recorded **GO / NO-GO**. Written into plan.md
(P11 header + sequencing diagram) and tasks.md (P11 + "Still open").

See [[project-security-privacy-posture]] for the [SEC] block sequencing (S1–S16).
