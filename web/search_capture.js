(function (root, factory) {
  if (typeof module === "object" && module.exports) {
    module.exports = factory();
    return;
  }
  root.SearchCapture = factory();
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  const EXCERPT_LIMIT = 5000;
  const EXCERPT_PREFIX = "Search excerpt:\n";

  function cleanText(value) {
    return typeof value === "string" ? value.trim() : "";
  }

  function requireHttpUrl(value, field = "url") {
    const url = cleanText(value);
    if (!/^https?:\/\//i.test(url)) {
      throw new Error(`${field} must be an http or https URL`);
    }
    return url;
  }

  function excerptText(result) {
    const text = cleanText(result?.abstract) || cleanText(result?.snippet);
    if (!text) throw new Error("Search result needs an abstract or snippet");
    const remaining = Math.max(0, EXCERPT_LIMIT - EXCERPT_PREFIX.length);
    return `${EXCERPT_PREFIX}${text.slice(0, remaining).trimEnd()}`;
  }

  function buildSearchCapturePayload(result) {
    const title = cleanText(result?.title) || "Untitled result";
    const url = requireHttpUrl(result?.url || result?.oa_url);
    const kind = cleanText(result?.kind);
    return {
      title,
      url,
      kind,
      excerpt: excerptText(result),
      origin: "search",
      source_result: { title, url, kind },
    };
  }

  function resolveSelectedNotebookId(notebooks, selectedId, activeNotebookId) {
    const ids = (Array.isArray(notebooks) ? notebooks : [])
      .map((item) => cleanText(item?.id))
      .filter(Boolean);
    if (selectedId && ids.includes(selectedId)) return selectedId;
    if (activeNotebookId && ids.includes(activeNotebookId)) return activeNotebookId;
    return ids[0] || "";
  }

  function prefillNotebookDraft(query) {
    const text = cleanText(query);
    return {
      title: text.slice(0, 120),
      goal: text.slice(0, 10000),
    };
  }

  function resultCaptureKey(result) {
    return `${cleanText(result?.title)}|${cleanText(result?.url || result?.oa_url)}`;
  }

  return {
    buildSearchCapturePayload,
    prefillNotebookDraft,
    resolveSelectedNotebookId,
    resultCaptureKey,
  };
});
