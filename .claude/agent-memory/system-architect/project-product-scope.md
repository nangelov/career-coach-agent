---
name: project-product-scope
description: LOCKED scope ruling (§1.1/§6.11) — career coaching & personal development ONLY; job postings are a market-signal source, not a product surface. Rescopes P6.
metadata:
  type: project
---

**The app is a career coach / personal-development assistant. It is NOT a job board.** Locked 2026-07-13 by the
owner; written into design §1.1, §5.6, §6.11.

The only loop every feature must serve:
`CV/profile + target role → skills gap → PDP → goals/tasks → progress`

**Why:** the owner explicitly rejected job-hunting as a purpose ("not job hunting, job board, doctor, general
chat assistant"). Job postings are mined as **evidence of what the market requires for a role you want to grow
into** — e.g. *"PM → AI Solution Architect: what does the market ask for?"* — never surfaced as inventory.

**How to apply (gate on these):**
- **P6 was rescoped** from "Richer job search" → **Market intelligence**. REJECT any P6 work that adds: listings
  UI, location/remote/salary filters, save/track jobs, per-posting match scoring, `GET/POST /api/jobs`,
  application tracking.
- Durable artifact = **`role_profiles`** — canonical role → aggregated requirements (skill → frequency/weight/
  evidence). **Global, NOT user-scoped** (a role's market requirements are the same for everyone). Two
  consequences to protect: extraction is paid **once per role** and amortized (a real LLM-cost control, §7.5),
  and the data is **non-personal** (the CV never travels with postings).
- `jobs` → **`job_postings`**: raw evidence only, TTL-cached, **third-party PII stripped at ingest** (recruiter
  names/emails — they never consented).
- **This assigns the previously-unowned `kb_documents` shared corpus** (`user_id IS NULL`): the market-intel
  pipeline populates it. Baseline = **ESCO / O\*NET** taxonomies (free, authoritative, *no scraping*); postings
  are only the recency delta. Never scrape LinkedIn (ToS).
- "Match scoring" now means `user profile △ role_profile` = the skills gap, feeding P7's PDP.
- **Topic guardrail (§7.4)** is what keeps this true in code: on the planner's *existing* `Intent` classification
  (no extra LLM call) — `OFF_TOPIC` → refuse, `JOB_HUNTING` → **redirect** (a near-miss on a real capability;
  never lump it in with abuse).
- **Still open:** CV tailoring / cover letters / interview prep. By this ruling they are job-hunting → **out**.
  My standing recommendation: hold the line.

Under this scope the **Dashboard (P8) is core**, not an over-build — I initially mis-ranked it while assuming a
job-hunting product. See [[project-security-privacy-posture]].
