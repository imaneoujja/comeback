"use strict";

/* COMEBACK web client: draws "the TV" (pitch, score bug, overlays), the match
 * timeline, the studio feed and the fan's phone, all fed by one SSE stream. */

const MATCH_ID = "demo-comeback";
const SPEEDS = [1, 5, 10, 20, 40];
const L = 105, W = 68;
const MIN_WALL_S = { lower_third: 2.4, top_right: 2.6, banner: 5.5 };
const TYPE_LABEL = {
  goal: "GOAL", big_chance: "BIG CHANCE", red_card: "RED CARD", penalty: "PENALTY",
  shape_change: "SHAPE CHANGE", momentum_swing: "MOMENTUM SWING", half_time: "HALF-TIME",
  full_time: "FULL-TIME", milestone: "MILESTONE", substitution: "SUBSTITUTION", danger_peak: "DANGER",
};
const LANG_LABEL = { en: "English", fr: "Français", es: "Español" };

const $ = (sel) => document.querySelector(sel);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]))
  .replace(/(\d)-(\d)/g, "$1\u2011$2");   // keep scores like 1-2 on one line

const app = {
  session: newSessionId(), profileId: "omar", speed: 10, paused: false,
  match: null, teams: {}, home: null, away: null, roster: {}, profiles: [],
  snapshot: null, timeline: [], cards: new Map(), notes: [], awayBands: [], present: true,
  lineup: {}, possession: null, holder: null,
  ball: { x: L / 2, y: W / 2 }, ballAnim: null, pos: {},
  overlays: {}, es: null, durationT: 5700, lastFrame: performance.now(),
};

function newSessionId() { return Math.random().toString(36).slice(2, 12); }
async function post(path) {
  const res = await fetch(`/api/session/${app.session}/${path}`, { method: "POST" });
  return res.ok ? res.json() : null;
}

/* ------------------------------------------------------------------ boot */

async function boot() {
  const [match, profiles] = await Promise.all([
    fetch(`/api/match/${MATCH_ID}`).then((r) => r.json()),
    fetch("/api/profiles").then((r) => r.json()),
  ]);
  app.match = match;
  app.profiles = profiles;
  app.durationT = match.duration_t;
  app.home = match.home.id;
  app.away = match.away.id;
  for (const side of ["home", "away"]) {
    const club = match[side];
    app.teams[club.id] = { ...club, isHome: side === "home" };
    for (const p of club.players) app.roster[p.id] = { ...p, team: club.id };
  }
  document.documentElement.style.setProperty("--home", app.teams[app.home].colour);
  document.documentElement.style.setProperty("--away", app.teams[app.away].colour);
  $(".lg-home-name").textContent = app.teams[app.home].name;
  $(".lg-away-name").textContent = app.teams[app.away].name;
  buildControls();
  connect();
  requestAnimationFrame(frame);
}

function buildControls() {
  $("#speeds").innerHTML = SPEEDS.map((s) => `<button data-speed="${s}">×${s}</button>`).join("");
  $("#speeds").addEventListener("click", (e) => {
    const s = Number(e.target.dataset.speed);
    if (!s) return;
    app.speed = s;
    renderControls();
    post(`speed?value=${s}`);
  });
  $("#pause").addEventListener("click", () => {
    app.paused = !app.paused;
    renderControls();
    post(`pause?paused=${app.paused}`);
  });
  $("#restart").addEventListener("click", restart);
  $("#btn-away").addEventListener("click", goAway);
  $("#btn-back").addEventListener("click", comeBack);
  $("#btn-join").addEventListener("click", () => { hideCatchup(); post("join?minute=60"); });
  $("#profiles").addEventListener("click", (e) => {
    const btn = e.target.closest("[data-profile]");
    if (!btn || btn.dataset.profile === app.profileId) return;
    app.profileId = btn.dataset.profile;
    hideCatchup();
    post(`profile?id=${app.profileId}`);
  });
  document.addEventListener("visibilitychange", () => {
    if (!$("#auto-away").checked) return;
    if (document.hidden) goAway(); else comeBack();
  });
  window.addEventListener("resize", () => { sizeCanvas($("#pitch")); sizeCanvas($("#timeline")); drawTimeline(); });
}

function goAway() { if (app.present) post("away"); }
function comeBack() { if (!app.present) post("back"); }

