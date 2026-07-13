# Architecture review — SEC-08-contact-redaction · engineer revision 1

## Verdict: APPROVED

## Design conformance
| id | area | expected (design ref) | observed | gap / required change |
|----|------|-----------------------|----------|-----------------------|
| A1 | Single chokepoint in LLM layer | Redaction at the **egress boundary — one place, in the LLM layer, not scattered across agents** (§7.6, §6.16) | `llm/redaction.py` pure util, called only from `LLMRouter.complete` (line 230) and `.stream` (line 310). grep confirms **no** `redact_*` call in `structuring.py`/`responder.py`/`planner.py`/`tools/` | none |
| A2 | Target structure (§8) | Redaction belongs in `llm/` | New module `backend/app/llm/redaction.py`, exported via `llm/__init__.py` | none |
| A3 | Fields stripped | name, email, phone, postal address, personal URLs/profile links (§6.16 item 16) | All five covered; photo correctly N/A (no image egress path today, documented) | none |
| A4 | Substance preserved | employers, titles, dates, skills, education must survive (§6.16, §7.6) | Conservative phone regex protects `2019-2023`; ZIP anchored to `City, ST`; name scoped to labelled line + first-line header. Preservation asserted in tests | none |
| A5 | Layering | Router→Service→Agent; util is dependency-free, no cross-layer leak | `redaction.py` imports only `re` + `.types.ChatMessage`; applied before any `client` call | none |
| A6 | Budget posture (§11) | free/OSS, no ML/NER | Compiled regex/heuristics only, no network/model dep; matches `guardrails/heuristics.py` minimal-slice posture | none |
| A7 | Only production egress path | Router is the sole real-model path (task §Where-the-gap) | Confirmed: blanket redaction of all outbound roles at the router naturally covers CV-structuring input + RAG-grounding chunks without per-agent tagging | none |

## Cross-cutting checks
- [x] Fits target structure (§8) + layering (Router→Service→Agent/Repo)
- [x] Honors locked decisions (§6.16/§7.6 contact-only redaction locked; router remains the failover chokepoint, mid-stream resume prefill correctly not re-redacted)
- [x] Interfaces-before-implementations (operates on `ChatMessage` port; no coupling to a concrete client)
- [x] Budget posture respected (regex/heuristic, no ML/NER)

## Notes
- Blanket redaction of all message roles (not just user CV turns) is the design-sanctioned "one place, not scattered" choice — over-redacting benign URLs in ordinary chat is the safe direction at an egress boundary and is documented honestly. Endorsed.
- Correctly scoped out (not gaps): embedding pipeline `llm/embeddings.py` is in-process sentence-transformers (no external egress), and the memory-writer PII redaction is the **separate** §7.6/§5.4 learning-loop obligation (Art. 9 exclusion) — belongs to the P9 memory-writer task, not here. The engineer flagged the embedding item as a follow-up; no action required for this task.
- Photo/image redaction N/A is accurate: P5 VLM-OCR is reserved, not implemented; no raw image bytes reach the chat LLM today.
