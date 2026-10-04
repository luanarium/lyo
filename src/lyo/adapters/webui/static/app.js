// The page: one quikchat instance, pointed at whichever session is selected.

const el = (id) => document.getElementById(id);
//  Opens on the throwaway simulation, so poking around saves nothing until
//  the session is switched deliberately. Both defaults are settings.
const state = { session: "ephemeral", player: "", chat: null, stream: null,
                prefix: "!", pace: 600 };

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
  refusal: "lyo-refusal", hint: "lyo-hint",
  location: "lyo-view", map: "lyo-view", inventory: "lyo-view",
  roster: "lyo-view", help: "lyo-view", stock: "lyo-view",
};

// A view's second line is its description, which views.py always puts there.
const DESCRIBED = new Set(["location", "map"]);
const NUMBER = /(?<![\w;&#])(\d+)(?![\w;])/g;

// Escape first, then insert tags: digits are untouched by escaping, so the
// number pattern is safe to run afterwards.
function markup(text, kind) {
  return text.split("\n").map((row, index) => {
    let marked = escapeHtml(row).replace(NUMBER, "<strong>$1</strong>");
    const prose = !/[0-9:]/.test(row) && /[a-z]/.test(row);
    if ((DESCRIBED.has(kind) && index === 1) || (kind === "flavour" && prose)) {
      marked = `<em>${marked}</em>`;
    }
    return marked;
  }).join("<br>");
}

function paint(line, mine) {
  if (!state.chat) return;
  const classes = [];
  if (line.kind && CLASS[line.kind]) classes.push(CLASS[line.kind]);
  if (line.private) classes.push("lyo-private");
  if (!mine && !line.player) classes.push("lyo-notice");

  const body = markup(line.text, line.kind);
  const wrapped = classes.length
    ? `<span class="${classes.join(" ")}">${body}</span>` : body;
  state.chat.messageAddNew(wrapped, "", "left", "assistant");
}

// Output is paced so a turn reads instead of landing all at once. One queue,
// drained in order, so a line pushed by another player cannot jump the turn
// it interrupted.
const pending = [];
let draining = false;

function show(line, mine) {
  pending.push([line, mine]);
  if (!draining) drain();
}

async function drain() {
  draining = true;
  while (pending.length) {
    const [line, mine] = pending.shift();
    //  The beat goes before the line, including the first: a reply that lands
    //  the instant you press enter reads like an echo, not an answer.
    if (state.pace > 0) await beat();
    paint(line, mine);
  }
  draining = false;
}

//  quikchat's own three-dot pulse, shown for as long as the beat lasts.
async function beat() {
  let dots = null;
  try {
    dots = state.chat.messageAddTypingIndicator("", "left");
  } catch {
    dots = null;
  }
  try {
    await new Promise((go) => setTimeout(go, state.pace));
  } finally {
    if (dots !== null && dots !== undefined) {
      try { state.chat.messageRemove(dots); } catch {}
    }
  }
}

const escapeHtml = (text) =>
  text.replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

function say(text) {
  if (!state.chat) return;
  state.chat.messageAddNew(escapeHtml(text), "", "right", "user");
}

// ------------------------------------------------------------------ sending

async function send(text) {
  if (!state.player) {
    show({ text: "Pick an id under “Playing as” first.", kind: "refusal" },
         true);
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
  state.prefix = info.prefix ?? "!";
  state.pace = info.pace ?? 0;
  //  Fill the identity once; never tread on what has been typed since.
  if (!state.player) {
    state.player = (el("player").value || info.player || "").trim();
    el("player").value = state.player;
  }
  el("verbs").innerHTML = info.verbs
    .map((v) => `<code>${escapeHtml(state.prefix + v)}</code>`).join("");
  const box = document.querySelector(".quikchat-input-textbox");
  if (box) box.placeholder = `${state.prefix}look — enter to send`;
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
  sendOnEnter();
  if (banner) show({ text: banner, kind: "refusal" }, true);
  show({ text: `Commands start with ${state.prefix}. ` +
               `Try ${state.prefix}register to make a character, then ` +
               `${state.prefix}look.`, private: true, kind: "flavour" }, true);
  show({ text: `Switch identity above to play both sides of a duel.`,
         private: true, kind: "flavour" }, true);
  listen();
}

function sendOnEnter() {
  const box = document.querySelector(".quikchat-input-textbox");
  if (!box || box.dataset.lyoEnter) return;
  box.dataset.lyoEnter = "1";
  box.placeholder = `${state.prefix}look — enter to send`;
  //  quikchat binds Shift+Enter only, and exposes no option to change it.
  box.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" || event.shiftKey) return;
    event.preventDefault();
    const text = box.value.trim();
    if (text) send(text);          // messageAddNew clears the box for us
  });
  box.focus();
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
  //  An unnamed request means whichever session the host opens on.
  const first = await api("/api/state");
  if (first.session && first.session !== state.session) {
    state.session = first.session;
  }
  el("session").value = state.session;
  await load(first);
  await boot();
})();
