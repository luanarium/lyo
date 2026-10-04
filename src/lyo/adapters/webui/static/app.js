// The page: one quikchat instance, pointed at whichever session is selected.

const el = (id) => document.getElementById(id);
const state = { session: "persistent", player: "", chat: null, stream: null };

const api = async (path, options) => {
  const response = await fetch(path, options);
  if (!response.ok) {
    let detail = response.statusText;
    try { detail = (await response.json()).error || detail; } catch {}
    throw new Error(detail);
  }
  return response.json();
};

// ---------------------------------------------------------------- rendering

const CLASS = {
  refusal: "lyo-refusal",
  location: "lyo-view", map: "lyo-view", inventory: "lyo-view",
  roster: "lyo-view", help: "lyo-view", stock: "lyo-view",
};

function show(line, mine) {
  if (!state.chat) return;
  const classes = [];
  if (line.kind && CLASS[line.kind]) classes.push(CLASS[line.kind]);
  if (line.private) classes.push("lyo-private");
  if (!mine && !line.player) classes.push("lyo-notice");

  const who = line.private ? "whisper" : (line.player || "world");
  const body = classes.length
    ? `<span class="${classes.join(" ")}">${escapeHtml(line.text)}</span>`
    : escapeHtml(line.text);
  state.chat.messageAddNew(body, who, "left", "assistant");
}

const escapeHtml = (text) =>
  text.replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

function say(text) {
  if (!state.chat) return;
  state.chat.messageAddNew(escapeHtml(text), state.player || "you", "right",
                           "user");
}

// ------------------------------------------------------------------ sending

async function send(text) {
  if (!state.player) {
    show({ text: "Pick an id under “Playing as” first.", kind: "refusal" }, true);
    return;
  }
  say(text);
  try {
    const reply = await api("/api/say", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session: state.session, player: state.player, text }),
    });
    // Our own public lines arrive on the stream too; show them from here and
    // let the stream skip anything we caused.
    reply.lines.forEach((line) => show(line, true));
    if (reply.prompt) show({ text: reply.prompt, private: true }, true);
    drawPlayers(reply.players);
  } catch (error) {
    show({ text: String(error.message || error), kind: "refusal" }, true);
  }
}

// ------------------------------------------------------------------- panels

function drawPlayers(players) {
  const list = el("players");
  list.innerHTML = "";
  if (!players || !players.length) {
    list.innerHTML =
      '<li class="empty">none yet — type <code>register</code></li>';
    return;
  }
  for (const p of players) {
    const item = document.createElement("li");
    if (p.id === state.player) item.className = "you";
    item.innerHTML =
      `<strong>${escapeHtml(p.name || p.id)}</strong> ` +
      `<span class="where">${escapeHtml(p.class || "")} · ` +
      `${p.hp}/${p.max_hp} hp · ${p.gold}g</span><br>` +
      `<span class="where">${escapeHtml(p.location || "")}` +
      `${p.dueling ? " · dueling" : ""}</span>`;
    item.title = `play as ${p.id}`;
    item.onclick = () => { el("player").value = p.id; pickPlayer(p.id); };
    list.append(item);
  }
  const known = el("known");
  known.innerHTML = "";
  for (const p of players) {
    const option = document.createElement("option");
    option.value = p.id;
    option.label = p.name || p.id;
    known.append(option);
  }
}

function describeMode(info) {
  el("mode").textContent = info.persistent
    ? "Persistent: everything here is saved to the project's sqlite3 file."
    : "Ephemeral: nothing here is saved, and Reset throws it away.";
  el("reset").hidden = info.persistent;
}

// ------------------------------------------------------------------ streams

function listen() {
  if (state.stream) state.stream.close();
  const source = new EventSource(
    `/api/events?session=${encodeURIComponent(state.session)}${tokenSuffix()}`);
  source.addEventListener("line", (message) => {
    const line = JSON.parse(message.data);
    // Skip what we just sent ourselves; `send` already printed it.
    if (line.player && line.player === state.player) return;
    show(line, false);
  });
  source.addEventListener("reset", () => {
    boot(`— ephemeral session reset —`);
  });
  state.stream = source;
}

const tokenSuffix = () => {
  const token = new URLSearchParams(location.search).get("token");
  return token ? `&token=${encodeURIComponent(token)}` : "";
};

// -------------------------------------------------------------------- setup

async function refresh() {
  const info = await api(
    `/api/state?session=${encodeURIComponent(state.session)}`);
  el("title").textContent = info.title;
  document.title = `lyo · ${info.title}`;
  el("verbs").innerHTML = info.verbs
    .map((v) => `<code>${escapeHtml(v)}</code>`).join("");
  drawPlayers(info.players);
  describeMode(info);
  return info;
}

async function boot(banner) {
  const info = await refresh();
  const mount = el("chat");
  mount.innerHTML = "";
  if (typeof quikchat === "undefined") {
    el("fallback").hidden = false;
    return;
  }
  state.chat = new quikchat("#chat", (_chat, text) => send(text), {
    theme: info.theme || "quikchat-theme-dark",
    titleArea: { title: `${info.title} — ${state.session}`, align: "center",
                 show: true },
    sanitize: false,
  });
  if (banner) show({ text: banner, kind: "refusal" }, true);
  show({ text: `Type a command, or "register" to make a character. ` +
               `Switch identity above to play both sides of a duel.`,
         private: true }, true);
  listen();
}

function pickPlayer(id) {
  state.player = id.trim();
  refresh().catch(() => {});
}

async function load(info) {
  const base = (info.assets || "https://unpkg.com/quikchat").replace(/\/$/, "");
  const css = document.createElement("link");
  css.rel = "stylesheet";
  css.href = base.endsWith(".js") ? base.replace(/[^/]+$/, "quikchat.css")
                                  : `${base}/dist/quikchat.css`;
  document.head.append(css);
  await new Promise((resolve) => {
    const script = document.createElement("script");
    script.src = base;
    script.onload = resolve;
    script.onerror = resolve;
    document.head.append(script);
  });
}

el("session").onchange = (e) => {
  state.session = e.target.value;
  boot(`— switched to the ${state.session} session —`);
};
el("player").onchange = (e) => pickPlayer(e.target.value);
el("reset").onclick = async () => {
  await api("/api/reset", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session: state.session }),
  });
};

(async () => {
  const info = await api("/api/state?session=persistent");
  await load(info);
  await boot();
})();
