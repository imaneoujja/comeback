/* The product's front doors.
 * FAN APP: pick a live match, your side (and optionally a player to follow), how you like it.
 * Opening a match in progress is a late join: COMEBACK tells you the story so far.
 * STUDIO CONSOLE: the live matches with their audience; open a control room on one of them.
 * Choices travel in the URL (a set-up can be reloaded or shared) and are remembered here. */

import { $, esc, DEMO_MATCH } from "./state.js";

const KEY = "comeback.setup";
const BROWSER_LANG = (navigator.language || "en").slice(0, 2);
const DEFAULTS = { mode: "fan", match: DEMO_MATCH, side: "home", player: "", lang: ["en", "fr", "es"].includes(BROWSER_LANG) ? BROWSER_LANG : "en",
  level: "casual", metric: "" };
const FIELDS = Object.keys(DEFAULTS);
let config = { ...DEFAULTS };
let live = [];
let hooks = {};
let running = false;

const autoMetric = (c) => (c.player ? "top_speed" : c.level === "analyst" ? "xg" : "possession");
export const metricOf = (c) => c.metric || autoMetric(c);
export const liveMatch = (id) => live.find((m) => m.match_id === id);
const scoreText = (m) => m.score.replace("-", "–");
const fmt = (n) => Number(n).toLocaleString("en-US");

/** ``h``: { getMatch(id) → Promise<meta>, onStart(config), onNav(mode) } */
export async function initSetup(h) {
  hooks = h;
  config = { ...DEFAULTS, ...stored(), ...fromUrl() };
  $("#su-form").addEventListener("click", onPick);
  $("#su-form").addEventListener("submit", (e) => { e.preventDefault(); start(); });
  $("#su-x").addEventListener("click", closeSetup);
  for (const [id, field] of [["#su-player", "player"], ["#su-lang", "lang"], ["#su-metric", "metric"]]) {
    $(id).addEventListener("change", (e) => { config[field] = e.target.value; render(); });
  }
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && running) closeSetup(); });
  live = await fetch("/api/live").then((r) => r.json()).catch(() => []);
  if (!live.some((m) => m.match_id === config.match)) config.match = DEMO_MATCH;
  renderMatches();
  await renderSides();
  render();
  $("#setup").classList.remove("loading");
  $("#su-start").disabled = false;
}

/** Show a front door: "fan" (the default) or "studio" (the console). */
export function openSetup(mode = config.mode) {
  config.mode = mode;
  $("#su-x").hidden = !running;
  document.body.classList.add("configuring");
  render();
}

function closeSetup() { document.body.classList.remove("configuring"); }

function onPick(e) {
  const go = e.target.closest("[data-goto]");
  if (go) { config.mode = go.dataset.goto; hooks.onNav(config.mode); render(); return; }
  const open = e.target.closest("[data-open]");
  if (open) { config.match = open.dataset.open; config.mode = "studio"; start(); return; }
  const b = e.target.closest(".su-opts button");
  if (!b) return;
  const field = b.closest("[data-field]").dataset.field;
  config[field] = b.dataset.value;
  if (field === "match") { config.player = ""; renderSides().then(render); return; }
  if (field === "side") renderPlayers();
  render();
}

function renderMatches() {
  $("#su-matches").innerHTML = live.map((m) => `<button type="button" data-value="${esc(m.match_id)}">
    <span class="lv"><i></i>LIVE ${m.minute}'</span>
    <b><span style="color:${m.home_colour}">■</span> ${esc(m.home)} ${scoreText(m)} ${esc(m.away)} <span style="color:${m.away_colour}">■</span></b>
    <small>${m.quiet ? "Quiet so far" : `${m.xg.toFixed(1)} xG so far`}</small></button>`).join("");
  $("#console").innerHTML = live.map((m) => `<div class="cs-row">
    <span class="lv"><i></i>LIVE ${m.minute}'</span>
    <b>${esc(m.home)} ${scoreText(m)} ${esc(m.away)}</b>
    <span class="cs-aud"><em>${fmt(m.audience.viewers)}</em> viewers · <em>${fmt(m.audience.away)}</em> away now ·
      <em>${fmt(m.audience.call_backs)}</em> call-backs sent</span>
    <button type="button" class="key hot" data-open="${esc(m.match_id)}">OPEN CONTROL ROOM ▸</button></div>`).join("");
}

