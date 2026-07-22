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

$("go").onclick = openUrl;
$("url").addEventListener("keydown", (e) => { if (e.key === "Enter") openUrl(); });
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