function restart() {
  if (app.es) app.es.close();
  app.session = newSessionId();
  Object.assign(app, { cards: new Map(), notes: [], timeline: [], awayBands: [], present: true, holder: null, pos: {} });
  hideCatchup();
  connect();
}

/* ------------------------------------------------------------------ stream */

function connect() {
  const url = `/api/stream?match_id=${MATCH_ID}&session=${app.session}&profile=${app.profileId}&speed=${app.speed}`;
  const es = new EventSource(url);
  app.es = es;
  const on = (type, fn) => es.addEventListener(type, (m) => fn(JSON.parse(m.data)));
  on("state", onState);
  on("event", onEvent);
  on("snapshot", (s) => { app.snapshot = s; renderScore(); });
  on("cue", showCue);
  on("card", (c) => { app.cards.set(c.moment_id, c); renderCards(); drawTimeline(); refreshBannerCard(c); });
  on("timeline", (t) => { app.timeline.push(t); drawTimeline(); });
  on("notification", (n) => { app.notes.unshift(n); renderNotes(); buzz(); drawTimeline(); });
  on("presence", (p) => {
    app.present = p.present; app.awayBands = p.away_bands;
    if (!p.present) hideCatchup();
    renderPresence(); drawTimeline();
  });
  on("catchup", renderCatchup);
  on("end", () => showBanner(`<div class="bn" style="--team:var(--text)"><div class="bn-kicker">FULL-TIME</div>
      <div class="bn-title">${esc(app.teams[app.home].name)} ${esc(app.snapshot?.score_str)} ${esc(app.teams[app.away].name)}</div></div>`, 60, 999));
}

function onState(s) {
  app.speed = s.speed;
  app.paused = s.paused;
  app.profileId = s.profile.id;
  app.present = s.present;
  app.awayBands = s.away_bands;
  app.snapshot = s.snapshot;
  app.timeline = s.timeline;
  app.cards = new Map(s.cards.map((c) => [c.moment_id, c]));
  app.notes = [...s.notifications].reverse();
  app.lineup = s.lineup;
  app.possession = s.snapshot.possession;
  renderControls(); renderScore(); renderProfiles(); renderPresence(); renderNotes(); renderCards(); drawTimeline();
}

/* ------------------------------------------------------------------ events → ball & players */

function isHome(team) { return team === app.home; }

function animateBall(x, y, ex, ey, realSeconds) {
  const wall = Math.min(0.9, Math.max(0.12, realSeconds / app.speed));
  app.ballAnim = { x0: x, y0: y, x1: ex, y1: ey, start: performance.now(), dur: wall * 1000 };
}

function snapBall(x, y) { animateBall(app.ball.x, app.ball.y, x, y, 0.15 * app.speed); }

function onEvent(e) {
  const team = e.team;
  switch (e.type) {
    case "pass": {
      app.possession = team;
      app.holder = null;
      const secs = e.distance_m / Math.max(5, e.ball_speed_kmh / 3.6);
      animateBall(e.x, e.y, e.end_x, e.end_y, secs);
      if (e.success) setTimeout(() => { app.holder = e.receiver; }, Math.min(900, (secs / app.speed) * 1000));
      break;
    }
    case "carry":
    case "sprint": {
      app.possession = team;
      app.holder = e.player;
      const dist = Math.hypot(e.end_x - e.x, e.end_y - e.y);
      animateBall(e.x, e.y, e.end_x, e.end_y, dist / Math.max(2, e.speed_kmh / 3.6));
      break;
    }
    case "shot": {
      app.possession = team;
      app.holder = null;
      const gx = isHome(team) ? L : 0;
      const gy = W / 2 + (e.outcome === "off_target" ? (Math.random() < 0.5 ? -6 : 6) : (Math.random() - 0.5) * 5);
      animateBall(e.x, e.y, gx, gy, 0.8);
      break;
    }
    case "possession_change":
      app.possession = e.to_team; app.holder = e.player; snapBall(e.x, e.y); break;
    case "throw_in": case "goal_kick": case "corner":
      app.possession = team; app.holder = e.player; snapBall(e.x, e.y); break;
    case "period_start":
      app.possession = team; app.holder = null; snapBall(L / 2, W / 2); break;
    case "goal":
      app.holder = null; break;
    case "substitution": {
      const lineup = app.lineup[team];
      const spot = e.spot || lineup[e.player_out];
      delete lineup[e.player_out];
      if (spot) lineup[e.player_in] = spot;
      app.pos[e.player_in] = app.pos[e.player_out];
      break;
    }
    case "card":
      if (e.color === "red") delete app.lineup[team][e.player];
      break;
    default:
      break;
  }
}

