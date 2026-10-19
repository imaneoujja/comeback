/* CAM 2: top-down tactical view (also the PGM fallback when WebGL is unavailable). */

import { app, L, W, sizeCanvas } from "./state.js";

export function drawTactical(canvas, { numbers = true } = {}) {
  const dpr = sizeCanvas(canvas);
  const ctx = canvas.getContext("2d");
  const cw = canvas.width, ch = canvas.height;
  const scale = Math.min((cw * 0.92) / L, (ch * 0.9) / W);
  const ox = (cw - L * scale) / 2, oy = (ch - W * scale) / 2;
  const X = (x) => ox + x * scale, Y = (y) => oy + (W - y) * scale;

  ctx.fillStyle = "#06120b"; ctx.fillRect(0, 0, cw, ch);
  for (let i = 0; i < 14; i++) {
    ctx.fillStyle = i % 2 ? "#0b2416" : "#0a2113";
    ctx.fillRect(X((L / 14) * i), Y(W), (L / 14) * scale + 1, W * scale);
  }
  ctx.strokeStyle = "rgba(236,235,230,.45)"; ctx.lineWidth = Math.max(1, 1.1 * dpr);
  const rect = (x, y, w, h) => ctx.strokeRect(X(x), Y(y + h), w * scale, h * scale);
  rect(0, 0, L, W);
  ctx.beginPath(); ctx.moveTo(X(L / 2), Y(0)); ctx.lineTo(X(L / 2), Y(W)); ctx.stroke();
  ctx.beginPath(); ctx.arc(X(L / 2), Y(W / 2), 9.15 * scale, 0, Math.PI * 2); ctx.stroke();
  for (const left of [true, false]) {
    rect(left ? 0 : L - 16.5, W / 2 - 20.16, 16.5, 40.32);
    rect(left ? 0 : L - 5.5, W / 2 - 9.16, 5.5, 18.32);
  }

  const r = 1.5 * scale;
  ctx.font = `700 ${Math.round(r * 1.1)}px "IBM Plex Sans Condensed", sans-serif`;
  ctx.textAlign = "center"; ctx.textBaseline = "middle";
  for (const [pid, p] of Object.entries(app.pos)) {
    const info = app.roster[pid];
    if (!info) continue;
    const gk = info.position === "GK";
    const colour = app.teams[info.team].colour;
    ctx.fillStyle = gk ? "#e9e7e1" : colour;
    ctx.beginPath(); ctx.arc(X(p.x), Y(p.y), r, 0, Math.PI * 2); ctx.fill();
    if (pid === app.holder) { ctx.strokeStyle = "#fff"; ctx.lineWidth = 2 * dpr; ctx.stroke(); }
    if (numbers && r > 5) { ctx.fillStyle = gk ? colour : "#0a0a0a"; ctx.fillText(String(info.number), X(p.x), Y(p.y) + 0.5); }
  }
  const fav = app.profiles.find((p) => p.id === app.profileId)?.favourite_player_id;
  if (fav && app.pos[fav]) {                      // player focus: ring around the followed player
    ctx.strokeStyle = "#ffb000"; ctx.lineWidth = 2 * dpr;
    ctx.beginPath(); ctx.arc(X(app.pos[fav].x), Y(app.pos[fav].y), r * 1.9, 0, Math.PI * 2); ctx.stroke();
  }
  ctx.fillStyle = "#fff";
  ctx.beginPath(); ctx.arc(X(app.ball.x), Y(app.ball.y), Math.max(2 * dpr, 0.7 * scale), 0, Math.PI * 2); ctx.fill();
}
