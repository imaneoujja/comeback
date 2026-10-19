/* COMEBACK control room: boot, SSE stream, controls and the render loop. */

import { $, app, MATCH_ID, SPEEDS, post, newSessionId, applyEvent, step, emit } from "./state.js";
import { renderScore, renderTimecode, showCue, expireOverlays, refreshBanner, clearOverlays, put } from "./graphics.js";
import {
  renderData, renderRundown, drawTimeline, renderProfiles, renderPresence, renderNotes, renderCatchup, hideCatchup, buzz,
} from "./panels.js";
import { drawTactical } from "./tactical.js";

let program = null;          // 3D renderer, or null → 2D fallback on the PGM canvas
let lastFrame = performance.now();
let lastSlow = 0;

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
  $(".lg-home-name").textContent = app.teams[app.home].name.toUpperCase();
  $(".lg-away-name").textContent = app.teams[app.away].name.toUpperCase();

  try {
    const { createProgram } = await import("./program3d.js");
    program = createProgram($("#pgm-canvas"));
  } catch (err) {
    console.warn("3D program unavailable, using the 2D camera:", err);
    $("#pgm-src").textContent = "CAM 2 · TACTICAL (3D UNAVAILABLE)";
  }
  buildControls();
  connect();
  requestAnimationFrame(frame);
}

function buildControls() {
  $("#speeds").innerHTML = SPEEDS.map((s) => `<button data-speed="${s}">×${s}</button>`).join("");
  $("#speeds").addEventListener("click", (e) => {
    const s = Number(e.target.dataset.speed);
    if (!s) return;
    app.speed = s; renderControls(); post(`speed?value=${s}`);
  });
  $("#pause").addEventListener("click", () => { app.paused = !app.paused; renderControls(); post(`pause?paused=${app.paused}`); });
  $("#restart").addEventListener("click", restart);
  $("#btn-away").addEventListener("click", () => app.present && post("away"));
  $("#btn-back").addEventListener("click", () => !app.present && post("back"));
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
    if (document.hidden) { if (app.present) post("away"); } else if (!app.present) post("back");
  });
}

function renderControls() {
  for (const b of document.querySelectorAll("#speeds button")) b.classList.toggle("on", Number(b.dataset.speed) === app.speed);
  $("#pause").textContent = app.paused ? "PLAY" : "PAUSE";
}

function restart() {
  if (app.es) app.es.close();
  app.session = newSessionId();
  Object.assign(app, { cards: new Map(), notes: [], timeline: [], awayBands: [], present: true, holder: null, pos: {} });
  hideCatchup(); clearOverlays();
  connect();
}

/* ------------------------------------------------------------------ stream */

function connect() {
  const url = `/api/stream?match_id=${MATCH_ID}&session=${app.session}&profile=${app.profileId}&speed=${app.speed}`;
  const es = new EventSource(url);
  app.es = es;
  const on = (type, fn) => es.addEventListener(type, (m) => { const d = JSON.parse(m.data); fn(d); emit(type, d); });
  on("state", onState);
  on("event", (e) => {
    applyEvent(e);
    if (e.type === "goal" && program) program.celebrate(e.team);
  });
  on("snapshot", (s) => { app.snapshot = s; app.snapshotAt = performance.now(); renderScore(); });
  on("cue", showCue);
  on("card", (c) => { app.cards.set(c.moment_id, c); renderRundown(); refreshBanner(c); });
  on("timeline", (t) => app.timeline.push(t));
  on("notification", (n) => { app.notes.unshift(n); renderNotes(); buzz(); });
  on("presence", (p) => {
    app.present = p.present; app.awayBands = p.away_bands;
    if (!p.present) hideCatchup();
    renderPresence();
  });
  on("catchup", renderCatchup);
  on("end", () => put("banner", `<div class="bn" style="--team:#ecebe6"><div class="bn-k">FULL-TIME</div>
      <div class="bn-t">${app.teams[app.home].name} ${app.snapshot?.score_str ?? ""} ${app.teams[app.away].name}</div></div>`, 120, 999));
}

function onState(s) {
  Object.assign(app, {
    speed: s.speed, paused: s.paused, profileId: s.profile.id, present: s.present, awayBands: s.away_bands,
    snapshot: s.snapshot, snapshotAt: performance.now(), timeline: s.timeline, lineup: s.lineup,
    cards: new Map(s.cards.map((c) => [c.moment_id, c])), notes: [...s.notifications].reverse(),
    possession: s.snapshot.possession,
  });
  renderControls(); renderScore(); renderProfiles(); renderPresence(); renderNotes(); renderRundown(); renderData();
  $("#btn-join").disabled = s.snapshot.period === 2 && s.snapshot.minute >= 60;
}

/* ------------------------------------------------------------------ render loop */

function frame(now) {
  const dt = Math.min(0.1, (now - lastFrame) / 1000);
  lastFrame = now;
  step(dt);
  if (program) program.render(dt); else drawTactical($("#pgm-canvas"));
  drawTactical($("#tactical"), { numbers: false });
  renderTimecode(now);
  expireOverlays(now);
  if (now - lastSlow > 250) {            // slower monitors: 4 Hz is plenty
    lastSlow = now;
    drawTimeline();
    renderData();
    const s = app.snapshot;
    if (s) $("#btn-join").disabled = s.period === 2 && s.minute >= 60;
  }
  requestAnimationFrame(frame);
}

boot();