function playerTargets() {
  const poss = app.possession || app.home;
  const flip = !isHome(poss);
  const toFrame = (x, y) => (flip ? [L - x, W - y] : [x, y]);   // absolute ⇄ possessing team's frame
  const [bx, by] = toFrame(app.ball.x, app.ball.y);
  const out = {};
  for (const team of [app.home, app.away]) {
    for (const [pid, [sx, sy]] of Object.entries(app.lineup[team] || {})) {
      const gk = app.roster[pid]?.position === "GK";
      let x, y;
      if (team === poss) {
        if (gk) { x = sx + Math.max(0, bx - 50) * 0.1; y = sy; }
        else {
          x = Math.min(Math.max(sx + (bx - 45) * 0.45, 2), Math.min(95, Math.max(84, bx + 6)));
          y = sy + (by - sy) * 0.2;
        }
      } else {
        const mx = L - sx, my = W - sy;
        const pull = gk ? 0.04 : 0.3;
        x = mx + (bx - mx) * pull; y = my + (by - my) * pull;
      }
      const wobble = Math.sin(performance.now() / 900 + pid.length * 7 + sx) * 0.6;
      out[pid] = toFrame(x + wobble, y + wobble * 0.6);
    }
  }
  if (app.holder && out[app.holder]) out[app.holder] = [app.ball.x - 0.8, app.ball.y + 0.6];
  return out;
}

/* ------------------------------------------------------------------ drawing: pitch */

function sizeCanvas(c) {
  const r = c.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  if (c.width !== Math.round(r.width * dpr) || c.height !== Math.round(r.height * dpr)) {
    c.width = Math.round(r.width * dpr); c.height = Math.round(r.height * dpr);
  }
  return dpr;
}

function frame(now) {
  const dt = Math.min(0.1, (now - app.lastFrame) / 1000);
  app.lastFrame = now;
  if (app.ballAnim) {
    const a = app.ballAnim;
    const k = Math.min(1, (now - a.start) / a.dur);
    const ease = 1 - Math.pow(1 - k, 2);
    app.ball = { x: a.x0 + (a.x1 - a.x0) * ease, y: a.y0 + (a.y1 - a.y0) * ease };
    if (k >= 1) app.ballAnim = null;
  }
  const targets = playerTargets();
  const follow = 1 - Math.exp(-dt * (2.5 + app.speed * 0.25));
  for (const [pid, [tx, ty]] of Object.entries(targets)) {
    const p = app.pos[pid] || (app.pos[pid] = { x: tx, y: ty });
    p.x += (tx - p.x) * follow; p.y += (ty - p.y) * follow;
  }
  drawPitch(targets);
  expireOverlays(now);
  requestAnimationFrame(frame);
}

