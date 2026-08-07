// Celina workspace UI. Vanilla, no build step.

const $ = (id) => document.getElementById(id);

const state = {
  provider: "anthropic",
  providerManual: false,
  providers: [],
  tools: [],
  view: "work",
  history: [],
  viewing: null,       // { title, text } in the reader
  results: null,       // last search result (answer + sources)
  activeFile: null,
  projects: [],
  projectId: null,
  notebooks: [],
  activeNotebook: null,
  activeNotebookSourceId: null,
  selectedSearchNotebookId: "",
  outputFormat: "markdown",
  sessionRetentionSeconds: 86400,
  providerPrivacy: {},
  sessionId: null,      // local research session (created on first search)
  incognito: false,     // ephemeral search session; deleted on end or page close
  activeRunId: null,    // the bounded search run currently streaming
  eventSource: null,    // its live trace connection
  mascot: { notices: [], unread: 0, panelOpen: false },
};

const TERMINAL_RUN_KINDS = new Set([
  "search.completed", "search.stopped", "search.failed",
]);

const escapeHtml = (s) =>
  (s || "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const looksLikeUrl = (s) => /^https?:\/\//i.test(s);
const csrfToken = () => document.querySelector('meta[name="celina-csrf"]')?.content || "";
const searchCapture = () => window.SearchCapture || {};

// ---------- accessibility: focus trap for modal-style overlays ----------

const FOCUSABLE = 'a[href], button:not([disabled]), textarea:not([disabled]), '
  + 'input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])';
let activeTrap = null;

function focusablesIn(container) {
  return Array.from(container.querySelectorAll(FOCUSABLE))
    .filter((el) => el.offsetParent !== null);
}

// Keeps Tab/Shift+Tab cycling inside container while it's open, moves focus
// in on open, and restores it on release - the overlay never lets keyboard
// focus leak onto the page underneath.
function trapFocus(container) {
  releaseFocus();
  const previouslyFocused = document.activeElement;
  const onKeydown = (e) => {
    if (e.key !== "Tab") return;
    const items = focusablesIn(container);
    if (!items.length) return;
    const first = items[0], last = items[items.length - 1];
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
  };
  container.addEventListener("keydown", onKeydown);
  (focusablesIn(container)[0] || container).focus();
  activeTrap = { container, onKeydown, previouslyFocused };
}

function releaseFocus(focusInstead) {
  if (!activeTrap) return;
  const { container, onKeydown, previouslyFocused } = activeTrap;
  container.removeEventListener("keydown", onKeydown);
  activeTrap = null;
  const target = focusInstead || previouslyFocused;
  if (target && typeof target.focus === "function") target.focus();
}

// ---------- boot ----------

async function boot() {
  await refreshConfig();
  try { await loadSettingsMeta(); } catch (err) { setEngine("Could not load privacy settings: " + err.message); }
  try { await loadFiles(); } catch (err) { setEngine("Could not load Library: " + err.message); }
  try { await loadProjects(); } catch (err) { setEngine("Library is unavailable: " + err.message); }
  await loadNotebooks();
  wireNav();
  wireSettings();
  wireTour();
  wireWelcome();
  maybeWelcome();
  checkForUpdate();  // fire-and-forget - never blocks or delays boot
}

// Anonymous, best-effort. A failed check is not an error the user needs to
// see - it just quietly doesn't mention an update this launch.
async function checkForUpdate() {
  try {
    const data = await fetch("/api/update-check").then((r) => r.json());
    if (data.update_available && data.url) {
      const link = $("update-link");
      link.href = data.url;
      link.hidden = false;
      addMascotNotice("Update available", "A newer version of Celina is ready.", "attention");
    }
  } catch { /* quiet */ }
}

async function refreshConfig() {
  try {
    const cfg = await fetch("/api/config").then((r) => r.json());
    state.providers = cfg.providers || [];
    state.tools = cfg.tools || [];
  } catch {
    state.providers = [];
    state.tools = [];
  }
  pickProvider();
  updatePrivacyUi();
}

// Auto-pick the active AI. A connected (keyed) provider is preferred over a
// local one, since a keyed provider is what the user deliberately set up - but
// an explicit manual choice in Settings always wins. No visible rail control.
function pickProvider() {
  const ready = state.providers.filter((p) => p.ready);
  const currentReady = ready.find((p) => p.id === state.provider);
  if (state.providerManual && currentReady) return;
  const connected = state.providers.find((p) => !p.local && p.ready);
  if (connected) { state.provider = connected.id; return; }
  if (!currentReady) state.provider = (ready[0] || {}).id || state.provider;
}

// A keyed (non-local) provider is connected.
function isConnected() {
  return state.providers.some((p) => !p.local && p.ready);
}

function retentionLabel(seconds) {
  if (seconds === 0) return "immediately";
  if (seconds === 3600) return "1 hour";
  if (seconds === 86400) return "24 hours";
  if (seconds === 604800) return "7 days";
  return `${seconds} seconds`;
}

const RETENTION_BADGE_LABELS = {
  0: "Auto-delete immediately",
  3600: "Auto-delete after 1 hour",
  86400: "Auto-delete after 24 hours",
  604800: "Auto-delete after 7 days",
};

function providerPrivacyText(providerId = state.provider) {
  const selected = state.providers.find((p) => p.id === providerId);
  if (selected?.local) return "Ollama — stays on this machine";
  return state.providerPrivacy[providerId] || "question/context sent to provider";
}

function sessionBadgeText() {
  if (state.incognito) return "Incognito — deletes on end";
  return RETENTION_BADGE_LABELS[state.sessionRetentionSeconds]
    || `Auto-delete after ${retentionLabel(state.sessionRetentionSeconds)}`;
}

function sessionStateText() {
  if (state.sessionId) return state.incognito ? "Current session: active (incognito)" : "Current session: active";
  return state.incognito ? "Current session: waiting to start (incognito)" : "Current session: not started";
}

function updatePrivacyUi() {
  const badge = $("session-badge");
  if (badge) badge.textContent = sessionBadgeText();
  const stateEl = $("session-state");
  if (stateEl) stateEl.textContent = sessionStateText();
  const deleteBtn = $("session-delete");
  if (deleteBtn) deleteBtn.disabled = !state.sessionId;
  const composerCopy = $("composer-privacy");
  if (composerCopy) composerCopy.textContent = providerPrivacyText();
  const settingsCopy = $("set-provider-privacy");
  if (settingsCopy) settingsCopy.textContent = providerPrivacyText($("set-provider")?.value || state.provider);
  const settingsBadge = $("set-session-badge");
  if (settingsBadge) settingsBadge.textContent = sessionBadgeText();
  const settingsState = $("set-session-state");
  if (settingsState) settingsState.textContent = sessionStateText();
  const settingsDelete = $("set-delete-session");
  if (settingsDelete) settingsDelete.disabled = !state.sessionId;
}

async function loadSettingsMeta() {
  const data = await fetch("/api/settings").then((r) => r.json());
  if (data.error) throw new Error(data.error);
  state.sessionRetentionSeconds = data.session_retention_seconds ?? state.sessionRetentionSeconds;
  state.providerPrivacy = data.provider_privacy || {};
  updatePrivacyUi();
  return data;
}

// ---------- first-run welcome ----------

function wireWelcome() {
  $("wl-connect-go").addEventListener("click", () => wlStep("connect"));
  $("wl-skip").addEventListener("click", closeWelcome);
  $("wl-back").addEventListener("click", () => wlStep("intro"));
  $("wl-getkey").addEventListener("click", () => openExternal("https://openrouter.ai/keys"));
  $("wl-connect").addEventListener("click", wlConnect);
  $("wl-finish").addEventListener("click", closeWelcome);
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !$("welcome").hidden) closeWelcome();
  });
}

function maybeWelcome() {
  if (!isConnected()) {
    wlStep("intro");
    $("welcome").hidden = false;
    trapFocus($("welcome"));
  }
}

function wlStep(step) {
  let shown = null;
  for (const s of document.querySelectorAll("#welcome .wl-step")) {
    const visible = s.dataset.step === step;
    s.hidden = !visible;
    if (visible) shown = s;
  }
  // Whatever held focus lived in the step that just got hidden - move it
  // into the newly visible one instead of losing it to <body>.
  if (shown) (focusablesIn(shown)[0] || shown).focus();
}

