/* "What you missed": the return screen, after the replay and the voice-over.
 * Three players who changed the game in the window, both teams then vs now, one line each.
 * A player opens a sheet (2D actions + stats, "While you were away | Whole match"); a team
 * opens a sheet compared with the match as the fan left it. Numbers come from the engine. */

import { $, app, esc, teamColour, teamName, emit, sizeCanvas, L, W } from "./state.js";

let data = null;          // the "missed" payload of the last return
let view = { page: "list" };

const pct = (v) => (v == null ? "–" : `${Math.round(v * 100)}%`);
const num = (v, d = 0) => (v == null ? "–" : Number(v).toFixed(d));
const surnameUp = (name) => { const [first, ...rest] = name.split(" "); return `${esc(first)} <b>${esc(rest.join(" ").toUpperCase())}</b>`; };
const REASON = {
  goals: ["goal", "goals"], assists: ["assist", "assists"], xg: ["xG", "xG"], key_passes: ["key pass", "key passes"],
  progressive_passes: ["forward pass", "forward passes"], duels_won: ["duel won", "duels won"],
  interceptions: ["interception", "interceptions"], passes_completed: ["completed pass", "completed passes"],
};
const reason = ([k, v]) => (k === "xg" ? `${Number(v).toFixed(2)} xG` : `${v} ${REASON[k][v === 1 ? 0 : 1]}`);

export const missedOpen = () => !$("#missed").hidden;

export function initMissed() {
  $("#missed").addEventListener("click", (e) => {
    const b = e.target.closest("[data-go]");
    if (!b) return;
    const [page, id] = b.dataset.go.split(":");
    if (page === "close") { hideMissed(); return; }
    if (page === "story") { hideMissed(); emit("show-story", {}); return; }
    if (page === "scope") { view.scope = id; render(); return; }
    view = { page, id, scope: "window" };
    render();
  });
}

/** Show the return screen for a catch-up's ``missed`` payload. */
export function showMissed(missed) {
  if (!missed?.players?.length) return false;
  data = missed;
  view = { page: "list" };
  render();
  return true;
}

export function hideMissed() {
  const el = $("#missed");
  el.hidden = true;
  el.innerHTML = "";
}

function head(title, sub) {
  return `<div class="ms-k"><span>${title}</span><span class="ms-btns">
      <button data-go="story">◂ STORY</button><button data-go="close" aria-label="Close">×</button></span></div>
    ${sub ? `<div class="ms-sub">${sub}</div>` : ""}`;
}

function windowLabel() {
  return data.late_join ? `THE STORY SO FAR · 0'–${data.to_minute}'` : `WHAT YOU MISSED · ${data.from_minute}'–${data.to_minute}'`;
}

function render() {
  const el = $("#missed");
  el.hidden = false;
  el.className = `missed ${view.page}`;
  if (view.page === "player") el.innerHTML = playerSheet(data.players.find((p) => p.id === view.id));
  else if (view.page === "team") el.innerHTML = teamSheet(view.id);
  else el.innerHTML = list();
  el.classList.remove("in"); void el.offsetWidth; el.classList.add("in");
  if (view.page === "player") drawActions(view.id);
}

function list() {
  const top = data.players[0]?.influence || 1;
  const players = data.players.map((p, i) => `
    <button class="ms-player" data-go="player:${p.id}" style="--team:${teamColour(p.team)}">
      <span class="ms-rank">${i + 1}</span><span class="ms-num">${p.number}</span>
      <span class="ms-who"><span class="ms-name">${surnameUp(p.name)}</span>
        <span class="ms-meta">${esc(teamName(p.team))} · ${esc(p.position)} · ${p.reasons.map(reason).join(" · ")}</span>
        <span class="ms-line">${esc(data.lines[p.id] || "")}</span></span>
      <span class="ms-bar"><i style="width:${Math.round((p.influence / top) * 100)}%"></i><em>${num(p.influence, 1)}</em></span>
    </button>`).join("");
  const teams = Object.entries(data.teams).map(([code, t]) => `
    <button class="ms-team" data-go="team:${code}" style="--team:${teamColour(code)}">
      <b>${esc(t.name)}</b><span>${data.late_join ? "" : `${esc(t.before.score)} → `}${esc(t.now.score)} · ${t.window.shots} shots ·
        ${num(t.window.xg, 2)} xG</span><small>${esc(data.lines[code] || "")}</small></button>`).join("");
  return `${head(windowLabel(), data.late_join ? "Players who changed the game before you joined"
    : "Players who changed the game while you were away")}
    <div class="ms-players">${players}</div>
    <div class="ms-teams">${teams}</div>
    <div class="ms-foot">Influence = goals×15 + assists×8 + xG×10 + key passes×3 + forward passes, duels won and interceptions
      (5 each at most) + completed passes×0.1 (30 at most) · numbers from the match engine ·
      ${data.source === "llm" ? "lines: Storyteller → Verifier" : "lines: factual templates"}</div>`;
}

