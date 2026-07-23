// Reveriebot UI. No framework, no build step - it loads as-is.

const $ = (id) => document.getElementById(id);

const state = {
  provider: "anthropic",
  history: [],        // chat turns sent to the model
  viewing: null,      // { title, text } currently in the reading pane
  activeFile: null,
};

// ---------- boot ----------

async function boot() {
  try {
    const cfg = await fetch("/api/config").then((r) => r.json());
    renderProviders(cfg.providers);
    renderTools(cfg.tools);
  } catch {
    $("tools").innerHTML = '<span class="chip">server unreachable</span>';
  }
  await loadFiles();
}

function renderProviders(providers) {
  const sel = $("provider");
  sel.innerHTML = "";
  let firstReady = null;
  for (const p of providers) {
    const opt = document.createElement("option");
    opt.value = p.id;
    opt.textContent = p.ready ? `${p.label} — ${p.model}` : `${p.label} (no key)`;
    opt.disabled = !p.ready;
    if (p.ready && !firstReady) firstReady = p.id;
    sel.appendChild(opt);
  }
  if (firstReady) { sel.value = firstReady; state.provider = firstReady; }
  sel.onchange = () => { state.provider = sel.value; };
}

function renderTools(tools) {
  $("tools").innerHTML = tools
    .map((t) => `<span class="chip ${t.present ? "on" : ""}" title="${t.detail}">${t.label}</span>`)
    .join("");
}

// ---------- workspace ----------

async function loadFiles() {
  const { files } = await fetch("/api/workspace").then((r) => r.json());
  const ul = $("files");
  ul.innerHTML = "";
  $("ws-empty").style.display = files.length ? "none" : "block";

  for (const f of files) {
    const li = document.createElement("li");
    li.innerHTML = `${f.name}<span class="meta">${(f.size / 1024).toFixed(1)} KB</span>`;
    if (f.path === state.activeFile) li.classList.add("active");
    li.onclick = () => openArtifact(f);
    ul.appendChild(li);
  }
}

async function openArtifact(file) {
  const data = await fetch(
    "/api/workspace/file?path=" + encodeURIComponent(file.path)
  ).then((r) => r.json());

  if (data.error) return setEngine("could not open: " + data.error);

  state.activeFile = file.path;
  state.viewing = { title: file.name, text: data.content };
  $("url").value = "";
  setEngine(`artifact · ${file.name}`);

  if (file.kind === "html") {
    // Sandboxed so a saved page cannot script against the app.
    const frame = document.createElement("iframe");
    frame.setAttribute("sandbox", "");
    frame.srcdoc = data.content;
    $("view").replaceChildren(frame);
  } else {
    showText(data.content);
  }
  $("save").disabled = true;
  loadFiles();
}

// ---------- reading ----------

function showText(text) {
  const pre = document.createElement("pre");
  pre.textContent = text;
  $("view").replaceChildren(pre);
}

function setEngine(msg) { $("engine").textContent = msg || ""; }

async function openUrl() {
  const url = $("url").value.trim();
  if (!url) return;

  setEngine("fetching…");
  $("go").disabled = true;
  try {
    const data = await fetch("/api/fetch", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ url }),
    }).then((r) => r.json());

    if (data.error) { setEngine("failed: " + data.error); return; }

    state.viewing = { title: data.url, text: data.text };
    state.activeFile = null;
    showText(data.text);
    setEngine(
      `${data.engine === "obscura" ? "rendered via Obscura" : "plain fetch"} · ` +
      `${data.text.length.toLocaleString()} chars${data.note ? " · " + data.note : ""}`
    );
    $("save").disabled = false;
    loadFiles();
  } catch (e) {
    setEngine("failed: " + e.message);
  } finally {
    $("go").disabled = false;
  }
}

// ---------- finder (scholarly search) ----------

const looksLikeUrl = (s) => /^https?:\/\//i.test(s);

const escapeHtml = (s) =>
  (s || "").replace(/[&<>"]/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

async function findPapers() {
  const q = $("url").value.trim();
  if (!q) return;
  if (looksLikeUrl(q)) return openUrl();   // a pasted URL just opens

  setEngine("searching open-access sources…");
  $("find").disabled = true;
  try {
    const data = await fetch("/api/explore", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ query: q, provider: state.provider }),
    }).then((r) => r.json());

    if (data.error) { setEngine("search failed: " + data.error); return; }

    renderResults(data);
    const n = data.results.length;
    setEngine(
      `${n} result${n === 1 ? "" : "s"} · open-access first` +
      (data.notes && data.notes.length ? " · " + data.notes.join(" · ") : "")
    );
  } catch (e) {
    setEngine("search failed: " + e.message);
  } finally {
    $("find").disabled = false;
  }
}