async function wlConnect() {
  const key = $("wl-key").value.trim();
  if (!key) { $("wl-msg").textContent = "Paste your key first."; return; }
  $("wl-msg").textContent = "Connecting...";
  try {
    const res = await fetch("/api/settings", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Celina-CSRF": csrfToken(),
      },
      body: JSON.stringify({ keys: { OPENROUTER_API_KEY: key } }),
    }).then((r) => r.json());
    if (res.error) { $("wl-msg").textContent = res.error; return; }
    await refreshConfig();
    if (isConnected()) wlStep("done");
    else $("wl-msg").textContent = "That key did not connect. Check it and try again.";
  } catch (e) {
    $("wl-msg").textContent = "Could not connect: " + e.message;
  }
}

function closeWelcome() {
  $("welcome").hidden = true;
  releaseFocus($("url"));
}

// Open an external link in the system browser (desktop) or a new tab (dev).
function openExternal(url) {
  if (window.pywebview && window.pywebview.api && window.pywebview.api.open_external) {
    window.pywebview.api.open_external(url);
  } else {
    window.open(url, "_blank", "noopener");
  }
}

// ---------- settings ----------

let settingsInitial = null;  // { finder, sessionRetentionSeconds }

function wireSettings() {
  $("settings-open").addEventListener("click", openSettings);
  $("settings-close").addEventListener("click", closeSettings);
  $("settings-cancel").addEventListener("click", closeSettings);
  $("settings-save").addEventListener("click", saveSettings);
  $("settings").addEventListener("click", (e) => {
    if (e.target.id === "settings") closeSettings();   // scrim click
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !$("settings").hidden) closeSettings();
  });
}

async function openSettings() {
  const data = await loadSettingsMeta();
  const retentionOptions = [
    [0, "Immediately"],
    [3600, "1 hour"],
    [86400, "24 hours"],
    [604800, "7 days"],
  ];
  const rows = data.providers.map((p) => {
    const clearBtn = (!p.local && p.has_key)
      ? `<button type="button" class="set-clear" data-clear-for="${p.key_env}">Clear</button>` : "";
    const keyField = p.local ? "" : `
      <div class="set-key">
        <input type="password" autocomplete="off" data-key="${p.key_env}"
               placeholder="${p.has_key ? "set (····" + (p.key_hint || "") + ")" : "not set"}" />
        ${clearBtn}
      </div>`;
    return `
      <div class="set-row">
        <div class="set-label"><span class="set-dot ${p.has_key || p.local ? "on" : ""}"></span>${escapeHtml(p.label)}${p.local ? " (local, no key)" : ""}</div>
        ${keyField}
        <input class="set-model" type="text" data-model="${p.model_env}"
               value="${p.model_overridden ? escapeHtml(p.model) : ""}"
               placeholder="model: ${escapeHtml(p.model)}" />
      </div>`;
  }).join("");
  const ready = state.providers.filter((p) => p.ready);
  const whichAI = `
    <div class="set-row">
      <div class="set-label">Which AI answers</div>
      <select id="set-provider" class="set-select">
        ${ready.map((p) => `<option value="${p.id}"${p.id === state.provider ? " selected" : ""}>${escapeHtml(p.label)}${p.local ? " (local)" : ""}</option>`).join("")}
      </select>
      <div class="set-help" id="set-provider-privacy">${escapeHtml(providerPrivacyText())}</div>
    </div>`;
  const sessionPrivacy = `
    <div class="set-row">
      <div class="set-label">Session retention</div>
      <select id="set-retention" class="set-select">
        ${retentionOptions.map(([value, label]) => `<option value="${value}"${value === state.sessionRetentionSeconds ? " selected" : ""}>${label}</option>`).join("")}
      </select>
      <div class="set-help" id="set-session-badge">${escapeHtml(sessionBadgeText())}</div>
    </div>
    <div class="set-row">
      <div class="set-label">Current session</div>
      <div class="set-inline">
        <span class="set-state" id="set-session-state">${escapeHtml(sessionStateText())}</span>
        <button type="button" class="set-delete" id="set-delete-session"${state.sessionId ? "" : " disabled"}>Delete current session</button>
      </div>
      <div class="set-help">Incognito only affects the Celina session locally. It does not change how external providers handle what you ask them.</div>
    </div>`;
  const toolsStatus = `
    <div class="set-row">
      <div class="set-label">Connected tools</div>
      <div class="set-tools">
        ${state.tools.map((t) => `<span class="set-tool${t.present ? " on" : ""}">${escapeHtml(t.label)} &middot; ${t.present ? "connected" : "not found"}</span>`).join("")}
      </div>
    </div>`;
  $("settings-body").innerHTML = sessionPrivacy + whichAI + toolsStatus + rows + `
    <div class="set-row">
      <div class="set-label">Finder contact email</div>
      <input type="text" id="set-finder" placeholder="you@example.com"
             value="${escapeHtml(data.finder_email || "")}" />
    </div>`;
  const sp = $("set-provider");
  if (sp) sp.addEventListener("change", () => { state.provider = sp.value; state.providerManual = true; updatePrivacyUi(); });
  const retention = $("set-retention");
  if (retention) retention.addEventListener("change", () => updatePrivacyUi());
  const deleteSession = $("set-delete-session");
  if (deleteSession) deleteSession.addEventListener("click", async () => {
    $("settings-msg").textContent = "Deleting current session...";
    const ok = await deleteCurrentSession();
    if (ok) updatePrivacyUi();
    $("settings-msg").textContent = ok ? "Current session deleted." : $("settings-msg").textContent;
  });
  settingsInitial = { finder: data.finder_email || "", sessionRetentionSeconds: data.session_retention_seconds ?? 86400 };
  for (const btn of document.querySelectorAll("#settings-body .set-clear")) {
    btn.addEventListener("click", () => {
      const input = document.querySelector(`input[data-key="${btn.dataset.clearFor}"]`);
      const armed = input.dataset.clear === "1";
      input.dataset.clear = armed ? "" : "1";
      input.value = "";
      input.disabled = !armed;
      input.classList.toggle("cleared", !armed);
      btn.classList.toggle("armed", !armed);
      btn.textContent = armed ? "Clear" : "Undo";
    });
  }
  $("settings-msg").textContent = "";
  $("settings").hidden = false;
  trapFocus($("settings"));
}

async function saveSettings() {
  const keys = {}, models = {};
  for (const el of document.querySelectorAll("#settings-body input[data-key]")) {
    if (el.dataset.clear === "1") keys[el.dataset.key] = "";      // armed Clear
    else if (el.value !== "") keys[el.dataset.key] = el.value;    // replace
  }
  for (const el of document.querySelectorAll("#settings-body input[data-model]")) {
    models[el.dataset.model] = el.value;
  }
  const body = { keys, models };
  const finder = $("set-finder").value;
  if (finder !== settingsInitial.finder) body.finder_email = finder;
  const retention = Number($("set-retention").value);
  if (retention !== settingsInitial.sessionRetentionSeconds) body.session_retention_seconds = retention;

  $("settings-msg").textContent = "Saving...";
  try {
    const res = await fetch("/api/settings", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Celina-CSRF": csrfToken(),
      },
      body: JSON.stringify(body),
    }).then((r) => r.json());
    if (res.error) { $("settings-msg").textContent = res.error; return; }
    await refreshConfig();   // provider readiness updates immediately
    await loadSettingsMeta();
    closeSettings();
  } catch (e) {
    $("settings-msg").textContent = "Could not save: " + e.message;
  }
}

function closeSettings() {
  $("settings").hidden = true;
  $("settings-body").innerHTML = "";
  releaseFocus();
}

// ---------- guide / walkthrough ----------

const TOUR_STEPS = [
  {
    title: "Ask a clear question",
    body: "Start with a question in the main field. Celina breaks it into searches and brings back sources you can inspect.",
  },
  {
    title: "Inspect what came back",
    body: "Read the answer, open the cited sources, and watch the trace when you want to see what Celina is doing.",
  },
  {
    title: "Keep useful work",
    body: "When something is worth building on, choose Keep this. Your note stays in the local Library on this machine.",
  },
];
let tourIndex = 0;