function drawPitch(targets) {
  const c = $("#pitch");
  const dpr = sizeCanvas(c);
  const ctx = c.getContext("2d");
  const cw = c.width, ch = c.height;
  const margin = 0.07;
  const scale = Math.min((cw * (1 - 2 * margin)) / L, (ch * (1 - 2 * margin) - 30 * dpr) / W);
  const ox = (cw - L * scale) / 2, oy = (ch - W * scale) / 2 + 14 * dpr;
  const X = (x) => ox + x * scale, Y = (y) => oy + (W - y) * scale;

  ctx.fillStyle = "#0b2a1b"; ctx.fillRect(0, 0, cw, ch);
  for (let i = 0; i < 12; i++) {           // mowing stripes
    ctx.fillStyle = i % 2 ? "#0f3322" : "#0d2f1f";
    ctx.fillRect(X((L / 12) * i), Y(W), (L / 12) * scale + 1, W * scale);
  }
  const grd = ctx.createRadialGradient(cw / 2, ch / 2, ch * 0.2, cw / 2, ch / 2, cw * 0.75);
  grd.addColorStop(0, "rgba(0,0,0,0)"); grd.addColorStop(1, "rgba(0,0,0,.45)");
  ctx.fillStyle = grd; ctx.fillRect(0, 0, cw, ch);

  ctx.strokeStyle = "rgba(255,255,255,.55)"; ctx.lineWidth = 1.4 * dpr;
  const rect = (x, y, w, h) => ctx.strokeRect(X(x), Y(y + h), w * scale, h * scale);
  rect(0, 0, L, W);
  ctx.beginPath(); ctx.moveTo(X(L / 2), Y(0)); ctx.lineTo(X(L / 2), Y(W)); ctx.stroke();
  ctx.beginPath(); ctx.arc(X(L / 2), Y(W / 2), 9.15 * scale, 0, Math.PI * 2); ctx.stroke();
  for (const left of [true, false]) {
    const bx = left ? 0 : L - 16.5, sx = left ? 0 : L - 5.5;
    rect(bx, W / 2 - 20.16, 16.5, 40.32);
    rect(sx, W / 2 - 9.16, 5.5, 18.32);
    const px = left ? 11 : L - 11;
    ctx.fillStyle = "rgba(255,255,255,.6)";
    ctx.beginPath(); ctx.arc(X(px), Y(W / 2), 2 * dpr, 0, Math.PI * 2); ctx.fill();
    ctx.beginPath();
    const a0 = left ? -0.93 : Math.PI - 0.93, a1 = left ? 0.93 : Math.PI + 0.93;
    ctx.arc(X(px), Y(W / 2), 9.15 * scale, a0, a1); ctx.stroke();
    ctx.fillStyle = "rgba(255,255,255,.18)";
    ctx.fillRect(left ? X(-2) : X(L), Y(W / 2 + 3.66), 2 * scale, 7.32 * scale);
  }

  // players
  const r = 1.55 * scale;
  ctx.font = `700 ${Math.round(r * 1.05)}px "Barlow Condensed", sans-serif`;
  ctx.textAlign = "center"; ctx.textBaseline = "middle";
  for (const pid of Object.keys(targets)) {
    const p = app.pos[pid]; const info = app.roster[pid];
    if (!p || !info) continue;
    const colour = app.teams[info.team].colour;
    const gk = info.position === "GK";
    ctx.fillStyle = "rgba(0,0,0,.35)";
    ctx.beginPath(); ctx.ellipse(X(p.x) + r * 0.25, Y(p.y) + r * 0.35, r, r * 0.8, 0, 0, Math.PI * 2); ctx.fill();
    ctx.fillStyle = gk ? "#e8edf3" : colour;
    ctx.beginPath(); ctx.arc(X(p.x), Y(p.y), r, 0, Math.PI * 2); ctx.fill();
    if (pid === app.holder) { ctx.strokeStyle = "#fff"; ctx.lineWidth = 2.2 * dpr; ctx.stroke(); }
    ctx.fillStyle = gk ? colour : "#07090d";
    ctx.fillText(String(info.number), X(p.x), Y(p.y) + 0.5);
  }
  // ball
  ctx.fillStyle = "rgba(0,0,0,.4)";
  ctx.beginPath(); ctx.arc(X(app.ball.x) + 2 * dpr, Y(app.ball.y) + 2 * dpr, 0.75 * scale, 0, Math.PI * 2); ctx.fill();
  ctx.fillStyle = "#ffffff";
  ctx.beginPath(); ctx.arc(X(app.ball.x), Y(app.ball.y), 0.75 * scale, 0, Math.PI * 2); ctx.fill();
}

/* ------------------------------------------------------------------ score bug & danger */

function clockText(s) {
  if (!s) return "00:00";
  const mm = String(s.minute).padStart(2, "0"), ss = String(s.second).padStart(2, "0");
  if (s.period === 1 && s.minute >= 45) return `45+${s.minute - 44}'`;
  if (s.period === 2 && s.minute >= 90) return `90+${s.minute - 89}'`;
  return `${mm}:${ss}`;
}

function renderScore() {
  const s = app.snapshot;
  if (!s) return;
  const bug = $("#scorebug");
  bug.querySelector(".home .sb-code").textContent = s.home;
  bug.querySelector(".away .sb-code").textContent = s.away;
  bug.querySelector(".sb-home").textContent = s.score[s.home];
  bug.querySelector(".sb-away").textContent = s.score[s.away];
  bug.querySelector(".home .sb-reds").innerHTML = "<i></i>".repeat(s.teams[s.home].red_cards);
  bug.querySelector(".away .sb-reds").innerHTML = "<i></i>".repeat(s.teams[s.away].red_cards);
  $("#clock").textContent = clockText(s);
  $("#btn-join").disabled = s.period === 2 && s.minute >= 60;
  $("#phone-clock").textContent = `${s.minute}'`;
  for (const side of ["home", "away"]) {
    const code = s[side], t = s.teams[code];
    const row = $(`#danger .danger-row.${side}`);
    row.querySelector(".dr-code").textContent = code;
    row.querySelector(".dr-bar i").style.width = `${Math.min(100, t.danger)}%`;
    row.querySelector(".dr-val").textContent = Math.round(t.danger);
    row.classList.toggle("hot", t.danger >= 55 && t.danger_slope > 0);
  }
}

