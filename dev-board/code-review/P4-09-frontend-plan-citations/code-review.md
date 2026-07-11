# Code review — P4-09-frontend-plan-citations · engineer revision 2

## Verdict: APPROVED

## Findings (revision 2)
| id | severity | file:line | issue | required change |
|----|----------|-----------|-------|-----------------|
| C1 | resolved | frontend/components/Chat.tsx:`safeHttpUrl`/`CitationEntry` | Fixed. `safeHttpUrl(url)` parses the citation url with `new URL()` in a try/catch and returns it only when `protocol` is `http:`/`https:`; `CitationEntry` renders the `<a href>` branch only when it yields a value, else a plain `<span>` label. `javascript:`/`data:`/uppercase/obfuscated (`java\nscript:`) schemes and unparseable/relative urls all degrade to non-clickable text. New component test feeds a `javascript:` citation and asserts the label renders with no `link` role. | none — verified |
| C2 | resolved | frontend/components/Chat.tsx (`CitationList` key) | Fixed. List key is now `` `${citation.source_id ?? citation.url ?? "src"}-${i}` `` — index folded in, so duplicate source_id/url no longer collide. | none — verified |

## Notes (revision 2)
- Re-verified the sole gating item (C1). The scheme allowlist is enforced at render time with no CSP dependency, matching the required change exactly. Reasoned through the WHATWG URL-parser edge cases (case-normalization of the scheme, tab/newline stripping, throwing on relative urls) — all land in the safe (non-link) branch.
- Ran `npm test` from `frontend/`: 6 suites / 59 tests passing (+1 unsafe-scheme degradation test vs. rev 1). Engineer's reported results reproduce.
- All rev-1 approvals (transport layer, additive plan/citation rendering, `tool_call`/`tool_result` untouched) still hold — the fix is scoped to `CitationEntry`/`CitationList` and one new pure helper.
- No new findings. Acceptance criteria met.

---

# Code review — P4-09-frontend-plan-citations · engineer revision 1

## Verdict: CHANGES_REQUESTED

## Findings
| id | severity | file:line | issue | required change |
|----|----------|-----------|-------|-----------------|
| C1 | major | frontend/components/Chat.tsx:467-477 (`CitationEntry`) | `<a href={citation.url}>` renders a citation URL directly with no scheme validation. These URLs originate from untrusted third-party content (`backend/app/agents/web_searcher.py:212` maps `item.get("url")` from search-provider results / crawled pages straight into the `SourceCitation.url` sent on `done.citations`). React does **not** sanitize `href` — a `javascript:` (or `data:text/html`) scheme from a poisoned search result becomes a clickable DOM-XSS vector when the user clicks the source link. No CSP is configured (`frontend/next.config.*` has none) and React 19 only warns (dev-only) on `javascript:` URLs without blocking them, so this is unmitigated. | Validate the scheme before rendering an anchor: only treat the citation as a link when `url` parses to an `http:`/`https:` origin (e.g. `new URL(url)` in a try/catch, guard `protocol`), otherwise render the label as plain text (the `<span>` branch). Add a parser/component test for a `javascript:`-scheme citation degrading to non-link text. |
| C2 | nit | frontend/components/Chat.tsx:455 | `key={citation.source_id ?? citation.url ?? i}` can collide when two citations share the same `source_id`/`url` (e.g. two chunks from one KB doc), triggering React duplicate-key warnings. | Fold the index into the key (e.g. `` `${citation.source_id ?? citation.url ?? "src"}-${i}` ``) so keys are always unique. |

## Notes
- Transport layer (`chatStream.ts`) is clean: the `plan` variant mirrors the `tool_call` end-to-end precedent exactly, `parseCitations` degrades defensively (non-array → `[]`, per-field `nullableStr`), and the `DoneEvent`/union extensions are correct. Parser tests cover the plan-default-empty, full-citation, partial-null-fill, and malformed-non-array cases well.
- Additive behavior verified: `PlanIndicator` only renders when `workers.length > 0` and `CitationList` only when non-empty, so smalltalk / no-source turns are visually unchanged. Existing `tool_call`/`tool_result` handling is untouched. Component tests assert the no-worker/no-citation suppression.
- All non-URL rendered strings (`content`, `intent`, `steps`, `label`) go through React text nodes and are auto-escaped — the only unsafe sink is the `href` in C1.
- Verified locally from `frontend/`: `npm run type-check` clean, `npm run lint` → "No ESLint warnings or errors", `npx jest` → 6 suites / 58 tests passing. Engineer's reported results reproduce.
- Acceptance criteria are otherwise met; C1 is the sole gating item. C2 may be bundled into the same fix.
