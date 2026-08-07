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
  sessionId: null,      // local research session (created on first search)
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
  await loadFiles();
  wireNav();
  wireSettings();
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
      headers: { "Content-Type": "application/json" },
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

let settingsInitial = null;  // { finder }

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
  const data = await fetch("/api/settings").then((r) => r.json());
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
    </div>`;
  const toolsStatus = `
    <div class="set-row">
      <div class="set-label">Connected tools</div>
      <div class="set-tools">
        ${state.tools.map((t) => `<span class="set-tool${t.present ? " on" : ""}">${escapeHtml(t.label)} &middot; ${t.present ? "connected" : "not found"}</span>`).join("")}
      </div>
    </div>`;
  $("settings-body").innerHTML = whichAI + toolsStatus + rows + `
    <div class="set-row">
      <div class="set-label">Finder contact email</div>
      <input type="text" id="set-finder" placeholder="you@example.com"
             value="${escapeHtml(data.finder_email || "")}" />
    </div>`;
  const sp = $("set-provider");
  if (sp) sp.addEventListener("change", () => { state.provider = sp.value; state.providerManual = true; });
  settingsInitial = { finder: data.finder_email || "" };
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

  $("settings-msg").textContent = "Saving...";
  try {
    const res = await fetch("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then((r) => r.json());
    if (res.error) { $("settings-msg").textContent = res.error; return; }
    await refreshConfig();   // provider readiness updates immediately
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
  const map = { work: "s-work", library: "s-library" };
  Object.entries(map).forEach(([v, id]) => { $(id).hidden = v !== view; });
  if (view === "library") loadFiles();
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
  return currentSource()?.text || "";
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
    body: JSON.stringify({ content_recording: true }),
  }).then((r) => r.json());
  if (res.error) throw new Error(res.error);
  state.sessionId = res.session_id;
  return state.sessionId;
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

async function findPapers() {
  const q = $("url").value.trim();
  if (!q) return;
  if (looksLikeUrl(q)) return openUrl();
  if (state.activeRunId) return;   // one bounded run at a time
  setMascotState("resting");
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

function renderResults(data) {
  state.viewing = null;
  state.activeFile = null;
  state.results = data;
  $("save").disabled = false;

  const wrap = document.createElement("div");
  wrap.className = "results";

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

async function saveCurrent() {
  const stamp = new Date().toISOString().slice(0, 19).replace(/[:T]/g, "-");
  let title, content;
  if (state.viewing) {
    title = state.viewing.title;
    content = `# ${title}\n\nSaved ${new Date().toISOString()}\n\n---\n\n${state.viewing.text}`;
  } else if (state.results) {
    title = state.results.query || "research";
    content = briefMarkdown(state.results);
  } else { return; }
  const res = await fetch("/api/workspace/save", {
    method: "POST", headers: { "content-type": "application/json" },
    body: JSON.stringify({ path: `${stamp}-${slugify(title)}.md`, content }),
  }).then((r) => r.json());
  if (res.error) {
    setEngine("Could not keep it: " + res.error);
    addMascotNotice("Could not save", res.error, "attention");
  } else {
    setEngine("Kept — find it in Library");
    notifyWhenReady("Saved to Library", "The note is ready in your Library.");
  }
  $("save").disabled = true;
  loadFiles();
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
$("example-q").onclick = () => { $("url").value = "does caffeine affect sleep?"; findPapers(); };
$("refresh").onclick = loadFiles;
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
renderMascotPanel();

boot();
