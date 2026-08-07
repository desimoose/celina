const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");

function makeElement(id) {
  return {
    id,
    hidden: false,
    disabled: false,
    checked: false,
    value: "",
    textContent: "",
    innerHTML: "",
    dataset: {},
    style: {},
    classList: { add() {}, remove() {}, toggle() {} },
    addEventListener() {},
    removeEventListener() {},
    setAttribute() {},
    appendChild() {},
    replaceChildren() {},
    contains() { return false; },
    focus() {},
    requestSubmit() {},
  };
}

function installBrowserShims() {
  const elements = new Map();
  const doc = {
    readyState: "complete",
    getElementById(id) {
      if (!elements.has(id)) elements.set(id, makeElement(id));
      return elements.get(id);
    },
    querySelector(selector) {
      if (selector === 'meta[name="celina-csrf"]') return { content: "csrf-token" };
      return null;
    },
    querySelectorAll() {
      return [];
    },
    createElement() {
      return makeElement("created");
    },
    addEventListener() {},
  };
  const win = {
    location: { origin: "http://127.0.0.1" },
    addEventListener() {},
    SearchCapture: {},
    pywebview: undefined,
  };
  global.document = doc;
  global.window = win;
  global.fetch = async (url) => ({
    json: async () => {
      if (url === "/api/config") {
        return {
          providers: [
            { id: "ollama", local: true, ready: true },
            { id: "openai", local: false, ready: false },
          ],
          tools: [],
        };
      }
      if (url === "/api/settings") {
        return {
          session_retention_seconds: 86400,
          provider_privacy: {
            ollama: "Ollama — stays on this machine",
            openai: "question/context sent to provider",
          },
        };
      }
      if (url === "/api/notebooks") return { notebooks: [] };
      if (url === "/api/projects") return { projects: [] };
      if (url === "/api/workspace") return { files: [] };
      return {};
    },
  });
  return elements;
}

function loadApp() {
  const appPath = path.join(__dirname, "..", "web", "app.js");
  delete require.cache[require.resolve(appPath)];
  installBrowserShims();
  return require(appPath);
}

test("deleteCurrentSession retains the session id until deletion succeeds", async () => {
  const app = loadApp();
  assert.equal(typeof app.deleteCurrentSession, "function");

  app.state.sessionId = "session-123";
  app.state.incognito = false;
  global.fetch = async () => ({
    json: async () => ({ error: "delete failed" }),
  });

  const failed = await app.deleteCurrentSession();
  assert.equal(failed, false);
  assert.equal(app.state.sessionId, "session-123");

  let requestedUrl = null;
  global.fetch = async (url) => {
    requestedUrl = url;
    return { json: async () => ({ ok: true }) };
  };

  const succeeded = await app.deleteCurrentSession();
  assert.equal(succeeded, true);
  assert.equal(requestedUrl, "/api/sessions/session-123");
  assert.equal(app.state.sessionId, null);
});

test("turning Incognito off uses the configured retention label", async () => {
  const app = loadApp();
  assert.equal(typeof app.setIncognitoMode, "function");

  app.state.sessionId = null;
  app.state.incognito = true;
  app.state.sessionRetentionSeconds = 3600;

  await app.setIncognitoMode({ target: { checked: false } });

  const engine = document.getElementById("engine").textContent;
  assert.match(engine, /1 hour/);
  assert.doesNotMatch(engine, /24 hours/);
});