function wireTour() {
  $("guide-open").addEventListener("click", () => openTour());
  $("guide-open-inline").addEventListener("click", () => openTour());
  $("tour-next").addEventListener("click", nextTourStep);
  $("tour-back").addEventListener("click", previousTourStep);
  $("tour-skip").addEventListener("click", closeTour);
  $("tour").addEventListener("click", (e) => {
    if (e.target.id === "tour") closeTour();
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !$("tour").hidden) closeTour();
  });
}

function openTour(start = 0) {
  tourIndex = Math.max(0, Math.min(start, TOUR_STEPS.length - 1));
  renderTour();
  $("tour").hidden = false;
  trapFocus($("tour"));
}

function renderTour() {
  const step = TOUR_STEPS[tourIndex];
  $("tour-kicker").textContent = `${String(tourIndex + 1).padStart(2, "0")} / ${String(TOUR_STEPS.length).padStart(2, "0")}`;
  $("tour-title").textContent = step.title;
  $("tour-body").textContent = step.body;
  $("tour-back").disabled = tourIndex === 0;
  $("tour-next").textContent = tourIndex === TOUR_STEPS.length - 1 ? "Finish" : "Next";
  $("tour-dots").replaceChildren(...TOUR_STEPS.map((_, i) => {
    const dot = document.createElement("span");
    dot.className = `tour-dot${i === tourIndex ? " is-active" : ""}`;
    return dot;
  }));
}

function nextTourStep() {
  if (tourIndex === TOUR_STEPS.length - 1) return closeTour();
  tourIndex += 1;
  renderTour();
  $("tour-next").focus();
}

function previousTourStep() {
  if (tourIndex === 0) return;
  tourIndex -= 1;
  renderTour();
  $("tour-back").focus();
}

function closeTour() {
  $("tour").hidden = true;
  localStorage.setItem("celina-tour-seen", "1");
  releaseFocus();
}

// ---------- navigation ----------

function wireNav() {
  document.querySelectorAll(".navbtn").forEach((btn) => {
    btn.onclick = () => nav(btn.dataset.view);
  });
}

function nav(view) {
  state.view = view;
  document.querySelectorAll(".navbtn").forEach((b) =>
    b.classList.toggle("is-active", b.dataset.view === view));
  const map = { work: "s-work", library: "s-library", notebook: "s-notebook" };
  Object.entries(map).forEach(([v, id]) => { $(id).hidden = v !== view; });
  if (view === "library") { loadFiles(); loadProjects(); }
  if (view === "notebook") {
    loadNotebooks();
    const head = document.querySelector(".asst-head span");
    if (head) head.textContent = "Ask about this notebook";
    $("input").placeholder = "Ask about the sources and notes";
    renderNotebook();
  } else {
    const head = document.querySelector(".asst-head span");
    if (head) head.textContent = "Ask about this";
    $("input").placeholder = "Ask about what you’re reading";
  }
}

// ---------- source (what Studio + Assistant work from) ----------

function briefPlainText(d) {
  const lines = [d.answer || ""];
  (d.results || []).forEach((r, i) => lines.push(`[${i + 1}] ${r.title || ""}`));
  return lines.join("\n");
}

function currentSource() {
  if (state.viewing) return { label: state.viewing.title, text: state.viewing.text };
  if (state.results) return { label: "search: " + (state.results.query || ""), text: briefPlainText(state.results) };
  return null;
}

function contextText() {
  if (state.view === "notebook" && state.activeNotebook) return notebookContextText();
  return currentSource()?.text || "";
}

// ---------- notebook (source-grounded learning workspace) ----------

function notebookHeaders() {
  return {
    "content-type": "application/json",
    "X-Celina-CSRF": csrfToken(),
    "Origin": window.location.origin,
  };
}

async function loadNotebooks() {
  try {
    const data = await fetch("/api/notebooks").then((r) => r.json());
    if (data.error) throw new Error(data.error);
    state.notebooks = data.notebooks || [];
    state.selectedSearchNotebookId = searchCapture().resolveSelectedNotebookId
      ? searchCapture().resolveSelectedNotebookId(
        state.notebooks,
        state.selectedSearchNotebookId,
        state.activeNotebook?.id || "",
      )
      : (state.selectedSearchNotebookId || state.activeNotebook?.id || state.notebooks[0]?.id || "");
    if (state.activeNotebook && state.notebooks.some((n) => n.id === state.activeNotebook.id)) {
      await selectNotebook(state.activeNotebook.id, false);
    } else if (state.notebooks.length) {
      await selectNotebook(state.notebooks[0].id, false);
    } else {
      state.activeNotebook = null;
      state.activeNotebookSourceId = null;
      renderNotebook();
    }
    if (state.results && state.view === "work") renderResults(state.results);
  } catch (err) {
    setEngine("Could not load notebooks: " + err.message);
  }
}

async function selectNotebook(id, announce = true) {
  if (!id) return;
  try {
    const data = await fetch(`/api/notebooks/${encodeURIComponent(id)}`).then((r) => r.json());
    if (data.error) throw new Error(data.error);
    state.activeNotebook = data.notebook;
    state.selectedSearchNotebookId = data.notebook.id;
    const sources = state.activeNotebook.sources || [];
    if (!sources.some((source) => source.id === state.activeNotebookSourceId)) {
      state.activeNotebookSourceId = sources[0]?.id || null;
    }
    renderNotebook();
    if (announce) setEngine(`Notebook: ${state.activeNotebook.title}`);
  } catch (err) {
    setEngine("Could not open notebook: " + err.message);
  }
}

function renderNotebook() {
  const notebook = state.activeNotebook;
  const empty = !notebook;
  $("notebook-empty").hidden = !empty;
  $("notebook-evidence").hidden = empty || !(notebook.sources || []).length;
  $("notebook-notes").hidden = empty;
  $("notebook-path-form").hidden = empty;
  $("source-new").hidden = empty;
  $("source-import-new").hidden = empty;
  $("notebook-source-form").hidden = true;
  $("notebook-import-form").hidden = true;
  $("notebook-note-form").hidden = true;
  $("notebook-path-empty").hidden = empty || Boolean(notebook.learning_path?.sections?.length);
  $("notebook-title").textContent = notebook?.title || "Choose a notebook";
  $("notebook-goal").textContent = notebook?.goal || "Bring a question, a paper, or a subject you want to understand.";

  const select = $("notebook-select");
  select.replaceChildren();
  if (!state.notebooks.length) {
    const option = document.createElement("option");
    option.textContent = "No notebooks yet";
    option.disabled = true;
    select.appendChild(option);
  } else {
    state.notebooks.forEach((item) => {
      const option = document.createElement("option");
      option.value = item.id;
      option.textContent = item.title;
      option.selected = item.id === notebook?.id;
      select.appendChild(option);
    });
  }

  const sources = notebook?.sources || [];
  $("notebook-source-count").textContent = String(sources.length).padStart(2, "0");
  $("notebook-sources-empty").hidden = !notebook || sources.length > 0;
  const sourceList = $("notebook-source-list");
  sourceList.replaceChildren(...sources.map((source) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `notebook-source${source.id === state.activeNotebookSourceId ? " is-active" : ""}`;
    const title = document.createElement("span");
    title.className = "notebook-source-title";
    title.textContent = source.title;
    const meta = document.createElement("span");
    meta.className = "notebook-source-meta";
    meta.textContent = [
      source.kind,
      source.origin === "import" ? "imported" : null,
      source.url ? "linked source" : "local excerpt",
    ].filter(Boolean).join(" · ");
    button.append(title, meta);
    button.onclick = () => { state.activeNotebookSourceId = source.id; renderNotebook(); };
    return button;
  }));

  const active = sources.find((source) => source.id === state.activeNotebookSourceId);
  if (active) {
    $("notebook-evidence").hidden = false;
    $("notebook-evidence-title").textContent = active.title;
    $("notebook-evidence-meta").textContent = [
      active.kind,
      active.origin === "import" ? "imported source" : null,
      active.url ? "linked source" : "local excerpt",
    ].filter(Boolean).join(" · ");
    $("notebook-evidence-excerpt").textContent = active.excerpt || "";
    const link = $("notebook-evidence-link");
    link.hidden = !active.url;
    if (active.url) link.href = active.url;
    const citations = $("notebook-evidence-citations");
    const items = (active.citations || []).map((citation) => {
      const article = document.createElement("article");
      article.className = "notebook-citation";
      const label = document.createElement("span");
      label.className = "notebook-citation-label";
      label.textContent = citation.label || "document";
      const text = document.createElement("p");
      text.className = "notebook-citation-text";
      text.textContent = citation.text || "";
      article.append(label, text);
      return article;
    });
    citations.hidden = items.length === 0;
    citations.replaceChildren(...items);
  }

  const noteList = $("notebook-note-list");
  noteList.replaceChildren(...(notebook?.notes || []).map((note) => {
    const article = document.createElement("article");
    article.className = "notebook-note";
    const title = document.createElement("h4");
    title.textContent = note.title;
    const body = document.createElement("p");
    body.textContent = note.body;
    const meta = document.createElement("span");
    meta.className = "notebook-note-meta";
    meta.textContent = note.source_ids?.length ? `grounded in ${note.source_ids.length} source${note.source_ids.length === 1 ? "" : "s"}` : "working note";
    article.append(title, body, meta);
    return article;
  }));

  const path = notebook?.learning_path;
  const pathWrap = $("notebook-path");
  pathWrap.replaceChildren(...(path?.sections || []).map((section) => {
    const article = document.createElement("article");
    article.className = "notebook-path-section";
    const heading = document.createElement("h4");
    heading.textContent = section.title;
    const list = document.createElement("ol");
    (section.items || []).forEach((item) => {
      const li = document.createElement("li");
      li.textContent = item.text;
      list.appendChild(li);
    });
    article.append(heading, list);
    return article;
  }));
  if (path) {
    $("path-depth").value = path.depth || "college";
    $("path-goal").value = path.goal || "";
  }
}