function playerSheet(p) {
  const s = view.scope === "match" ? p.match : p.window;
  const rows = [
    ["PASSES", `${s.passes_completed}/${s.passes}`, pct(s.pass_accuracy)],
    ["AVG PASS DIFFICULTY", num(s.avg_pass_difficulty), "0–100"],
    ["KEY PASSES", s.key_passes, ""],
    ["SHOTS · xG", `${s.shots} · ${num(s.xg, 2)}`, s.goals ? `${s.goals} goal${s.goals > 1 ? "s" : ""}` : ""],
    ["ASSISTS", s.assists, ""],
    ["TOP SPEED", s.top_speed_kmh ? `${num(s.top_speed_kmh, 1)} km/h` : "–", s.sprints ? `${s.sprints} sprint${s.sprints > 1 ? "s" : ""}` : ""],
    ["WITH THE BALL", `${num(s.distance_with_ball_m)} m`, ""],
    ["DUELS WON", `${s.duels_won}/${s.duels}`, s.interceptions ? `${s.interceptions} interception${s.interceptions > 1 ? "s" : ""}` : ""],
  ];
  const away = data.late_join ? "BEFORE YOU JOINED" : "WHILE YOU WERE AWAY";
  return `${head(`<button class="ms-back" data-go="list">◂ ${windowLabel()}</button>`)}
    <div class="ms-sheet-h" style="--team:${teamColour(p.team)}"><span class="ms-num big">${p.number}</span>
      <div><div class="ms-name big">${surnameUp(p.name)}</div><div class="ms-meta">${esc(teamName(p.team))} · ${esc(p.position)}</div></div>
      <div class="seg ms-scope"><button data-go="scope:window" class="${view.scope === "window" ? "on" : ""}">${away}</button>
        <button data-go="scope:match" class="${view.scope === "match" ? "on" : ""}">WHOLE MATCH</button></div></div>
    <div class="ms-why">${esc(data.lines[p.id] || "")}</div>
    <div class="ms-body"><div class="ms-pitch"><canvas id="ms-canvas"></canvas>
        <div class="ms-legend"><span><i class="lg-pass"></i>pass</span><span><i class="lg-key"></i>key pass</span>
          <span><i class="lg-lost"></i>lost</span><span><i class="lg-shot"></i>shot (size = xG)</span><span><i class="lg-run"></i>run</span>
          <span><i class="lg-duel"></i>duel</span><span class="dir">ATTACKING →</span></div></div>
      <table class="ms-stats">${rows.map(([k, v, x]) => `<tr><td>${k}</td><td class="v">${v}</td><td class="x">${x}</td></tr>`).join("")}</table></div>`;
}

function teamSheet(code) {
  const t = data.teams[code];
  const late = data.late_join;
  const rows = late ? [
    ["SCORE", "", t.now.score], ["POSSESSION", "", pct(t.window.possession)], ["SHOTS", "", t.window.shots],
    ["xG", "", num(t.window.xg, 2)], ["PASS ACCURACY", "", pct(t.window.pass_accuracy)], ["BOX ENTRIES", "", t.window.box_entries],
    ["DANGER · NOW", "", t.now.danger], ["CONTROL · NOW", "", num(t.now.control, 2)],
  ] : [
    ["SCORE", t.before.score, t.now.score], ["POSSESSION", pct(t.before.possession), pct(t.window.possession)],
    ["SHOTS", t.before.shots, t.window.shots], ["xG", num(t.before.xg, 2), num(t.window.xg, 2)],
    ["PASS ACCURACY", pct(t.before.pass_accuracy), pct(t.window.pass_accuracy)], ["BOX ENTRIES", t.before.box_entries, t.window.box_entries],
    ["DANGER · 0–100", t.before.danger, t.now.danger], ["CONTROL", num(t.before.control, 2), num(t.now.control, 2)],
  ];
  const cols = late ? ["", `0'–${data.to_minute}'`] : [`BEFORE YOU LEFT · 0'–${data.from_minute}'`, `WHILE YOU WERE AWAY · ${data.from_minute}'–${data.to_minute}'`];
  return `${head(`<button class="ms-back" data-go="list">◂ ${windowLabel()}</button>`)}
    <div class="ms-sheet-h" style="--team:${teamColour(code)}"><span class="ms-crest"></span>
      <div><div class="ms-name big"><b>${esc(t.name.toUpperCase())}</b></div><div class="ms-meta">${t.now.players_on_pitch} players on the pitch</div></div></div>
    <div class="ms-why">${esc(data.lines[code] || "")}</div>
    <table class="ms-stats team"><tr><th></th>${cols.map((c) => `<th>${c}</th>`).join("")}</tr>
      ${rows.map(([k, a, b]) => `<tr><td>${k}</td>${late ? "" : `<td class="v dim">${a}</td>`}<td class="v">${b}</td></tr>`).join("")}</table>
    <div class="ms-foot">Score, danger and control: as you left them → as you found them. The other rows: totals for each period.</div>`;
}

