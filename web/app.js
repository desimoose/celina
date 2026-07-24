// Reveriebot workspace UI. Vanilla, no build step.

const $ = (id) => document.getElementById(id);

const state = {
  provider: "anthropic",
  view: "work",
  history: [],
  viewing: null,       // { title, text } in the reader
  results: null,       // last search result (answer + sources)
  activeFile: null,
  studioDraft: null,   // { fmt, label, text, provider, model }
};

const FORMAT_LABELS = {
  tiktok: "TikTok script",
  podcast: "Podcast episode",
  linkedin: "LinkedIn slideshow",
};

const escapeHtml = (s) =>
  (s || "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const looksLikeUrl = (s) => /^https?:\/\//i.test(s);

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
  wireNav();
}

function renderProviders(providers) {
  const sel = $("provider");
  sel.innerHTML = "";
  let firstReady = null;
  for (const p of providers) {
    const opt = document.createElement("option");
    opt.value = p.id;
    opt.textContent = p.ready ? `${p.label}` : `${p.label} (no key)`;
    opt.disabled = !p.ready;
    if (p.ready && !firstReady) firstReady = p.id;
    sel.appendChild(opt);
  }
  if (firstReady) { sel.value = firstReady; state.provider = firstReady; }
  sel.onchange = () => { state.provider = sel.value; };
}

function renderTools(tools) {
  $("tools").innerHTML = tools
    .map((t) => `<span class="chip ${t.present ? "on" : ""}" title="${escapeHtml(t.detail)}">${escapeHtml(t.label)}</span>`)
    .join("");
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
  const map = { work: "s-work", library: "s-library", studio: "s-studio", editor: "s-editor" };
  Object.entries(map).forEach(([v, id]) => { $(id).hidden = v !== view; });
  if (view === "studio") updateStudioSrc();
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
  if (state.view === "studio" && state.studioDraft) return state.studioDraft.text;
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
  setEngine(`artifact · ${file.name}`);
  if (file.kind === "html") {
    const frame = document.createElement("iframe");
    frame.setAttribute("sandbox", "");
    frame.srcdoc = data.content;
    $("view").replaceChildren(frame);
  } else {
    showText(data.content);
  }
  $("save").disabled = true;
  updateStudioSrc();
  nav("work");
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
      method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ url }),
    }).then((r) => r.json());
    if (data.error) { setEngine("failed: " + data.error); return; }
    state.viewing = { title: data.url, text: data.text };
    state.activeFile = null;
    state.results = null;
    showText(data.text);
    setEngine(
      `${data.engine.startsWith("obscura") ? "via Obscura" : "plain fetch"} · ` +
      `${data.text.length.toLocaleString()} chars${data.note ? " · " + data.note : ""}`
    );
    $("save").disabled = false;
    updateStudioSrc();
  } catch (e) {
    setEngine("failed: " + e.message);
  } finally {
    $("go").disabled = false;
  }
}

// ---------- search (finder) ----------

async function findPapers() {
  const q = $("url").value.trim();
  if (!q) return;
  if (looksLikeUrl(q)) return openUrl();
  setEngine("searching open-access sources…");
  $("find").disabled = true;
  try {
    const data = await fetch("/api/explore", {
      method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ query: q, provider: state.provider }),
    }).then((r) => r.json());
    if (data.error) { setEngine("search failed: " + data.error); return; }
    data.query = data.query || q;
    renderResults(data);
    const n = data.results.length;
    setEngine(`${n} result${n === 1 ? "" : "s"} · open-access first` +
      (data.notes && data.notes.length ? " · " + data.notes.join(" · ") : ""));
  } catch (e) {
    setEngine("search failed: " + e.message);
  } finally {
    $("find").disabled = false;
  }
}