function showNotebookCreate(prefill = null) {
  $("notebook-create").hidden = false;
  if (prefill) {
    $("notebook-name").value = prefill.title || "";
    $("notebook-goal-input").value = prefill.goal || "";
  }
  $("notebook-name").focus();
}

function hideNotebookCreate() {
  $("notebook-create").hidden = true;
  $("notebook-name").value = "";
  $("notebook-goal-input").value = "";
}

async function createNotebook() {
  const title = $("notebook-name").value.trim();
  const goal = $("notebook-goal-input").value.trim();
  if (!title) return $("notebook-name").focus();
  const data = await fetch("/api/notebooks", {
    method: "POST", headers: notebookHeaders(), body: JSON.stringify({ title, goal }),
  }).then((r) => r.json());
  if (data.error) return setEngine("Could not create notebook: " + data.error);
  hideNotebookCreate();
  state.notebooks = [data.notebook, ...state.notebooks.filter((n) => n.id !== data.notebook.id)];
  await selectNotebook(data.notebook.id);
  if (state.results && state.view === "work") renderResults(state.results);
  notifyWhenReady("Notebook ready", "Add a source, then build a path through it.");
}

function openSearchNotebookCreate(query) {
  const draft = searchCapture().prefillNotebookDraft
    ? searchCapture().prefillNotebookDraft(query)
    : { title: query || "", goal: query || "" };
  nav("notebook");
  showNotebookCreate(draft);
  setEngine("Create a notebook to capture this search");
}

function toggleNotebookForm(id, show) {
  $(id).hidden = !show;
  if (show) $(id).querySelector("input, textarea")?.focus();
}

async function addNotebookSource(e) {
  e.preventDefault();
  if (!state.activeNotebook) return;
  const payload = {
    title: $("source-title").value.trim(), url: $("source-url").value.trim(),
    excerpt: $("source-excerpt").value.trim(), kind: $("source-kind").value.trim(),
  };
  const data = await fetch(`/api/notebooks/${encodeURIComponent(state.activeNotebook.id)}/sources`, {
    method: "POST", headers: notebookHeaders(), body: JSON.stringify(payload),
  }).then((r) => r.json());
  if (data.error) return setEngine("Could not add source: " + data.error);
  $("notebook-source-form").reset();
  toggleNotebookForm("notebook-source-form", false);
  await selectNotebook(state.activeNotebook.id);
  state.activeNotebookSourceId = data.source.id;
  renderNotebook();
}

async function importNotebookSource(e) {
  e.preventDefault();
  if (!state.activeNotebook) return;
  const status = $("notebook-import-status");
  const submit = $("import-submit");
  const payload = {
    url: $("import-url").value.trim(),
    title: $("import-title").value.trim(),
    kind: $("import-kind").value.trim(),
  };
  status.textContent = "Importing…";
  submit.disabled = true;
  try {
    const data = await fetch(`/api/notebooks/${encodeURIComponent(state.activeNotebook.id)}/sources/import`, {
      method: "POST", headers: notebookHeaders(), body: JSON.stringify(payload),
    }).then((r) => r.json());
    if (data.error) {
      status.textContent = data.error;
      return setEngine("Could not import source: " + data.error);
    }
    $("notebook-import-form").reset();
    status.textContent = "";
    toggleNotebookForm("notebook-import-form", false);
    await selectNotebook(state.activeNotebook.id, false);
    state.activeNotebookSourceId = data.source.id;
    renderNotebook();
    setEngine(`Imported to notebook: ${data.source.title}`);
    notifyWhenReady("Source imported", "The page or PDF is ready in your notebook.");
  } catch (err) {
    status.textContent = err.message;
    setEngine("Could not import source: " + err.message);
  } finally {
    submit.disabled = false;
  }
}

async function addNotebookNote(e) {
  e.preventDefault();
  if (!state.activeNotebook) return;
  const payload = {
    title: $("note-title").value.trim(), body: $("note-body").value.trim(),
    source_ids: state.activeNotebookSourceId ? [state.activeNotebookSourceId] : [],
  };
  const data = await fetch(`/api/notebooks/${encodeURIComponent(state.activeNotebook.id)}/notes`, {
    method: "POST", headers: notebookHeaders(), body: JSON.stringify(payload),
  }).then((r) => r.json());
  if (data.error) return setEngine("Could not keep note: " + data.error);
  $("notebook-note-form").reset();
  toggleNotebookForm("notebook-note-form", false);
  await selectNotebook(state.activeNotebook.id);
}

async function generateNotebookPath(e) {
  e.preventDefault();
  if (!state.activeNotebook) return;
  const data = await fetch(`/api/notebooks/${encodeURIComponent(state.activeNotebook.id)}/learning-path`, {
    method: "POST", headers: notebookHeaders(), body: JSON.stringify({ depth: $("path-depth").value, goal: $("path-goal").value.trim() }),
  }).then((r) => r.json());
  if (data.error) return setEngine("Could not build path: " + data.error);
  state.activeNotebook.learning_path = data.learning_path;
  renderNotebook();
  setEngine("Learning path ready");
}

function notebookContextText() {
  const notebook = state.activeNotebook;
  if (!notebook) return "";
  const chunks = [`Notebook: ${notebook.title}`, `Learning goal: ${notebook.goal || "not specified"}`];
  (notebook.sources || []).forEach((source, i) => {
    const lines = [`Source ${i + 1}: ${source.title}`];
    if (source.excerpt) lines.push(`Excerpt:\n${(source.excerpt || "").slice(0, 5000)}`);
    const citations = (source.citations || []).slice(0, 6).map((citation) =>
      `${citation.label || "document"}: ${(citation.text || "").slice(0, 600)}`);
    if (citations.length) lines.push(`Citations:\n${citations.join("\n")}`);
    chunks.push(lines.join("\n"));
  });
  (notebook.notes || []).forEach((note, i) => {
    chunks.push(`Note ${i + 1}: ${note.title}\n${(note.body || "").slice(0, 5000)}`);
  });
  (notebook.learning_path?.sections || []).forEach((section) => {
    chunks.push(`${section.title}:\n${(section.items || []).map((item) => item.text).join("\n")}`);
  });
  return chunks.join("\n\n").slice(0, 40000);
}

