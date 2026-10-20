/* AUD monitor: 10,000 simulated fans served by the same match brain.
 * Left: one pixel per fan (watching / away / called back / not joined yet).
 * Right: what it costs — catch-ups delivered vs stories the LLM actually wrote,
 * and how LLM calls grow (barely) with the size of the audience. */

import { $, MATCH_ID, on, sizeCanvas } from "./state.js";

const COLOURS = ["#1f3a2a", "#6b5216", "#ff3b30", "#1a1a1a"];   // watching, away, called back, not joined
const fmt = (n) => Number(n).toLocaleString("en-US");
let curve = null;
let last = null;

export function initAudience() {
  $("#audience").innerHTML = `<div class="aud">
    <canvas id="aud-grid" aria-label="Simulated audience: one pixel per fan"></canvas>
    <div class="aud-side" id="aud-side"></div></div>`;
  on("crowd", render);
  on("state", (s) => s.crowd && render(s.crowd));
  on("view", () => requestAnimationFrame(() => last && render(last)));   // the canvas was hidden in the fan view
  fetch(`/api/scale/${MATCH_ID}`).then((r) => r.json()).then((d) => { curve = d.curve; if (last) render(last); }).catch(() => {});
}

function render(c) {
  last = c;
  const canvas = $("#aud-grid");
  sizeCanvas(canvas);
  const ctx = canvas.getContext("2d");
  const cols = 125, rows = Math.ceil(c.size / cols);
  const cw = canvas.width / cols, ch = canvas.height / rows;
  ctx.fillStyle = "#050505"; ctx.fillRect(0, 0, canvas.width, canvas.height);
  for (let i = 0; i < c.grid.length; i++) {
    ctx.fillStyle = COLOURS[c.grid.charCodeAt(i) - 48];
    ctx.fillRect((i % cols) * cw, Math.floor(i / cols) * ch, Math.max(1, cw - 0.6), Math.max(1, ch - 0.6));
  }
  const goal = c.back_in_time.at(-1);
  $("#aud-side").innerHTML = `
    <div class="aud-big">${fmt(c.size)} <small>VIEWERS</small></div>
    <div class="aud-row"><i style="background:${COLOURS[0]}"></i>${fmt(c.watching)}<i style="background:${COLOURS[1]}"></i>${fmt(c.away)}<i style="background:${COLOURS[2]}"></i>${fmt(c.called)}</div>
    <div class="aud-row">ALERTS SENT <b>${fmt(c.alerts_sent)}</b></div>
    <div class="aud-row hot">${goal ? `BACK FOR ${goal.minute}' GOAL <b>${fmt(goal.fans)}</b>` : "BACK FOR A GOAL <b>–</b>"}</div>
    <div class="aud-row">CATCH-UPS <b>${fmt(c.catchups)}</b></div>
    <div class="aud-row">LLM STORIES <b class="ok">${fmt(c.stories)}</b></div>
    ${curve ? curveSvg(curve) : `<div class="aud-row dim">computing scale curve…</div>`}`;
}

/* LLM calls vs audience size (log-log): COMEBACK stays nearly flat, one-call-per-catch-up does not. */
function curveSvg(points) {
  const w = 200, h = 30, pad = 3;
  const xs = points.map((p) => Math.log10(p.fans)), ys = points.flatMap((p) => [p.llm_calls, p.naive_llm_calls].map(Math.log10));
  const x = (v) => pad + ((v - Math.min(...xs)) / (Math.max(...xs) - Math.min(...xs))) * (w - 2 * pad);
  const y = (v) => h - pad - ((Math.log10(v) - Math.min(...ys)) / (Math.max(...ys) - Math.min(...ys))) * (h - 2 * pad);
  const line = (key) => points.map((p, i) => `${i ? "L" : "M"}${x(Math.log10(p.fans)).toFixed(1)},${y(p[key]).toFixed(1)}`).join("");
  const lastP = points.at(-1);
  return `<div class="aud-k">LLM CALLS · ${fmt(points[0].fans / 1000)}K → ${fmt(lastP.fans / 1000)}K FANS</div>
    <svg viewBox="0 0 ${w} ${h}" class="aud-svg" role="img" aria-label="LLM calls grow far slower than the audience">
      <path d="${line("naive_llm_calls")}" stroke="#6f6d68" stroke-dasharray="3 3" fill="none"/>
      <path d="${line("llm_calls")}" stroke="#30d158" stroke-width="2" fill="none"/>
    </svg>
    <div class="aud-row dim">${fmt(lastP.llm_calls)} <span class="ok">vs</span> ${fmt(lastP.naive_llm_calls)} naive</div>`;
}