function renderResults(data) {
  state.viewing = null;
  state.activeFile = null;
  state.results = data;
  $("save").disabled = false;
  updateStudioSrc();

  const wrap = document.createElement("div");
  wrap.className = "results";

  const note = document.createElement("div");
  if (data.answer) {
    note.className = "answer";
    note.innerHTML = `<div class="answer-head">grounded answer<span class="meta">${escapeHtml((data.provider || "") + " " + (data.model || ""))}</span></div>`;
    const body = document.createElement("div");
    body.className = "answer-body";
    body.textContent = data.answer;
    note.appendChild(body);
  } else if (data.answer_error) {
    note.className = "answer note";
    note.textContent = "No grounded answer: " + data.answer_error + " — the papers below still stand.";
  } else {
    note.className = "answer note";
    note.textContent = "Add a model key for a grounded answer. The papers below are real regardless.";
  }
  wrap.appendChild(note);

  data.results.forEach((r, i) => {
    const el = document.createElement("div");
    el.className = "paper";
    const authors = r.authors || [];
    const who = authors.slice(0, 3).join(", ") + (authors.length > 3 ? " et al." : "");
    const meta = [who, r.year, r.venue, r.cited_by != null ? `cited by ${r.cited_by}` : null, r.source].filter(Boolean).join(" · ");
    el.innerHTML = `<div class="paper-title">[${i + 1}] ${escapeHtml(r.title || "untitled")}</div><div class="paper-meta">${escapeHtml(meta)}</div>`;
    const actions = document.createElement("div");
    actions.className = "paper-actions";
    if (r.oa_url) {
      const read = document.createElement("button");
      read.className = "btn btn--ghost";
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

// ---------- studio ----------

function updateStudioSrc() {
  const src = currentSource();
  $("studio-src").textContent = src ? "from: " + src.label.slice(0, 60) : "No source yet";
}

async function generate(fmt, btn) {
  const src = currentSource();
  if (!src) {
    $("studio-out").innerHTML = `<div class="empty small">No source yet. Search a paper and open its full text, or open a saved brief, then come back.</div>`;
    return;
  }
  btn.setAttribute("aria-busy", "true");
  $("studio-out").innerHTML = `<div class="empty small">Writing your ${FORMAT_LABELS[fmt]} from “${escapeHtml(src.label.slice(0, 50))}”…</div>`;
  try {
    const res = await fetch("/api/studio", {
      method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ provider: state.provider, format: fmt, source: src.text }),
    }).then((r) => r.json());
    if (res.error) {
      $("studio-out").innerHTML = `<div class="empty small">Couldn’t write that: ${escapeHtml(res.error)}</div>`;
      return;
    }
    state.studioDraft = { fmt, label: src.label, text: res.text, provider: res.provider, model: res.model };
    renderDraft();
  } catch (e) {
    $("studio-out").innerHTML = `<div class="empty small">Couldn’t write that: ${escapeHtml(e.message)}</div>`;
  } finally {
    btn.removeAttribute("aria-busy");
  }
}

function renderDraft() {
  const d = state.studioDraft;
  const wrap = document.createElement("div");
  wrap.className = "draft";
  wrap.innerHTML = `<div class="draft-head"><span class="tag">${escapeHtml(FORMAT_LABELS[d.fmt])}</span><span class="meta">${escapeHtml((d.provider || "") + " " + (d.model || ""))}</span></div>`;
  const ta = document.createElement("textarea");
  ta.value = d.text;
  ta.setAttribute("aria-label", FORMAT_LABELS[d.fmt] + " draft");
  ta.oninput = () => { d.text = ta.value; };
  wrap.appendChild(ta);
  const actions = document.createElement("div");
  actions.className = "draft-actions";
  const save = document.createElement("button");
  save.className = "btn btn--create";
  save.textContent = "Save to Library";
  save.onclick = saveDraft;
  const regen = document.createElement("button");
  regen.className = "btn btn--ghost";
  regen.textContent = "Rewrite";
  regen.onclick = () => { const b = document.querySelector(`.fmt[data-fmt="${d.fmt}"]`); generate(d.fmt, b); };
  actions.append(save, regen);
  wrap.appendChild(actions);
  $("studio-out").replaceChildren(wrap);
}

async function saveDraft() {
  const d = state.studioDraft;
  if (!d) return;
  const stamp = new Date().toISOString().slice(0, 19).replace(/[:T]/g, "-");
  const content = `# ${FORMAT_LABELS[d.fmt]}\n\nFrom: ${d.label}\nSaved ${new Date().toISOString()} · ${d.provider} ${d.model}\n\n---\n\n${d.text}`;
  const res = await fetch("/api/workspace/save", {
    method: "POST", headers: { "content-type": "application/json" },
    body: JSON.stringify({ path: `${stamp}-${d.fmt}.md`, content }),
  }).then((r) => r.json());
  const meta = $("studio-out").querySelector(".draft-head .meta");
  if (meta) meta.textContent = res.error ? "save failed" : "saved to Library";
  loadFiles();
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
  setEngine(res.error ? "save failed: " + res.error : "saved to Library");
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
    if (res.error) { pending.remove(); addMessage("err", res.error); state.history.pop(); return; }
    pending.remove();
    addMessage("bot", res.text);
    state.history.push({ role: "assistant", content: res.text });
    const u = res.usage || {};
    $("usage").textContent = `${res.provider} · ${res.model}` + (u.input_tokens ? ` · ${u.input_tokens} in / ${u.output_tokens} out` : "");
  } catch (err) {
    pending.remove(); addMessage("err", err.message); state.history.pop();
  } finally {
    $("send").disabled = false;
  }
}

// ---------- wiring ----------

$("find").onclick = findPapers;
$("go").onclick = openUrl;
$("url").addEventListener("keydown", (e) => { if (e.key === "Enter") findPapers(); });
$("save").onclick = saveCurrent;
$("refresh").onclick = loadFiles;
document.querySelectorAll(".fmt").forEach((b) => { b.onclick = () => generate(b.dataset.fmt, b); });
$("composer").addEventListener("submit", send);
$("clear").onclick = () => { state.history = []; $("log").innerHTML = ""; $("usage").textContent = ""; };
$("input").addEventListener("keydown", (e) => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) $("composer").requestSubmit(); });

boot();
