(function initializeSearchCore(globalScope) {
  "use strict";

  function normalizeTitle(value) {
    return String(value ?? "")
      .normalize("NFKC")
      .toLocaleLowerCase()
      .trim()
      .replace(/\s+/gu, " ");
  }

  function compareIds(left, right) {
    if (left === right) return 0;
    return left < right ? -1 : 1;
  }

  function searchTitles(documents, query, limit = 20) {
    const normalizedQuery = normalizeTitle(query);
    if (!normalizedQuery) return [];
    const tokens = normalizedQuery.split(" ").filter(Boolean);
    return (Array.isArray(documents) ? documents : [])
      .map((document) => {
        const normalizedTitle = normalizeTitle(document?.title);
        const positions = tokens.map((token) => normalizedTitle.indexOf(token));
        if (positions.some((position) => position < 0)) return null;
        return {
          document,
          exact: normalizedTitle === normalizedQuery ? 0 : 1,
          prefix: normalizedTitle.startsWith(normalizedQuery) ? 0 : 1,
          firstPosition: Math.min(...positions),
          publishedAt: String(document.published_at ?? ""),
        };
      })
      .filter(Boolean)
      .sort((left, right) =>
        left.exact - right.exact
        || left.prefix - right.prefix
        || left.firstPosition - right.firstPosition
        || right.publishedAt.localeCompare(left.publishedAt)
        || compareIds(String(left.document.id ?? ""), String(right.document.id ?? "")),
      )
      .slice(0, Math.max(0, limit))
      .map((entry) => entry.document);
  }

  const api = { normalizeTitle, searchTitles };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  globalScope.TogosSearchCore = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
