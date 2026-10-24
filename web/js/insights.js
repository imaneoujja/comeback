/* "Match insights": the analysis the engine already does, made visible in four pictures.
 * 1. The match curve: momentum (control share) and chaos per minute, key moments marked.
 * 2. Shot map: every shot so far, size = xG, colour = team, goals highlighted.
 * 3. Players of the match: influence, average pass difficulty, top speed (click → player sheet).
 * 4. The three turning points, with their verified "why it matters".
 * No new computation and no model call: engine timeline, moment cards, /insights (shots, influence).
 * Open by default for analysts; casual fans get a lighter version. */

import { $, app, esc, on, teamColour, teamName, sizeCanvas, L, W, profile } from "./state.js";
import { showPlayerSheet } from "./missed.js";

const REFRESH_MS = 8000;
const TURNING = new Set(["goal", "red_card", "penalty", "big_chance", "momentum_swing", "shape_change"]);
let data = null;
let root = null;                // where the pictures were last drawn
let timer = null;
let tab = null;                 // "alerts" | "insights": the fan's own choice wins over the default

const analyst = () => profile()?.level === "analyst";

/** The insights data (shots, influence) of this session. */
export const fetchInsights = () => fetch(`/api/session/${app.session}/insights`).then((r) => (r.ok ? r.json() : null)).catch(() => null);

export function initInsights() {
  $("#cp-tabs").addEventListener("click", (e) => { if (e.target.dataset.tab) { tab = e.target.dataset.tab; show(); } });
  document.addEventListener("click", (e) => {
    const b = e.target.closest(".in-player[data-player]");
    if (!b || !data) return;
    const player = data.players.find((p) => p.id === b.dataset.player);
    showPlayerSheet({ ...player, window: player.match }, data.players.map((p) => ({ ...p, window: p.match })), data.t, data.minute);
  });
  on("state", () => { show(); refresh(); });
  on("card", () => { if (open() || root !== $("#insights")) renderTurning(); });
  on("timeline", () => { if (open() || root !== $("#insights")) drawCurve(); });
}

const open = () => !$("#insights").hidden;

function show() {
  const which = tab || (analyst() ? "insights" : "alerts");
  for (const b of document.querySelectorAll("#cp-tabs button")) b.classList.toggle("on", b.dataset.tab === which);
  for (const pane of document.querySelectorAll("#companion [data-pane]")) pane.hidden = pane.dataset.pane !== which;
  clearInterval(timer);
  if (which === "insights") { render(); refresh(); timer = setInterval(refresh, REFRESH_MS); }
}

async function refresh() {
  if (!open() || !app.session) return;
  data = await fetchInsights();
  render();
}

function render() { renderMatchInsights($("#insights"), data, analyst()); }

/** The four pictures, into ``el`` (the fan's companion or the studio's Research Desk). */
export function renderMatchInsights(el, insights, deep) {
  data = insights || data;
  root = el;
  if (!app.snapshot || !el) { if (el) el.innerHTML = ""; return; }
  el.innerHTML = `
    <section class="in-block"><div class="cp-k">THE MATCH SO FAR</div>
      <canvas class="in-curve" aria-label="Momentum and chaos minute by minute, key moments marked"></canvas>
      <div class="in-legend"><span><i style="background:${teamColour(app.home)}"></i>${esc(teamName(app.home))} in control</span>
        <span><i style="background:${teamColour(app.away)}"></i>${esc(teamName(app.away))} in control</span>
        ${deep ? `<span><i class="chaos"></i>chaos (duels + turnovers / min)</span>` : ""}</div></section>
    <section class="in-block"><div class="cp-k">SHOTS · SIZE = xG</div><canvas class="in-shots" aria-label="Shot map"></canvas>
      <div class="in-legend in-shots-sum"></div></section>
    <section class="in-block"><div class="cp-k">PLAYERS OF THE MATCH</div><div class="in-players"></div></section>
    <section class="in-block"><div class="cp-k">THE TURNING POINTS</div><div class="in-turning"></div></section>`;
  drawCurve();
  drawShots();
  renderPlayers();
  renderTurning();
}

/* 1 ----------------------------------------------------------------- the match curve */
function drawCurve() {
  const c = root?.querySelector(".in-curve");
  if (!c) return;
  const dpr = sizeCanvas(c);
  const ctx = c.getContext("2d");
  const w = c.width, h = c.height, mid = h / 2, pad = 4 * dpr;
  const X = (t) => pad + (t / app.durationT) * (w - 2 * pad);
  ctx.clearRect(0, 0, w, h);
  ctx.strokeStyle = "#2a2a2a"; ctx.lineWidth = dpr;
  ctx.beginPath(); ctx.moveTo(pad, mid); ctx.lineTo(w - pad, mid); ctx.stroke();
  const bw = Math.max(dpr, (w - 2 * pad) / 100);
  for (const e of app.timeline) {
    const diff = (e.control[app.home] ?? 0) - (e.control[app.away] ?? 0);
    const bh = Math.min(1, Math.abs(diff) / 0.5) * (mid - 6 * dpr);
    ctx.fillStyle = teamColour(diff >= 0 ? app.home : app.away);
    ctx.globalAlpha = 0.75;
    ctx.fillRect(X(e.t), diff >= 0 ? mid - bh : mid, bw, bh);
  }
  ctx.globalAlpha = 1;
  if (analyst() && app.timeline.length > 1) {          // chaos, the other half of "control vs chaos"
    ctx.strokeStyle = "#8fd3ff"; ctx.lineWidth = 1.5 * dpr; ctx.beginPath();
    app.timeline.forEach((e, i) => {
      const y = h - pad - Math.min(1, (e.chaos_per_min || 0) / 6) * (h - 2 * pad);
      if (i) ctx.lineTo(X(e.t), y); else ctx.moveTo(X(e.t), y);
    });
    ctx.stroke();
  }
  for (const card of app.cards.values()) {
    if (!["goal", "red_card"].includes(card.type)) continue;
    const x = X(card.t), y = card.team === app.home ? 7 * dpr : h - 7 * dpr;
    ctx.fillStyle = card.type === "red_card" ? "#ff3b30" : teamColour(card.team);
    ctx.strokeStyle = "#fff"; ctx.lineWidth = 1.4 * dpr;
    ctx.beginPath(); ctx.arc(x, y, 5 * dpr, 0, Math.PI * 2); ctx.fill(); ctx.stroke();
  }
}