/* ------------------------------------------------------------------ 2D actions */

async function drawActions(pid) {
  const from = view.scope === "match" ? 0 : data.from_t;
  const res = await fetch(`/api/session/${app.session}/player/${pid}/actions?from_t=${from}&to_t=${data.to_t}`).then((r) => r.json()).catch(() => null);
  const c = $("#ms-canvas");
  if (!c || !res || view.id !== pid) return;
  const dpr = sizeCanvas(c);
  const ctx = c.getContext("2d");
  const w = c.width, h = c.height, pad = 10 * dpr;
  const flip = res.team !== app.home;                        // the player's team always attacks to the right
  const X = (x) => pad + ((flip ? L - x : x) / L) * (w - 2 * pad);
  const Y = (y) => pad + ((flip ? W - y : y) / W) * (h - 2 * pad);
  const sx = (w - 2 * pad) / L, sy = (h - 2 * pad) / W;      // the pitch is symmetric: lines need no flip
  ctx.fillStyle = "#0f2a18"; ctx.fillRect(0, 0, w, h);
  ctx.strokeStyle = "rgba(255,255,255,.35)"; ctx.lineWidth = dpr;
  ctx.strokeRect(pad, pad, L * sx, W * sy);
  ctx.beginPath(); ctx.moveTo(pad + (L / 2) * sx, pad); ctx.lineTo(pad + (L / 2) * sx, pad + W * sy); ctx.stroke();
  ctx.beginPath(); ctx.arc(pad + (L / 2) * sx, pad + (W / 2) * sy, 9.15 * sx, 0, Math.PI * 2); ctx.stroke();
  for (const bx of [0, L - 16.5]) ctx.strokeRect(pad + bx * sx, pad + (W / 2 - 20.15) * sy, 16.5 * sx, 40.3 * sy);
  const colour = teamColour(res.team);
  const arrow = (a, col, dash = []) => {
    ctx.strokeStyle = col; ctx.setLineDash(dash.map((d) => d * dpr)); ctx.lineWidth = 1.6 * dpr;
    ctx.beginPath(); ctx.moveTo(X(a.x), Y(a.y)); ctx.lineTo(X(a.end_x), Y(a.end_y)); ctx.stroke(); ctx.setLineDash([]);
    ctx.fillStyle = col; ctx.beginPath(); ctx.arc(X(a.end_x), Y(a.end_y), 2.2 * dpr, 0, Math.PI * 2); ctx.fill();
  };
  for (const a of res.actions) {
    if (a.type === "carry" || a.type === "sprint") arrow(a, "rgba(255,255,255,.5)", [3, 3]);
    else if (a.type === "pass") arrow(a, a.key ? "#ffb000" : a.success ? colour : "#ff3b30");
  }
  for (const a of res.actions) {
    if (a.type === "shot") {
      const r = (4 + a.xg * 22) * dpr;
      ctx.lineWidth = 2 * dpr; ctx.strokeStyle = "#fff";
      ctx.fillStyle = a.outcome === "goal" ? "#fff" : "rgba(255,255,255,.12)";
      ctx.beginPath(); ctx.arc(X(a.x), Y(a.y), r, 0, Math.PI * 2); ctx.fill(); ctx.stroke();
    } else if (["tackle", "interception", "pressure"].includes(a.type)) {
      const s = 4 * dpr, x = X(a.x), y = Y(a.y);
      ctx.strokeStyle = a.won ? "#8fd3ff" : "rgba(143,211,255,.4)"; ctx.lineWidth = 2 * dpr;
      ctx.beginPath(); ctx.moveTo(x - s, y - s); ctx.lineTo(x + s, y + s); ctx.moveTo(x + s, y - s); ctx.lineTo(x - s, y + s); ctx.stroke();
    }
  }
  if (!res.actions.length) {
    ctx.fillStyle = "rgba(255,255,255,.6)"; ctx.font = `500 ${12 * dpr}px "JetBrains Mono", monospace`; ctx.textAlign = "center";
    ctx.fillText("No action on the ball in this period", w / 2, h / 2);
  }
}