let meta = null;
async function renderSides() {
  meta = await hooks.getMatch(config.match);
  $("#su-sides").innerHTML = `
    <button type="button" data-value="home" style="--team:${meta.home.colour}"><b>${esc(meta.home.name)}</b><small>Home</small></button>
    <button type="button" data-value="away" style="--team:${meta.away.colour}"><b>${esc(meta.away.name)}</b><small>Away</small></button>
    <button type="button" data-value="neutral"><b>Neutral</b><small>Just here for the football</small></button>`;
  renderPlayers();
}

function renderPlayers() {
  const sides = config.side === "home" ? ["home"] : config.side === "away" ? ["away"] : ["home", "away"];
  const ids = sides.flatMap((s) => meta[s].players.map((p) => p.id));
  if (config.player && !ids.includes(config.player)) config.player = "";
  $("#su-player").innerHTML = `<option value="">Nobody in particular</option>` + sides.map((s) => `<optgroup label="${esc(meta[s].name)}">
    ${meta[s].players.map((p) => `<option value="${esc(p.id)}">${p.number} · ${esc(p.name)} · ${esc(p.position)}</option>`).join("")}</optgroup>`).join("");
  $("#su-player").value = config.player;
}

function render() {
  const form = $("#su-form");
  form.dataset.view = config.mode;
  for (const group of form.querySelectorAll("[data-field]")) {
    const value = String(config[group.dataset.field]);
    for (const b of group.querySelectorAll("button")) b.classList.toggle("on", b.dataset.value === value);
  }
  $("#su-lang").value = config.lang;
  $("#su-metric").value = config.metric;
  $("#su-start").textContent = "WATCH LIVE ▸";
  const m = liveMatch(config.match);
  const side = config.side === "neutral" ? "neutral" : `${config.side === "home" ? m?.home : m?.away} fan`;
  const follow = config.player && meta ? ` · follows ${[...meta.home.players, ...meta.away.players].find((p) => p.id === config.player)?.name}` : "";
  $("#su-sum").textContent = m ? `${m.home} ${scoreText(m)} ${m.away} · LIVE ${m.minute}' · ${side}${follow}` : "";
  hooks.onNav?.(config.mode);
}

function start() {
  const cfg = { ...config, metric: metricOf(config), liveMinute: liveMatch(config.match)?.live_minute ?? 0 };
  try { localStorage.setItem(KEY, JSON.stringify(config)); } catch { /* private mode: fine */ }
  const params = new URLSearchParams(cfg.mode === "studio" ? { as: "studio", match: cfg.match }
    : { as: "fan", match: cfg.match, side: cfg.side, lang: cfg.lang, level: cfg.level, ...(cfg.player ? { player: cfg.player } : {}),
      ...(config.metric ? { metric: config.metric } : {}) });
  history.replaceState(null, "", `?${params}`);
  running = true;
  closeSetup();
  hooks.onStart(cfg);
}

function stored() {
  try { return JSON.parse(localStorage.getItem(KEY) || "{}"); } catch { return {}; }
}

function fromUrl() {
  const q = new URLSearchParams(location.search);
  const out = {};
  if (q.get("as")) out.mode = q.get("as") === "studio" ? "studio" : "fan";
  for (const k of ["match", "side", "player", "lang", "level", "metric"]) if (q.get(k)) out[k] = q.get(k);
  if (out.side === "player") out.side = "neutral";
  return Object.fromEntries(Object.entries(out).filter(([k]) => FIELDS.includes(k)));
}