function renderControls() {
  for (const b of document.querySelectorAll("#speeds button")) b.classList.toggle("on", Number(b.dataset.speed) === app.speed);
  $("#pause").textContent = app.paused ? "▶" : "❚❚";
}

/* ------------------------------------------------------------------ overlays */

function teamColour(team) { return app.teams[team]?.colour || "var(--text)"; }
function level() { return app.profiles.find((p) => p.id === app.profileId)?.level || "casual"; }

function showCue(cue) {
  const now = performance.now();
  const cur = app.overlays[cue.layer];
  if (cur && cur.until > now && cur.priority > cue.priority) return;
  const html = cueHtml(cue);
  if (!html) return;
  const wall = Math.max(MIN_WALL_S[cue.layer], (cue.t_out - cue.t_in) / app.speed);
  app.overlays[cue.layer] = { until: now + wall * 1000, priority: cue.priority, momentId: cue.data.moment_id };
  const el = $(`#ov-${cue.layer}`);
  el.classList.remove("out");
  el.innerHTML = html;
}

function showBanner(html, seconds, priority) {
  app.overlays.banner = { until: performance.now() + seconds * 1000, priority };
  const el = $("#ov-banner"); el.classList.remove("out"); el.innerHTML = html;
}

function expireOverlays(now) {
  for (const [layer, o] of Object.entries(app.overlays)) {
    if (o && o.until < now) {
      const el = $(`#ov-${layer}`);
      el.classList.add("out");
      app.overlays[layer] = null;
      setTimeout(() => { if (!app.overlays[layer]) el.innerHTML = ""; }, 320);
    }
  }
}

function sourceBadge(card) {
  if (!card || card.pending) return `<span class="badge pending">Analyst agent writing…</span>`;
  if (card.source === "llm") {
    const revised = card.attempts > 1 ? ` · revised ${card.attempts - 1}×` : "";
    return `<span class="badge">✓ Analyst → Verifier${revised}</span>`;
  }
  return `<span class="badge template">Template · verified facts</span>`;
}

function cueHtml(cue) {
  const d = cue.data;
  const team = `--team:${teamColour(d.team)}`;
  switch (cue.template) {
    case "player_tag": {
      const [first, ...rest] = d.player_name.split(" ");
      const stat = d.goals ? `${d.goals} goal${d.goals > 1 ? "s" : ""}` : `${d.passes_completed} passes completed`;
      return `<div class="lt" style="${team}"><div class="lt-num">${d.number}</div><div class="lt-body">
        <div class="lt-name">${esc(first)} <b>${esc(rest.join(" "))}</b></div>
        <div class="lt-meta">${esc(d.position)} · ${esc(app.teams[d.team].name)} · ${stat}</div></div></div>`;
    }
    case "pass_quality":
      return `<div class="tr" style="${team}"><div class="tr-kicker">PASS DIFFICULTY · ${esc(d.label.toUpperCase())}</div>
        <div class="tr-big">${d.difficulty}<span>/100</span></div><div class="bar"><i style="width:${d.difficulty}%"></i></div>
        <div class="tr-meta">${d.distance_m} m · ${Math.round(d.ball_speed_kmh)} km/h</div>
        <div class="tr-sub">${esc(d.player_name)} → ${esc(d.receiver_name)}</div></div>`;
    case "shot_speed": {
      const outcome = { goal: "GOAL", saved: "Saved", blocked: "Blocked", off_target: "Off target" }[d.outcome];
      const detail = level() === "analyst" ? `xG ${d.xg.toFixed(2)} · ${outcome}` : (d.xg >= 0.25 ? `Big chance · ${outcome}` : outcome);
      return `<div class="tr" style="${team}"><div class="tr-kicker">SHOT SPEED</div>
        <div class="tr-big">${d.shot_speed_kmh.toFixed(1)}<span>km/h</span></div>
        <div class="tr-meta">${esc(d.player_name)}</div><div class="tr-sub">${esc(detail)}</div></div>`;
    }
    case "sprint":
      return `<div class="tr" style="${team}"><div class="tr-kicker">TOP SPEED</div>
        <div class="tr-big">${d.speed_kmh.toFixed(1)}<span>km/h</span></div>
        <div class="tr-meta">${esc(d.player_name)} · ${d.distance_m} m sprint</div></div>`;
    case "danger":
      return `<div class="bn danger-bn" style="${team}"><div class="bn-kicker">DANGER ▲ ${esc(app.teams[d.team].name.toUpperCase())}</div>
        <div class="bn-title">${d.box_entries} box entries in ${Math.round(d.window_s / 60)} minutes</div>
        <div class="bn-why">Danger index ${d.danger}/100${d.main_channel ? ` · attacking down the ${d.main_channel}` : ""}</div></div>`;
    case "moment":
      return momentBanner(app.cards.get(d.moment_id) || d);
    default:
      return "";
  }
}