/* 2 ----------------------------------------------------------------- the shot map */
function drawShots() {
  const c = root?.querySelector(".in-shots");
  if (!c || !data) return;
  const dpr = sizeCanvas(c);
  const ctx = c.getContext("2d");
  const w = c.width, h = c.height, pad = 6 * dpr;
  const sx = (w - 2 * pad) / L, sy = (h - 2 * pad) / W;
  ctx.fillStyle = "#0f2a18"; ctx.fillRect(0, 0, w, h);
  ctx.strokeStyle = "rgba(255,255,255,.3)"; ctx.lineWidth = dpr;
  ctx.strokeRect(pad, pad, L * sx, W * sy);
  ctx.beginPath(); ctx.moveTo(pad + (L / 2) * sx, pad); ctx.lineTo(pad + (L / 2) * sx, pad + W * sy); ctx.stroke();
  for (const bx of [0, L - 16.5]) ctx.strokeRect(pad + bx * sx, pad + (W / 2 - 20.15) * sy, 16.5 * sx, 40.3 * sy);
  const shots = [...data.shots].sort((a, b) => (a.outcome === "goal") - (b.outcome === "goal"));
  for (const s of shots) {
    const r = (2.5 + s.xg * 16) * dpr;
    ctx.fillStyle = teamColour(s.team);
    ctx.globalAlpha = s.outcome === "goal" ? 1 : 0.55;
    ctx.beginPath(); ctx.arc(pad + s.x * sx, pad + s.y * sy, r, 0, Math.PI * 2); ctx.fill();
    ctx.globalAlpha = 1;
    if (s.outcome === "goal") { ctx.strokeStyle = "#fff"; ctx.lineWidth = 2 * dpr; ctx.stroke(); }
  }
  const sum = (team) => data.shots.filter((s) => s.team === team);
  const line = (team) => `<span><i style="background:${teamColour(team)}"></i>${esc(team)} ${sum(team).length} shots ·
    ${sum(team).reduce((a, s) => a + s.xg, 0).toFixed(2)} xG</span>`;
  root.querySelector(".in-shots-sum").innerHTML = `${line(app.home)}${line(app.away)}<span>○ white ring = goal</span>`;
}

/* 3 ----------------------------------------------------------------- players of the match */
function renderPlayers() {
  const el = root?.querySelector(".in-players");
  if (!el || !data) return;
  const deep = analyst();
  const top = data.players[0]?.influence || 1;
  el.innerHTML = data.players.slice(0, deep ? 4 : 3).map((p) => `
    <button class="in-player" data-player="${esc(p.id)}" style="--team:${teamColour(p.team)}">
      <span class="ms-num">${p.number}</span>
      <span class="in-who"><b>${esc(p.name)}</b><small>${esc(p.position)} · ${esc(teamName(p.team))}</small>
        <span class="in-bar"><i style="width:${Math.round((p.influence / top) * 100)}%"></i></span></span>
      <span class="in-stats">${deep ? `<em>${p.match.avg_pass_difficulty ?? "–"}</em> pass diff.<br>` : ""}<em>${p.match.top_speed_kmh
        ? p.match.top_speed_kmh.toFixed(1) : "–"}</em> km/h<br><em>${p.influence.toFixed(0)}</em> influence</span>
    </button>`).join("") || `<div class="in-empty">No player has made a mark yet.</div>`;
}

/* 4 ----------------------------------------------------------------- the turning points */
function renderTurning() {
  const el = root?.querySelector(".in-turning");
  if (!el) return;
  const top = [...app.cards.values()].filter((c) => TURNING.has(c.type) && !c.pending)
    .sort((a, b) => b.importance - a.importance).slice(0, 3).sort((a, b) => a.t - b.t);
  el.innerHTML = top.map((c) => `<div class="in-turn" style="--team:${teamColour(c.team)}">
    <b>${c.minute}'</b><div><strong>${esc(c.headline)}</strong>${analyst() || top.length < 3 ? `<small>${esc(c.why_it_matters)}</small>` : ""}</div></div>`).join("")
    || `<div class="in-empty">The turning points will appear here.</div>`;
}
