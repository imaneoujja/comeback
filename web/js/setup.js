/* The first screen: who is watching (a fan or a studio), which match, and for a fan: side,
 * language, style, one metric and when they watch. The choices travel in the URL, so a
 * configuration can be reloaded or shared, and are remembered on this browser. */

import { $, esc, DEMO_MATCH, LANG_NAME } from "./state.js";

const KEY = "comeback.setup";
const DEFAULTS = { mode: "fan", match: DEMO_MATCH, side: "home", lang: "en", level: "casual", metric: null, start: "away",
  studioStart: "60" };
const FIELDS = Object.keys(DEFAULTS);
const START = { away: "steps away 63'–70'", join: "joins at 60'", kickoff: "from kick-off" };
const METRIC = { xg: "xG", possession: "possession", top_speed: "top speed", pass_difficulty: "pass difficulty" };
let config = { ...DEFAULTS };
let matches = [];
let hooks = {};
let running = false;

/** The metric a fan gets unless they pick one: their player's speed, xG for analysts, possession otherwise. */
const autoMetric = (c) => (c.side === "player" ? "top_speed" : c.level === "analyst" ? "xg" : "possession");
export const metricOf = (c) => c.metric || autoMetric(c);

/** ``h``: { getMatch(id) → Promise<meta>, onStart(config) } */
export async function initSetup(h) {
  hooks = h;
  config = { ...DEFAULTS, ...stored(), ...fromUrl() };
  $("#su-form").addEventListener("click", onPick);
  $("#su-form").addEventListener("submit", (e) => { e.preventDefault(); start(); });
  $("#su-x").addEventListener("click", closeSetup);
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && running) closeSetup(); });
  matches = await fetch("/api/matches").then((r) => r.json()).catch(() => []);
  if (!matches.some((m) => m.match_id === config.match)) config.match = DEMO_MATCH;
  $("#su-matches").innerHTML = matches.map((m) => `<button type="button" data-value="${esc(m.match_id)}">
    <b>${esc(m.home)} v ${esc(m.away)}</b><small>${m.scripted ? "Scripted storyline: a comeback"
      : "Unscripted: the same engine, agents and Verifier, live"}</small></button>`).join("");
  await renderSides();
  render();
  $("#setup").classList.remove("loading");
  $("#su-start").disabled = false;
  $("#su-start").focus();
}

export function openSetup() {
  $("#su-x").hidden = !running;
  document.body.classList.add("configuring");
  render();
  $("#su-start").focus();
}

function closeSetup() { document.body.classList.remove("configuring"); }

function onPick(e) {
  const b = e.target.closest(".su-opts button");
  if (!b) return;
  const field = b.closest("[data-field]").dataset.field;
  config[field] = b.dataset.value;
  if (field === "match") renderSides().then(render);
  else render();
}

async function renderSides() {
  const m = await hooks.getMatch(config.match);
  const nine = m.away.players.find((p) => p.id === `${m.away.id}-9`);
  $("#su-sides").innerHTML = `
    <button type="button" data-value="home" style="--team:${m.home.colour}"><b>${esc(m.home.name)}</b><small>Home side</small></button>
    <button type="button" data-value="away" style="--team:${m.away.colour}"><b>${esc(m.away.name)}</b><small>Away side</small></button>
    <button type="button" data-value="player" style="--team:${m.away.colour}"><b>★ ${esc(nine?.name || "A player")}</b>
      <small>Follow a player · ${esc(m.away.name)} #9</small></button>`;
}

function render() {
  const form = $("#su-form");
  form.dataset.mode = config.mode;
  for (const group of form.querySelectorAll("[data-field]")) {
    const field = group.dataset.field;
    const value = field === "metric" ? metricOf(config) : String(config[field]);
    for (const b of group.querySelectorAll("button")) b.classList.toggle("on", b.dataset.value === value);
  }
  $("#su-start").textContent = running ? "APPLY ▸" : "START ▸";
  $("#su-sum").textContent = summary();
}

function summary() {
  const m = matches.find((x) => x.match_id === config.match);
  const fixture = m ? `${m.home} v ${m.away}` : "";
  if (config.mode === "studio") return `Studio control room · ${fixture} · from ${config.studioStart === "0" ? "kick-off" : "60'"}`;
  const side = config.side === "player" ? "follows a player" : `${config.side === "home" ? m?.home : m?.away} fan`;
  return `${side} · ${LANG_NAME[config.lang]} · ${config.level} · ${METRIC[metricOf(config)]} · ${START[config.start]}`;
}

function start() {
  const cfg = { ...config, metric: metricOf(config) };
  try { localStorage.setItem(KEY, JSON.stringify(config)); } catch { /* private mode: fine */ }
  const params = new URLSearchParams(cfg.mode === "studio"
    ? { as: "studio", match: cfg.match, from: cfg.studioStart }
    : { as: "fan", match: cfg.match, side: cfg.side, lang: cfg.lang, level: cfg.level, metric: cfg.metric, start: cfg.start });
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
  if (q.get("match")) out.match = q.get("match");
  if (q.get("from")) out.studioStart = q.get("from") === "0" ? "0" : "60";
  for (const k of ["side", "lang", "level", "metric", "start"]) if (q.get(k)) out[k] = q.get(k);
  return Object.fromEntries(Object.entries(out).filter(([k]) => FIELDS.includes(k)));
}