function momentBanner(card) {
  const goal = card.type === "goal";
  const title = card.headline || TYPE_LABEL[card.type];
  const why = card.why_it_matters ? `<div class="bn-why">${esc(card.why_it_matters)}</div>` : "";
  const score = goal && card.facts ? ` · ${card.facts.score_after}` : "";
  return `<div class="bn ${goal ? "goal" : ""}" style="--team:${teamColour(card.team)}">
    <div class="bn-kicker">${TYPE_LABEL[card.type] || ""} · ${card.minute}'${score}</div>
    <div class="bn-title">${esc(title)}</div>${why}<div class="bn-foot">${sourceBadge(card)}</div></div>`;
}

function refreshBannerCard(card) {
  const o = app.overlays.banner;
  if (o && o.momentId === card.moment_id) $("#ov-banner").innerHTML = momentBanner(card);
}

/* ------------------------------------------------------------------ studio feed */

function renderCards() {
  const list = [...app.cards.values()]
    .filter((c) => c.importance >= 50 && c.type !== "danger_peak")
    .sort((a, b) => b.t - a.t).slice(0, 3);
  $("#cards").innerHTML = list.length ? list.map((c) => `
    <article class="card" style="--team:${teamColour(c.team)}">
      <div class="card-kicker">${c.minute}' · ${TYPE_LABEL[c.type] || c.type}</div>
      <div class="card-title">${esc(c.headline)}</div>
      <div class="card-why">${esc(c.why_it_matters)}</div>
      <div>${sourceBadge(c)}</div>
    </article>`).join("") : `<div class="empty">Key moments will appear here as the Analyst writes them.</div>`;
}

/* ------------------------------------------------------------------ timeline */

