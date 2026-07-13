/**
 * URL safety helpers shared by any surface that renders untrusted third-party links.
 *
 * Citation / evidence URLs originate from untrusted content (search-result and crawled-page
 * URLs the market/web-search workers forward verbatim), so a `javascript:` / `data:` scheme
 * would become a DOM-XSS sink — React does not sanitize an `href`. Centralizing the guard here
 * (rather than duplicating it per component) keeps one audited definition of "safe to link".
 */

/**
 * Return `url` only when it is a parseable absolute `http(s)` URL — otherwise `null`, so the
 * caller renders it as plain text instead of a clickable anchor. Anything that is not an
 * `http:`/`https:` URL (relative strings, `javascript:`, `data:`, unparseable input) degrades.
 */
export function safeHttpUrl(url: string | null | undefined): string | null {
  if (!url) {
    return null;
  }
  try {
    const parsed = new URL(url);
    if (parsed.protocol === "http:" || parsed.protocol === "https:") {
      return url;
    }
  } catch {
    // Not an absolute/parseable URL — treat as non-link.
  }
  return null;
}