// ---------- workspace / library ----------

async function loadFiles() {
  const { files } = await fetch("/api/workspace").then((r) => r.json());
  const ul = $("files");
  ul.innerHTML = "";
  $("ws-empty").style.display = files.length ? "none" : "block";
  for (const f of files) {
    const li = document.createElement("li");
    li.innerHTML = `<span class="name">${escapeHtml(f.name)}</span><span class="meta">${(f.size / 1024).toFixed(1)} KB</span>`;
    if (f.path === state.activeFile) li.classList.add("active");
    li.tabIndex = 0;
    li.setAttribute("role", "button");
    const open = () => openArtifact(f);
    li.onclick = open;
    li.onkeydown = (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); open(); } };
    ul.appendChild(li);
  }
}

async function loadProjects() {
  const data = await fetch("/api/projects").then((r) => r.json());
  if (data.error) throw new Error(data.error);
  state.projects = data.projects || [];
  const formats = data.formats || [];
  const formatSelect = $("output-format");
  const projectSelect = $("project-select");
  const currentProject = state.projects.find((p) => p.id === state.projectId);
  if (!currentProject) state.projectId = state.projects[0]?.id || null;
  if (!formats.some((format) => format.id === state.outputFormat)) {
    state.outputFormat = formats[0]?.id || "markdown";
  }
  formatSelect.replaceChildren(...formats.map((format) => {
    const option = document.createElement("option");
    option.value = format.id;
    option.textContent = format.label;
    option.selected = format.id === state.outputFormat;
    return option;
  }));
  projectSelect.replaceChildren(...state.projects.map((project) => {
    const option = document.createElement("option");
    option.value = project.id;
    option.textContent = project.name;
    option.selected = project.id === state.projectId;
    return option;
  }));
  renderProjects();
}

function renderProjects() {
  const list = $("projects");
  list.replaceChildren();
  $("projects-empty").style.display = state.projects.length ? "none" : "block";
  state.projects.forEach((project) => {
    const card = document.createElement("li");
    card.className = `project-card${project.id === state.projectId ? " is-active" : ""}`;
    const head = document.createElement("div");
    head.className = "project-card-head";
    head.innerHTML = `<span class="project-card-name">${escapeHtml(project.name)}</span>`
      + `<span class="project-card-meta">${project.outputs.length} output${project.outputs.length === 1 ? "" : "s"}</span>`;
    card.appendChild(head);
    const outputs = document.createElement("ul");
    outputs.className = "project-outputs";
    if (!project.outputs.length) {
      const empty = document.createElement("li");
      empty.className = "project-empty";
      empty.textContent = "No outputs yet. Keep a result here.";
      outputs.appendChild(empty);
    } else {
      project.outputs.forEach((output) => {
        const item = document.createElement("li");
        const button = document.createElement("button");
        button.className = "project-output";
        button.type = "button";
        button.title = `Open ${output.format_label} output`;
        button.innerHTML = `<span class="project-output-name">${escapeHtml(output.name)}</span>`
          + `<span class="project-output-format">${escapeHtml(output.format_label)}</span>`;
        button.onclick = () => openProjectOutput(project.id, output);
        item.appendChild(button);
        outputs.appendChild(item);
      });
    }
    card.appendChild(outputs);
    list.appendChild(card);
  });
}

async function openProjectOutput(projectId, output) {
  const data = await fetch(`/api/projects/${encodeURIComponent(projectId)}/outputs/${encodeURIComponent(output.name)}`).then((r) => r.json());
  if (data.error) return setEngine("could not open: " + data.error);
  state.activeFile = `projects/${projectId}/outputs/${output.name}`;
  state.viewing = { title: output.name, text: data.content };
  state.results = null;
  $("url").value = "";
  if (output.format === "html") {
    const frame = document.createElement("iframe");
    frame.setAttribute("sandbox", "");
    frame.srcdoc = data.content;
    $("view").replaceChildren(frame);
  } else {
    showText(data.content);
  }
  $("save").disabled = true;
  setEngine(`Project output · ${output.name}`);
  nav("work");
}

function showProjectCreate() {
  $("project-create").hidden = false;
  $("project-name").value = "";
  $("project-name").focus();
}

function hideProjectCreate() {
  $("project-create").hidden = true;
}

async function createProject() {
  const name = $("project-name").value.trim();
  if (!name) return $("project-name").focus();
  const res = await fetch("/api/projects", {
    method: "POST",
    headers: {
      "content-type": "application/json",
      "X-Celina-CSRF": csrfToken(),
      "Origin": window.location.origin,
    },
    body: JSON.stringify({ name }),
  }).then((r) => r.json());
  if (res.error) return setEngine("Could not create project: " + res.error);
  state.projectId = res.id;
  hideProjectCreate();
  await loadProjects();
  setEngine(`Project ready · ${res.name}`);
}

async function openArtifact(file) {
  const data = await fetch("/api/workspace/file?path=" + encodeURIComponent(file.path)).then((r) => r.json());
  if (data.error) return setEngine("could not open: " + data.error);
  state.activeFile = file.path;
  state.viewing = { title: file.name, text: data.content };
  state.results = null;
  $("url").value = "";
  setEngine(`Kept · ${file.name}`);
  if (file.kind === "html") {
    const frame = document.createElement("iframe");
    frame.setAttribute("sandbox", "");
    frame.srcdoc = data.content;
    $("view").replaceChildren(frame);
  } else {
    showText(data.content);
  }
  $("save").disabled = true;
  nav("work");
}

// ---------- reading ----------

function showText(text) {
  const pre = document.createElement("pre");
  pre.textContent = text;
  $("view").replaceChildren(pre);
}
function setEngine(msg) { $("engine").textContent = msg || ""; announce(msg); }
// A live search run fires many trace events (one per source read, etc.) -
// announcing every one would bury a screen-reader user in chatter. #engine
// updates visually on each event; this aria-live region only speaks at
// meaningful checkpoints (see watchRun).
function announce(msg) { $("engine-announce").textContent = msg || ""; }

// ---------- companion state + quick panel ----------

function setMascotState(kind) {
  const mascot = $("mascot");
  if (mascot) mascot.dataset.state = kind;
}

function noticeTime(date) {
  return date.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

function renderMascotPanel() {
  const list = $("mascot-notices");
  if (!list) return;
  list.replaceChildren();
  if (!state.mascot.notices.length) {
    const empty = document.createElement("li");
    empty.className = "mascot-notice-body";
    empty.textContent = "No new notices.";
    list.appendChild(empty);
  } else {
    state.mascot.notices.forEach((notice) => {
      const item = document.createElement("li");
      item.innerHTML = `<span class="mascot-notice-title">${escapeHtml(notice.title)}</span>`
        + `<span class="mascot-notice-body">${escapeHtml(notice.body)}</span>`
        + `<span class="mascot-notice-time">${noticeTime(notice.at)}</span>`;
      list.appendChild(item);
    });
  }
  const bell = $("mascot-notify");
  if (state.mascot.unread) bell.dataset.unread = String(state.mascot.unread);
  else delete bell.dataset.unread;
  $("mascot-panel-summary").textContent = state.mascot.unread
    ? `${state.mascot.unread} new notice${state.mascot.unread === 1 ? "" : "s"}`
    : "Quiet here.";
  const enable = $("mascot-enable-notify");
  if (!("Notification" in window)) {
    enable.disabled = true;
    enable.textContent = "Notifications unavailable";
  } else if (Notification.permission === "granted") {
    enable.disabled = false;
    enable.textContent = "Notifications on";
  } else if (Notification.permission === "denied") {
    enable.disabled = true;
    enable.textContent = "Notifications blocked";
  } else {
    enable.disabled = false;
    enable.textContent = "Enable notifications";
  }
}

function addMascotNotice(title, body, kind = "active") {
  state.mascot.notices.unshift({ title, body, at: new Date() });
  state.mascot.notices = state.mascot.notices.slice(0, 5);
  state.mascot.unread = state.mascot.panelOpen ? 0 : state.mascot.unread + 1;
  setMascotState(kind);
  renderMascotPanel();
}

function openMascotPanel() {
  state.mascot.panelOpen = true;
  state.mascot.unread = 0;
  $("mascot-panel").hidden = false;
  $("mascot").classList.add("is-panel-open");
  $("mascot-notify").setAttribute("aria-expanded", "true");
  renderMascotPanel();
  setMascotState("resting");
}

function closeMascotPanel() {
  state.mascot.panelOpen = false;
  $("mascot-panel").hidden = true;
  $("mascot").classList.remove("is-panel-open");
  $("mascot-notify").setAttribute("aria-expanded", "false");
  renderMascotPanel();
}

async function openUrl() {
  const url = $("url").value.trim();
  if (!url) return;
  setMascotState("resting");
  setEngine("fetching…");
  $("go").disabled = true;
  try {
    const data = await fetch("/api/fetch", {
      method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ url }),
    }).then((r) => r.json());
    if (data.error) {
      setEngine("failed: " + data.error);
      addMascotNotice("Reading needs attention", data.error, "attention");
      return;
    }
    state.viewing = { title: data.url, text: data.text };
    state.activeFile = null;
    state.results = null;
    showText(data.text);
    setEngine("Read privately" + (data.note ? " · " + data.note : ""));
    $("save").disabled = false;
    notifyWhenReady("Reading ready", "Celina has the page open.");
  } catch (e) {
    setEngine("failed: " + e.message);
    addMascotNotice("Reading needs attention", e.message, "attention");
  } finally {
    $("go").disabled = false;
  }
}