function drawTimeline() {
  const c = $("#timeline");
  const dpr = sizeCanvas(c);
  const ctx = c.getContext("2d");
  const w = c.width, h = c.height, pad = 10 * dpr, mid = h * 0.52;
  const X = (t) => pad + (t / app.durationT) * (w - 2 * pad);
  ctx.clearRect(0, 0, w, h);

  // away bands
  const nowT = app.snapshot?.t || 0;
  for (const b of app.awayBands) {
    const x0 = X(b.from_t), x1 = X(b.to_t ?? nowT);
    ctx.fillStyle = "rgba(140,150,170,.16)"; ctx.fillRect(x0, 4 * dpr, Math.max(2, x1 - x0), h - 22 * dpr);
    ctx.save(); ctx.beginPath(); ctx.rect(x0, 4 * dpr, Math.max(2, x1 - x0), h - 22 * dpr); ctx.clip();
    ctx.strokeStyle = "rgba(140,150,170,.22)"; ctx.lineWidth = 1 * dpr;
    for (let x = x0 - h; x < x1; x += 7 * dpr) { ctx.beginPath(); ctx.moveTo(x, h); ctx.lineTo(x + h, 0); ctx.stroke(); }
    ctx.restore();
    ctx.fillStyle = "#9aa4b6"; ctx.font = `600 ${10 * dpr}px Inter, sans-serif`; ctx.textAlign = "left";
    ctx.fillText(b.late_join ? "NOT WATCHING" : "AWAY", x0 + 4 * dpr, 15 * dpr);
  }

  // axis, half-time, 15' ticks
  ctx.strokeStyle = "#2a3240"; ctx.lineWidth = 1 * dpr;
  ctx.beginPath(); ctx.moveTo(pad, mid); ctx.lineTo(w - pad, mid); ctx.stroke();
  ctx.fillStyle = "#6c768a"; ctx.font = `500 ${10 * dpr}px Inter, sans-serif`; ctx.textAlign = "center";
  const ht = app.timeline.find((e) => e.period === 2)?.t;
  for (let m = 0; m <= 90; m += 15) {
    const t = m <= 45 ? m * 60 : (ht ?? 2700) + (m - 45) * 60;
    ctx.fillText(`${m}'`, X(t), h - 4 * dpr);
  }

  // momentum (control difference) as mirrored bars
  const bw = Math.max(1.5 * dpr, (w - 2 * pad) / 100 - 1 * dpr);
  for (const e of app.timeline) {
    const diff = (e.control[app.home] ?? 0) - (e.control[app.away] ?? 0);
    const bh = Math.min(1, Math.abs(diff) / 0.5) * (mid - 18 * dpr);
    ctx.fillStyle = diff >= 0 ? app.teams[app.home].colour : app.teams[app.away].colour;
    ctx.globalAlpha = 0.75;
    ctx.fillRect(X(e.t), diff >= 0 ? mid - bh : mid, bw, bh);
  }
  ctx.globalAlpha = 1;

  // come-back alerts (this fan)
  for (const n of app.notes.filter((n) => n.kind === "come_back")) {
    const x = X(n.t);
    ctx.strokeStyle = "rgba(255,77,94,.7)"; ctx.setLineDash([3 * dpr, 3 * dpr]);
    ctx.beginPath(); ctx.moveTo(x, 8 * dpr); ctx.lineTo(x, h - 18 * dpr); ctx.stroke(); ctx.setLineDash([]);
    ctx.fillStyle = "#ff4d5e"; ctx.beginPath(); ctx.arc(x, 9 * dpr, 4 * dpr, 0, Math.PI * 2); ctx.fill();
  }

  // key moments
  for (const card of app.cards.values()) {
    const x = X(card.t), up = card.team === app.home;
    const y = card.team ? (up ? mid - 30 * dpr : mid + 30 * dpr) : mid;
    const col = card.team ? app.teams[card.team].colour : "#cfd6e2";
    if (card.type === "goal") {
      ctx.fillStyle = col; ctx.strokeStyle = "#fff"; ctx.lineWidth = 2 * dpr;
      ctx.beginPath(); ctx.arc(x, y, 6.5 * dpr, 0, Math.PI * 2); ctx.fill(); ctx.stroke();
    } else if (card.type === "red_card") {
      ctx.fillStyle = "#ff4d5e"; ctx.fillRect(x - 3.5 * dpr, y - 5 * dpr, 7 * dpr, 10 * dpr);
    } else if (card.type === "shape_change") {
      ctx.fillStyle = col; ctx.beginPath();
      ctx.moveTo(x, y - 6 * dpr); ctx.lineTo(x + 6 * dpr, y); ctx.lineTo(x, y + 6 * dpr); ctx.lineTo(x - 6 * dpr, y); ctx.fill();
    } else if (card.type === "big_chance") {
      ctx.strokeStyle = col; ctx.lineWidth = 2 * dpr; ctx.beginPath(); ctx.arc(x, y, 5 * dpr, 0, Math.PI * 2); ctx.stroke();
    } else if (card.type === "half_time") {
      ctx.strokeStyle = "#4b5566"; ctx.beginPath(); ctx.moveTo(x, 6 * dpr); ctx.lineTo(x, h - 18 * dpr); ctx.stroke();
    }
  }

  // now cursor
  ctx.strokeStyle = "#ffffff"; ctx.lineWidth = 1.5 * dpr;
  ctx.beginPath(); ctx.moveTo(X(nowT), 4 * dpr); ctx.lineTo(X(nowT), h - 16 * dpr); ctx.stroke();
}

/* ------------------------------------------------------------------ the phone */

