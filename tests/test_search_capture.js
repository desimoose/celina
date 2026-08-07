const test = require("node:test");
const assert = require("node:assert/strict");

const capture = require("../web/search_capture.js");

test("buildSearchCapturePayload prefers abstract text", () => {
  const payload = capture.buildSearchCapturePayload({
    title: "Controlled trial",
    url: "https://example.test/trial",
    kind: "research",
    abstract: "Abstract text",
    snippet: "Snippet text",
  });

  assert.deepEqual(payload, {
    title: "Controlled trial",
    url: "https://example.test/trial",
    kind: "research",
    excerpt: "Search excerpt:\nAbstract text",
    origin: "search",
    source_result: {
      title: "Controlled trial",
      url: "https://example.test/trial",
      kind: "research",
    },
  });
});

test("buildSearchCapturePayload bounds the labeled excerpt to the notebook limit", () => {
  const payload = capture.buildSearchCapturePayload({
    title: "Controlled trial",
    url: "https://example.test/trial",
    kind: "research",
    abstract: "x".repeat(6000),
  });

  assert.equal(payload.excerpt.startsWith("Search excerpt:\n"), true);
  assert.equal(payload.excerpt.length, 5000);
});

test("buildSearchCapturePayload falls back to snippet when abstract is missing", () => {
  const payload = capture.buildSearchCapturePayload({
    title: "Controlled trial",
    url: "https://example.test/trial",
    kind: "research",
    snippet: "Snippet text",
  });

  assert.equal(payload.excerpt, "Search excerpt:\nSnippet text");
});

test("buildSearchCapturePayload rejects unsafe links", () => {
  assert.throws(
    () =>
      capture.buildSearchCapturePayload({
        title: "Unsafe result",
        url: "javascript:alert(1)",
        kind: "research",
        snippet: "Snippet text",
      }),
    /http or https/i,
  );
});

test("resolveSelectedNotebookId preserves the selected notebook across view changes", () => {
  const selectedId = capture.resolveSelectedNotebookId(
    [{ id: "sleep" }, { id: "memory" }],
    "memory",
    "sleep",
  );

  assert.equal(selectedId, "memory");
});

test("resolveSelectedNotebookId falls back to the active notebook, then the first notebook", () => {
  assert.equal(
    capture.resolveSelectedNotebookId([{ id: "sleep" }, { id: "memory" }], "", "memory"),
    "memory",
  );
  assert.equal(
    capture.resolveSelectedNotebookId([{ id: "sleep" }, { id: "memory" }], "", "missing"),
    "sleep",
  );
  assert.equal(capture.resolveSelectedNotebookId([], "", "missing"), "");
});