// ---------- search (bounded, observable search run over SSE) ----------

async function ensureSession() {
  if (state.sessionId) return state.sessionId;
  const res = await fetch("/api/sessions", {
    method: "POST",
    headers: { "content-type": "application/json", "X-Celina-CSRF": csrfToken() },
    body: JSON.stringify({ content_recording: !state.incognito, incognito: state.incognito }),
  }).then((r) => r.json());
  if (res.error) throw new Error(res.error);
  state.sessionId = res.session_id;
  updatePrivacyUi();
  return state.sessionId;
}

async function deleteCurrentSession() {
  const sessionId = state.sessionId;
  if (!sessionId) return true;
  try {
    const res = await fetch(`/api/sessions/${encodeURIComponent(sessionId)}`, {
      method: "DELETE",
      headers: { "X-Celina-CSRF": csrfToken(), "Origin": window.location.origin },
    }).then((r) => r.json());
    if (res.error) throw new Error(res.error);
    state.sessionId = null;
    updatePrivacyUi();
    return true;
  } catch (err) {
    setEngine("Could not delete session: " + err.message);
    return false;
  }
}

async function setIncognitoMode(e) {
  const requested = e.target.checked;
  if (state.activeRunId) {
    e.target.checked = state.incognito;
    setEngine("Finish or stop the current search before changing privacy mode");
    return;
  }
  if (state.sessionId && !(await deleteCurrentSession())) {
    e.target.checked = state.incognito;
    return;
  }
  state.incognito = requested;
  setEngine(requested ? "Incognito on · session auto-deletes" : `Incognito off · ${sessionBadgeText()}`);
  updatePrivacyUi();
}

async function startSearchRun(query, provider) {
  const sessionId = await ensureSession();
  const res = await fetch("/api/search-runs", {
    method: "POST",
    headers: { "content-type": "application/json", "X-Celina-CSRF": csrfToken() },
    body: JSON.stringify({ session_id: sessionId, query, provider }),
  }).then((r) => r.json());
  if (res.error) throw new Error(res.error);
  return res;
}

function resetResearchLoop() {
  $("research-loop").hidden = true;
  $("research-loop-count").textContent = "Preparing focused questions";
  $("research-loop-questions").replaceChildren();
}

function renderResearchLoop(queries, currentQuery = "") {
  const list = $("research-loop-questions");
  list.replaceChildren(...queries.map((query) => {
    const item = document.createElement("li");
    item.textContent = query;
    if (query === currentQuery) item.classList.add("is-current");
    return item;
  }));
  $("research-loop-count").textContent = `${queries.length} question${queries.length === 1 ? "" : "s"} in this pass`;
  $("research-loop").hidden = false;
}

function markResearchQuestion(query, done = false) {
  document.querySelectorAll("#research-loop-questions li").forEach((item) => {
    const matches = item.textContent === query;
    item.classList.toggle("is-current", matches && !done);
    if (matches && done) item.classList.add("is-done");
  });
}

async function findPapers() {
  const q = $("url").value.trim();
  if (!q) return;
  if (looksLikeUrl(q)) return openUrl();
  if (state.activeRunId) return;   // one bounded run at a time
  setMascotState("resting");
  resetResearchLoop();
  setEngine("Finding real sources…");
  $("find").disabled = true;
  $("stop").hidden = false;
  try {
    const started = await startSearchRun(q, state.provider);
    state.activeRunId = started.run_id;
    watchRun(started.run_id, started.events_url, q);
  } catch (e) {
    setEngine("search failed: " + e.message);
    addMascotNotice("Search needs attention", e.message, "attention");
    $("find").disabled = false;
    $("stop").hidden = true;
  }
}

// Live trace: each SSE frame is one observable step ("Reading “X”.",
// "Verified support for…") - shown as the current status line while it runs.
// #engine gets every one of those (sighted users watch the detail scroll
// by); the aria-live region only speaks once per phase change, so a
// screen-reader user hears "reading" / "synthesizing" / "done", not a
// blow-by-blow of every source.
function watchRun(runId, eventsUrl, query) {
  if (state.eventSource) state.eventSource.close();
  const source = new EventSource(eventsUrl);
  state.eventSource = source;
  let announcedPhase = null;
  source.addEventListener("trace", (e) => {
    let payload;
    try { payload = JSON.parse(e.data); } catch { return; }
    $("engine").textContent = payload.summary || "";
    if (payload.kind === "plan.completed") {
      const queries = payload.details?.queries || [];
      if (queries.length) renderResearchLoop(queries);
    }
    if (payload.kind === "query.started") {
      const query = payload.details?.query || "";
      if (query) markResearchQuestion(query);
    }
    if (payload.kind === "query.completed" || payload.kind === "query.failed") {
      const query = payload.details?.query || "";
      if (query) markResearchQuestion(query, true);
    }
    if (payload.phase && payload.phase !== announcedPhase) {
      announcedPhase = payload.phase;
      announce(payload.summary || "");
    }
    if (TERMINAL_RUN_KINDS.has(payload.kind)) finishRun(runId, query);
  });
}

async function stopActiveRun() {
  if (!state.activeRunId) return;
  try {
    await fetch(`/api/search-runs/${state.activeRunId}/stop`, {
      method: "POST",
      headers: { "content-type": "application/json", "X-Celina-CSRF": csrfToken() },
      body: "{}",
    });
  } catch { /* the trace stream still delivers the terminal event */ }
}

async function finishRun(runId, query) {
  if (state.eventSource) { state.eventSource.close(); state.eventSource = null; }
  state.activeRunId = null;
  $("find").disabled = false;
  $("stop").hidden = true;
  try {
    const run = await fetch(`/api/search-runs/${runId}`).then((r) => r.json());
    renderRun(run, query);
  } catch (e) {
    setEngine("search failed: " + e.message);
    addMascotNotice("Search needs attention", e.message, "attention");
  }
}

// Adapt a serialized search run onto the shape renderResults already knows.
function renderRun(run, query) {
  const data = {
    query: run.query || query,
    provider: state.provider,
    model: "",
    results: (run.candidates || []).map((c) => ({
      title: c.title,
      url: c.url,
      oa_url: c.open_access ? c.url : null,
      kind: c.source_kind,
      authors: c.authors,
      year: (c.published_at || "").slice(0, 4) || null,
      snippet: c.snippet,
      abstract: c.snippet,
    })),
  };
  if (run.answer) data.answer = run.answer.answer;
  if (run.state !== "completed") {
    data.answer_error = run.state === "stopped"
      ? "the search was stopped" : "the search failed";
  }
  renderResults(data);
  const n = data.results.length;
  setEngine(`${n} source${n === 1 ? "" : "s"} found`);
  notifyWhenReady(`${n} source${n === 1 ? "" : "s"} found`, "Celina finished looking.", run.state === "completed" ? "active" : "attention");
}