function renderProfiles() {
  $("#profiles").innerHTML = app.profiles.map((p) => {
    const colour = p.club_id ? app.teams[p.club_id]?.colour : app.teams[app.roster[p.favourite_player_id]?.team]?.colour;
    return `<button class="profile ${p.id === app.profileId ? "on" : ""}" data-profile="${p.id}" role="tab"
      aria-selected="${p.id === app.profileId}"><span><i style="background:${colour}"></i>${esc(p.name)}</span>
      <small>${p.language.toUpperCase()} · ${p.level}</small></button>`;
  }).join("");
  const p = app.profiles.find((x) => x.id === app.profileId);
  if (!p) return;
  const who = p.club_id ? `supports <b>${esc(app.teams[p.club_id].name)}</b>`
    : `follows <b>${esc(app.roster[p.favourite_player_id]?.name)}</b> (${esc(app.roster[p.favourite_player_id]?.team)})`;
  $("#fan-card").innerHTML = `<b>${esc(p.name)}</b> ${who} · ${p.level === "analyst" ? "Analyst view" : "Casual view"} · ${LANG_LABEL[p.language]}`;
}

function renderPresence() {
  const el = $("#presence");
  const band = app.awayBands.at(-1);
  if (app.present) {
    el.className = "presence";
    el.innerHTML = `<i></i><span>Watching live</span>`;
  } else {
    el.className = "presence away";
    const since = band ? minuteAt(band.from_t) : "";
    el.innerHTML = `<i></i><span>Away since ${since}'<small>COMEBACK is watching the match for you</small></span>`;
  }
  $("#btn-away").disabled = !app.present;
  $("#btn-back").disabled = app.present;
  $("#away-veil").hidden = app.present;
}

function minuteAt(t) {
  const e = [...app.timeline].reverse().find((x) => x.t <= t);
  return e ? e.minute : Math.floor(t / 60);
}

function renderNotes() {
  const el = $("#notes");
  if (!app.notes.length) {
    el.innerHTML = `<div class="empty">Nothing yet. Leave the match and COMEBACK will watch it for you.</div>`;
    return;
  }
  el.innerHTML = app.notes.slice(0, 6).map((n) => `
    <div class="note ${n.kind}"><div class="note-head"><b>${n.kind === "come_back" ? "🔔 COME BACK" : "⚽ GOAL"}</b><span>${n.minute}'</span></div>
    <div class="note-text">${esc(n.text)}</div></div>`).join("");
}

function buzz() {
  const phone = $("#phone");
  phone.classList.remove("buzz"); void phone.offsetWidth; phone.classList.add("buzz");
  if (navigator.vibrate) navigator.vibrate(120);
}

function renderCatchup(c) {
  const d = c.delta || {};
  const title = c.late_join ? "The story so far" : `While you were away · ${d.away_minutes} min`;
  const chips = [
    `<span class="chip">${esc(d.score_then)} → <b>${esc(d.score_now)}</b></span>`,
    d.in_control_now ? `<span class="chip">In control: ${d.in_control_then && !c.late_join ? `${esc(d.in_control_then)} → ` : ""}<b>${esc(d.in_control_now)}</b></span>` : "",
    d.players_on_pitch_now ? `<span class="chip">${Object.entries(d.players_on_pitch_now).map(([t, n]) => `${esc(t)} ${n}`).join(" v ")}</span>` : "",
  ].join("");
  const badge = c.source === "llm"
    ? `<span class="badge">✓ Storyteller → Verifier${c.attempts > 1 ? ` · revised ${c.attempts - 1}×` : ""}</span>`
    : `<span class="badge template">Template · verified facts</span>`;
  const el = $("#catchup");
  el.hidden = false;
  el.innerHTML = `<div class="catchup-kicker"><span>PREVIOUSLY ON…</span><button aria-label="Close" onclick="hideCatchup()">×</button></div>
    <div class="catchup-title">${esc(title)}</div><div class="delta">${chips}</div>
    <div class="catchup-text">${esc(c.text)}</div>
    <div class="catchup-foot">${badge}${"speechSynthesis" in window ? `<button class="listen" id="listen">🔊 Listen</button>` : ""}</div>`;
  const listen = $("#listen");
  if (listen) listen.addEventListener("click", () => speak(c.text, c.language));
}

function speak(text, lang) {
  speechSynthesis.cancel();
  const u = new SpeechSynthesisUtterance(text);
  u.lang = { en: "en-GB", fr: "fr-FR", es: "es-ES" }[lang] || "en-GB";
  u.rate = 1.03;
  speechSynthesis.speak(u);
}

function hideCatchup() {
  if ("speechSynthesis" in window) speechSynthesis.cancel();
  const el = $("#catchup"); el.hidden = true; el.innerHTML = "";
}

boot();
