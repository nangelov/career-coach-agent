# Taxonomy seed data — provenance & licensing

`taxonomy_seed.json` is a small, **curated static subset** of occupation + skill vocabulary
used to seed the shared RAG knowledge base (P6-01). It is intentionally a representative
sample (~two dozen tech / data / AI / product-management occupations), **not** the full
taxonomy — enough for later phases and tests to exercise real data. The ingestion pipeline
(`app/ingestion/taxonomy_seed.py` + `app/tasks/taxonomy.py`) is the deliverable; sourcing the
full live dataset is a separate, documented upgrade path (below).

## Sources & licensing (both free to redistribute)

- **ESCO** (European Skills, Competences, Qualifications and Occupations) — published by the
  European Commission under the **Creative Commons Attribution 4.0 International (CC BY 4.0)**
  licence, free to reuse and redistribute with attribution. Occupation labels/descriptions and
  skill labels here are derived from the ESCO classification (ESCO v1, built on **ISCO-08**
  occupation codes, used as the `id` for `taxonomy: "esco"` entries).
  https://esco.ec.europa.eu/ — © European Union, ESCO, CC BY 4.0.
- **O*NET** (Occupational Information Network) — sponsored by the U.S. Department of Labor.
  O*NET data is in the **public domain** in the United States and free to redistribute (the
  O*NET® name/logo are trademarks used here only to cite provenance). Occupation
  titles/descriptions and the O*NET-SOC codes used as the `id` for `taxonomy: "onet"` entries
  are derived from the O*NET database. https://www.onetonline.org/

Descriptions are paraphrased/condensed from the above public sources for brevity. No scraping
or live API call is performed at runtime — this file is checked in and read from disk.

## Schema (each array element)

```json
{
  "taxonomy": "esco" | "onet",
  "id": "<ISCO-08 code | O*NET-SOC code>",
  "title": "<occupation name>",
  "description": "<1-3 sentence occupation summary>",
  "skills": ["<skill label>", "..."]
}
```

`source` on the resulting `kb_documents` row is `"<taxonomy>:<id>"` (e.g. `"onet:15-1252.00"`,
`"esco:2512"`), which is the idempotency key: re-running the seed replaces the document for a
given `source` rather than duplicating it.

## Upgrade path — swapping in the full ESCO / O*NET bulk download

To move from this curated sample to the full taxonomy, **replace this file** (or point the
loader at a new path) with a normalized export of a bulk download — no code change to the
ingestion pipeline is required, only the data + a mapping step:

1. Download the bulk distributions (one-off, offline — still no runtime scraping):
   - ESCO: the CSV/RDF classification export from the ESCO download portal.
   - O*NET: the O*NET Database text/Excel distribution from onetcenter.org.
2. Map their columns to this file's schema (`taxonomy`, `id`, `title`, `description`,
   `skills[]`) — e.g. join O*NET `Occupation Data` to `Skills`/`Technology Skills`, or ESCO
   `occupations_en.csv` to `occupationSkillRelations_en.csv`.
3. Write the normalized result to `taxonomy_seed.json` (or pass `--path` to the seed CLI) and
   re-run the seed task; the idempotent upsert keeps exactly one document per `source`.