function renderSearchNotebookControls(data) {
  const bar = document.createElement("section");
  bar.className = "results-toolbar";

  const copy = document.createElement("div");
  copy.className = "results-toolbar-copy";
  copy.innerHTML = "<span class=\"eyebrow\">Notebook capture</span><p>Turn a search result into a bounded source you can study later.</p>";
  bar.appendChild(copy);

  const actions = document.createElement("div");
  actions.className = "results-toolbar-actions";
  if (!state.notebooks.length) {
    const create = document.createElement("button");
    create.type = "button";
    create.className = "btn btn--ghost";
    create.textContent = "Create notebook";
    create.onclick = () => openSearchNotebookCreate(data.query || "");
    actions.appendChild(create);
  } else {
    const label = document.createElement("label");
    label.className = "results-notebook-select";
    const span = document.createElement("span");
    span.textContent = "Capture into";
    const select = document.createElement("select");
    state.notebooks.forEach((notebook) => {
      const option = document.createElement("option");
      option.value = notebook.id;
      option.textContent = notebook.title;
      option.selected = notebook.id === state.selectedSearchNotebookId;
      select.appendChild(option);
    });
    select.onchange = () => {
      state.selectedSearchNotebookId = select.value;
      if (select.value && state.activeNotebook?.id !== select.value) selectNotebook(select.value, false);
    };
    label.append(span, select);
    actions.appendChild(label);
  }
  bar.appendChild(actions);
  return bar;
}

async function addSearchResultToNotebook(result) {
  if (!state.notebooks.length || !state.selectedSearchNotebookId) {
    openSearchNotebookCreate(state.results?.query || result.title || "");
    return;
  }
  let payload;
  try {
    payload = searchCapture().buildSearchCapturePayload(result);
  } catch (err) {
    setEngine("Could not add source: " + err.message);
    return;
  }
  const data = await fetch(`/api/notebooks/${encodeURIComponent(state.selectedSearchNotebookId)}/sources`, {
    method: "POST",
    headers: notebookHeaders(),
    body: JSON.stringify(payload),
  }).then((r) => r.json());
  if (data.error) return setEngine("Could not add source: " + data.error);
  await loadNotebooks();
  await selectNotebook(state.selectedSearchNotebookId, false);
  state.activeNotebookSourceId = data.source.id;
  state.results.added_capture_keys[searchCapture().resultCaptureKey(result)] = true;
  renderNotebook();
  renderResults(state.results);
  setEngine(`Added to notebook: ${state.activeNotebook?.title || state.selectedSearchNotebookId}`);
}

function renderResults(data) {
  state.viewing = null;
  state.activeFile = null;
  state.results = data;
  state.results.added_capture_keys = state.results.added_capture_keys || {};
  $("save").disabled = false;

  const wrap = document.createElement("div");
  wrap.className = "results";
  wrap.appendChild(renderSearchNotebookControls(data));

  const note = document.createElement("div");
  if (data.answer) {
    note.className = "answer";
    note.innerHTML = `<div class="answer-head">Answer<span class="meta">${escapeHtml((data.provider || "") + " " + (data.model || ""))}</span></div>`;
    const body = document.createElement("div");
    body.className = "answer-body";
    body.textContent = data.answer;
    note.appendChild(body);
  } else if (data.answer_error) {
    note.className = "answer note";
    note.textContent = "Could not write an answer: " + data.answer_error + " — the sources below still stand.";
  } else {
    note.className = "answer note";
    note.textContent = "Connect an AI in Settings for a written answer. The sources below are real regardless.";
  }
  wrap.appendChild(note);

  const KIND = { research: "Research", web: "Web", news: "Recent", wikipedia: "Wikipedia" };
  data.results.forEach((r, i) => {
    const el = document.createElement("div");
    el.className = "paper";
    const authors = r.authors || [];
    const who = authors.slice(0, 3).join(", ") + (authors.length > 3 ? " et al." : "");
    const meta = [who, r.year, r.venue, r.cited_by != null ? `cited by ${r.cited_by}` : null, r.source].filter(Boolean).join(" · ");
    const tag = r.kind ? `<span class="kind kind--${r.kind}">${KIND[r.kind] || r.kind}</span>` : "";
    el.innerHTML = `<div class="paper-title">${tag}${escapeHtml(r.title || "untitled")}</div>` +
      (meta ? `<div class="paper-meta">${escapeHtml(meta)}</div>` : "");
    const actions = document.createElement("div");
    actions.className = "paper-actions";
    // Anything with a readable link gets a Read button (Obscura reads it).
    const readable = r.oa_url || r.url;
    if (readable) {
      const read = document.createElement("button");
      read.className = "btn btn--ghost";
      read.textContent = "Read";
      read.onclick = () => { $("url").value = readable; openUrl(); };
      actions.appendChild(read);
    }
    const add = document.createElement("button");
    add.className = "btn btn--ghost";
    const added = Boolean(state.results.added_capture_keys[searchCapture().resultCaptureKey(r)]);
    add.textContent = added ? "Added" : "Add to Notebook";
    add.disabled = added;
    add.onclick = () => { addSearchResultToNotebook(r); };
    actions.appendChild(add);
    const link = r.url || r.oa_url;
    if (link) {
      const a = document.createElement("a");
      a.href = link; a.target = "_blank"; a.rel = "noopener";
      a.className = "paper-link" + (r.oa_url ? " oa" : "");
      a.textContent = r.oa_url ? "open access ↗" : "open ↗";
      actions.appendChild(a);
    }
    el.appendChild(actions);
    if (r.abstract || r.snippet) {
      const ab = document.createElement("div");
      ab.className = "paper-abstract";
      ab.textContent = r.abstract || r.snippet;
      el.appendChild(ab);
    }
    wrap.appendChild(el);
  });
  $("view").replaceChildren(wrap);
}

// ---------- save (search / reader) ----------