function renderResults(data) {
  state.viewing = null;
  state.activeFile = null;
  $("save").disabled = true;

  const wrap = document.createElement("div");
  wrap.className = "results";

  // grounded answer, or an honest note about why there isn't one
  const note = document.createElement("div");
  if (data.answer) {
    note.className = "answer";
    note.innerHTML =
      `<div class="answer-head">grounded answer` +
      `<span class="meta">${escapeHtml((data.provider || "") + " " + (data.model || ""))}</span></div>`;
    const body = document.createElement("div");
    body.className = "answer-body";
    body.textContent = data.answer;
    note.appendChild(body);
  } else if (data.answer_error) {
    note.className = "answer note";
    note.textContent = "No grounded answer: " + data.answer_error +
      " — the papers below still stand.";
  } else {
    note.className = "answer note";
    note.textContent =
      "Add a model key in .env for a grounded answer. The papers below are real regardless.";
  }
  wrap.appendChild(note);

  data.results.forEach((r, i) => {
    const el = document.createElement("div");
    el.className = "paper";
    const authors = r.authors || [];
    const who = authors.slice(0, 3).join(", ") + (authors.length > 3 ? " et al." : "");
    const meta = [
      who, r.year, r.venue,
      r.cited_by != null ? `cited by ${r.cited_by}` : null, r.source,
    ].filter(Boolean).join(" · ");

    el.innerHTML =
      `<div class="paper-title">[${i + 1}] ${escapeHtml(r.title || "untitled")}</div>` +
      `<div class="paper-meta">${escapeHtml(meta)}</div>`;

    const actions = document.createElement("div");
    actions.className = "paper-actions";
    if (r.oa_url) {
      const read = document.createElement("button");
      read.className = "ghost";
      read.textContent = "Read full text";
      read.onclick = () => { $("url").value = r.oa_url; openUrl(); };
      actions.appendChild(read);
    }
    const link = r.oa_url || r.url;
    if (link) {
      const a = document.createElement("a");
      a.href = link; a.target = "_blank"; a.rel = "noopener";
      a.className = "paper-link";
      a.textContent = r.oa_url ? "open access ↗" : "link ↗";
      actions.appendChild(a);
    }
    el.appendChild(actions);

    if (r.abstract) {
      const ab = document.createElement("div");
      ab.className = "paper-abstract";
      ab.textContent = r.abstract;
      el.appendChild(ab);
    }
    wrap.appendChild(el);
  });

  $("view").replaceChildren(wrap);
}

async function saveCurrent() {
  if (!state.viewing) return;
  const stamp = new Date().toISOString().slice(0, 19).replace(/[:T]/g, "-");
  const slug = state.viewing.title
    .replace(/^https?:\/\//, "")
    .replace(/[^a-z0-9]+/gi, "-")
    .slice(0, 60)
    .replace(/^-|-$/g, "") || "artifact";

  const body = `# ${state.viewing.title}\n\nSaved ${new Date().toISOString()}\n\n---\n\n${state.viewing.text}`;
  const res = await fetch("/api/workspace/save", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ path: `${stamp}-${slug}.md`, content: body }),
  }).then((r) => r.json());

  setEngine(res.error ? "save failed: " + res.error : "saved to workspace");
  $("save").disabled = true;
  loadFiles();
}

// ---------- chat ----------

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
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        provider: state.provider,
        messages: state.history,
        context: state.viewing ? state.viewing.text : "",
      }),
    }).then((r) => r.json());

    if (res.error) {
      pending.remove();
      addMessage("err", res.error);
      state.history.pop();   // let the user retry cleanly
      return;
    }

    pending.remove();
    addMessage("bot", res.text);
    state.history.push({ role: "assistant", content: res.text });

    const u = res.usage || {};
    $("usage").textContent =
      `${res.provider} · ${res.model}` +
      (u.input_tokens ? ` · ${u.input_tokens} in / ${u.output_tokens} out` : "");
  } catch (err) {
    pending.remove();
    addMessage("err", err.message);
    state.history.pop();
  } finally {
    $("send").disabled = false;
  }
}

// ---------- wiring ----------

$("find").onclick = findPapers;
$("go").onclick = openUrl;
// Search is the primary action; a pasted URL still opens (findPapers detects it).
$("url").addEventListener("keydown", (e) => { if (e.key === "Enter") findPapers(); });
$("save").onclick = saveCurrent;
$("refresh").onclick = loadFiles;
$("composer").addEventListener("submit", send);
$("clear").onclick = () => {
  state.history = [];
  $("log").innerHTML = "";
  $("usage").textContent = "";
};
$("input").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) $("composer").requestSubmit();
});

boot();