function slugify(s) {
  return (s || "").replace(/^https?:\/\//, "").replace(/[^a-z0-9]+/gi, "-").slice(0, 60).replace(/^-|-$/g, "") || "artifact";
}

function briefMarkdown(d) {
  const out = [`# ${d.query || "research"}`, ""];
  out.push(`Saved ${new Date().toISOString()}` + (d.answer ? ` · ${(d.provider || "")} ${(d.model || "")}`.trimEnd() : ""), "");
  out.push("## Grounded answer", "", d.answer || "_(no grounded answer — the sources below are real regardless)_", "");
  out.push("## Sources", "");
  (d.results || []).forEach((r, i) => {
    const authors = (r.authors || []).slice(0, 5).join(", ") + ((r.authors || []).length > 5 ? " et al." : "");
    const meta = [authors, r.year, r.venue, r.cited_by != null ? `cited by ${r.cited_by}` : null, r.source].filter(Boolean).join(" · ");
    out.push(`${i + 1}. **${r.title || "untitled"}**`);
    if (meta) out.push(`   ${meta}`);
    const link = r.oa_url || r.url;
    if (link) out.push(`   ${r.oa_url ? "open access: " : ""}${link}`);
    if (r.abstract) { const a = r.abstract.replace(/\s+/g, " ").trim(); out.push(`   > ${a.slice(0, 300)}${a.length > 300 ? "…" : ""}`); }
    out.push("");
  });
  if (d.notes && d.notes.length) out.push("---", "", `_notes: ${d.notes.join(" · ")}_`);
  return out.join("\n");
}

function briefHtml(d, title) {
  const sources = (d.results || []).map((r) => {
    const link = r.oa_url || r.url;
    return `<li><strong>${escapeHtml(r.title || "untitled")}</strong>`
      + (link ? ` · <a href="${escapeHtml(link)}">${escapeHtml(link)}</a>` : "")
      + (r.abstract ? `<p>${escapeHtml(r.abstract)}</p>` : "")
      + "</li>";
  }).join("");
  return `<!doctype html><meta charset="utf-8"><title>${escapeHtml(title)}</title>`
    + `<article><h1>${escapeHtml(title)}</h1><p>Saved ${new Date().toISOString()}</p>`
    + `<h2>Grounded answer</h2><p>${escapeHtml(d.answer || "No grounded answer.").replace(/\n/g, "<br>")}</p>`
    + `<h2>Sources</h2><ol>${sources}</ol></article>`;
}

function formatOutput(d, format, title) {
  if (format === "markdown") {
    if (d.results) return briefMarkdown(d);
    return `# ${title}\n\nSaved ${new Date().toISOString()}\n\n---\n\n${d.text || ""}`;
  }
  if (format === "html") {
    if (d.results) return briefHtml(d, title);
    return `<!doctype html><meta charset="utf-8"><title>${escapeHtml(title)}</title><article><h1>${escapeHtml(title)}</h1><pre>${escapeHtml(d.text || "")}</pre></article>`;
  }
  if (format === "json") {
    return JSON.stringify({ ...d, title, saved_at: new Date().toISOString() }, null, 2);
  }
  if (d.results) {
    return [d.answer || "No grounded answer.", "", ...(d.results || []).map((r, i) =>
      `[${i + 1}] ${r.title || "untitled"}${r.url ? `\n${r.url}` : ""}`)].join("\n");
  }
  return `${title}\n\n${d.text || ""}`;
}

async function saveCurrent() {
  if (!state.projectId) await loadProjects();
  if (!state.projectId) return setEngine("Create a project before saving");
  let title, source;
  if (state.viewing) {
    title = state.viewing.title;
    source = { title, text: state.viewing.text };
  } else if (state.results) {
    title = state.results.query || "research";
    source = state.results;
  } else { return; }
  const res = await fetch(`/api/projects/${encodeURIComponent(state.projectId)}/outputs`, {
    method: "POST",
    headers: {
      "content-type": "application/json",
      "X-Celina-CSRF": csrfToken(),
      "Origin": window.location.origin,
    },
    body: JSON.stringify({
      title: slugify(title),
      format: state.outputFormat,
      content: formatOutput(source, state.outputFormat, title),
    }),
  }).then((r) => r.json());
  if (res.error) {
    setEngine("Could not keep it: " + res.error);
    addMascotNotice("Could not save", res.error, "attention");
  } else {
    setEngine("Kept — find it in Library");
    notifyWhenReady("Saved to Library", "The note is ready in your Library.");
  }
  $("save").disabled = true;
  await loadProjects();
}

// ---------- assistant ----------

function addMessage(role, text) {
  const div = document.createElement("div");
  div.className = "msg " + role;
  const who = role === "user" ? "you" : role === "err" ? "error" : "assistant";
  div.innerHTML = `<span class="who">${who}</span>`;
  div.appendChild(document.createTextNode(text));
  $("log").appendChild(div);
  $("log").scrollTop = $("log").scrollHeight;
  return div;
}

async function send(e) {
  e.preventDefault();
  const text = $("input").value.trim();
  if (!text) return;
  $("input").value = "";
  addMessage("user", text);
  state.history.push({ role: "user", content: text });
  const pending = addMessage("bot", "thinking…");
  $("send").disabled = true;
  try {
    const res = await fetch("/api/chat", {
      method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ provider: state.provider, messages: state.history, context: contextText() }),
    }).then((r) => r.json());
    if (res.error) {
      pending.remove(); addMessage("err", res.error); state.history.pop();
      addMascotNotice("Assistant needs attention", res.error, "attention");
      return;
    }
    pending.remove();
    addMessage("bot", res.text);
    state.history.push({ role: "assistant", content: res.text });
    const u = res.usage || {};
    $("usage").textContent = `${res.provider} · ${res.model}` + (u.input_tokens ? ` · ${u.input_tokens} in / ${u.output_tokens} out` : "");
  } catch (err) {
    pending.remove(); addMessage("err", err.message); state.history.pop();
    addMascotNotice("Assistant needs attention", err.message, "attention");
  } finally {
    $("send").disabled = false;
  }
}

// ---------- companion tools ----------

async function enableNotifications() {
  if (!("Notification" in window)) {
    setEngine("Notifications are not available here");
    renderMascotPanel();
    return;
  }
  let permission = Notification.permission;
  if (permission === "default") permission = await Notification.requestPermission();
  setEngine(permission === "granted" ? "Notifications on" : "Notifications remain quiet");
  renderMascotPanel();
}

function notifyWhenReady(title, body, kind = "active") {
  addMascotNotice(title, body, kind);
  if ("Notification" in window && Notification.permission === "granted") {
    try { new Notification(title, { body }); } catch { /* in-app notice still works */ }
  }
}

// ---------- wiring ----------

$("find").onclick = findPapers;
$("stop").onclick = stopActiveRun;
$("go").onclick = openUrl;
$("url").addEventListener("keydown", (e) => { if (e.key === "Enter") findPapers(); });
$("save").onclick = saveCurrent;
$("incognito-toggle").onchange = setIncognitoMode;
$("session-delete").onclick = async () => {
  const ok = await deleteCurrentSession();
  if (ok) updatePrivacyUi();
};
$("example-q").onclick = () => { $("url").value = "does caffeine affect sleep?"; findPapers(); };
$("refresh").onclick = loadFiles;
$("project-select").onchange = (e) => { state.projectId = e.target.value; renderProjects(); };
$("output-format").onchange = (e) => { state.outputFormat = e.target.value; };
$("project-new").onclick = showProjectCreate;
$("project-create-cancel").onclick = hideProjectCreate;
$("project-create-save").onclick = createProject;
$("project-name").addEventListener("keydown", (e) => { if (e.key === "Enter") createProject(); });
$("notebook-select").onchange = (e) => selectNotebook(e.target.value);
$("notebook-new").onclick = showNotebookCreate;
$("notebook-empty-new").onclick = showNotebookCreate;
$("notebook-create-cancel").onclick = hideNotebookCreate;
if (typeof module !== "undefined" && module.exports) {
  module.exports = {
    state,
    retentionLabel,
    sessionBadgeText,
    sessionStateText,
    deleteCurrentSession,
    setIncognitoMode,
    updatePrivacyUi,
  };
} else {
  $("notebook-create-save").onclick = createNotebook;
  $("notebook-name").addEventListener("keydown", (e) => { if (e.key === "Enter") createNotebook(); });
  $("source-new").onclick = () => toggleNotebookForm("notebook-source-form", true);
  $("source-import-new").onclick = () => toggleNotebookForm("notebook-import-form", true);
  $("source-cancel").onclick = () => toggleNotebookForm("notebook-source-form", false);
  $("import-cancel").onclick = () => {
    $("notebook-import-status").textContent = "";
    toggleNotebookForm("notebook-import-form", false);
  };
  $("notebook-source-form").addEventListener("submit", addNotebookSource);
  $("notebook-import-form").addEventListener("submit", importNotebookSource);
  $("note-new").onclick = () => toggleNotebookForm("notebook-note-form", true);
  $("note-cancel").onclick = () => toggleNotebookForm("notebook-note-form", false);
  $("notebook-note-form").addEventListener("submit", addNotebookNote);
  $("notebook-path-form").addEventListener("submit", generateNotebookPath);
  $("composer").addEventListener("submit", send);
  $("clear").onclick = () => { state.history = []; $("log").innerHTML = ""; $("usage").textContent = ""; };
  $("input").addEventListener("keydown", (e) => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) $("composer").requestSubmit(); });
  $("mascot-notify").onclick = openMascotPanel;
  $("mascot-panel-close").onclick = closeMascotPanel;
  $("mascot-enable-notify").onclick = enableNotifications;
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && state.mascot.panelOpen) closeMascotPanel(); });
  document.addEventListener("click", (e) => {
    if (state.mascot.panelOpen && !$("mascot").contains(e.target)) closeMascotPanel();
  });
  window.addEventListener("pagehide", () => {
    if (!state.incognito || !state.sessionId) return;
    fetch(`/api/sessions/${encodeURIComponent(state.sessionId)}`, {
      method: "DELETE",
      headers: { "X-Celina-CSRF": csrfToken(), "Origin": window.location.origin },
      keepalive: true,
    });
  });
  renderMascotPanel();

  boot();
}
