/* COMEBACK control room: boot, SSE stream, controls and the render loop. */

import { $, app, MATCH_ID, IS_DEMO, SPEEDS, post, newSessionId, applyEvent, step, emit, on as onMessage, profile } from "./state.js";
import {
  renderScore, renderTimecode, showCue, expireOverlays, refreshBanner, clearOverlays, put, favouriteTag, renderMetric,
  renderGazette, milestoneTag,
} from "./graphics.js";
import {
  renderData, renderRundown, drawTimeline, renderProfiles, renderPresence, renderNotes, renderCatchup, hideCatchup, buzz,
  initToast, toast, renderPrefs, renderVeiledCatchup,
} from "./panels.js";
import { drawTactical } from "./tactical.js";
import { initAgents } from "./agents.js";
import { initAudience } from "./audience.js";
import { initPairing } from "./pairing.js";
import { initFocus } from "./focus.js";
import { unlockSpeech } from "./voice.js";
import { isReplaying, buffer, playReplay, playVoice, interruptForLive, unlockAudio } from "./replay.js";
import { initPicker, openPicker } from "./picker.js";
import { initStory, startStory, exitStory, storyActive, storyClock } from "./story.js";
import { initStoryViews } from "./storyviews.js";
import { initFactCheck } from "./factcheck.js";
import { initDecisions } from "./decision.js";
import { initCues } from "./cues.js";

let program = null;          // 3D renderer, or null → 2D fallback on the PGM canvas
const LATE_JOIN = { reda: 60 }; // demo fans who join the match late (minute)
let pendingJoin = null;
let lastFrame = performance.now();
let lastSlow = 0;

async function boot() {
  const [match, profiles] = await Promise.all([
    fetch(`/api/match/${MATCH_ID}`).then((r) => r.json()),
    fetch(`/api/profiles?match_id=${MATCH_ID}`).then((r) => r.json()),
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
  document.body.classList.toggle("other-match", !IS_DEMO);
  for (const a of document.querySelectorAll("[data-overlays]")) a.href = `/api/overlays/${MATCH_ID}`;
  $("#bar-sub").textContent = IS_DEMO ? "DEMO MATCH · SCRIPTED STORYLINE · FICTIONAL CLUBS"
    : `UNSCRIPTED MATCH · ${app.teams[app.home].name.toUpperCase()} v ${app.teams[app.away].name.toUpperCase()}`;
  $(".lg-away-name").textContent = app.teams[app.away].name.toUpperCase();

  try {
    const { createProgram } = await import("./program3d.js");
    program = createProgram($("#pgm-canvas"));
  } catch (err) {
    console.warn("3D program unavailable, using the 2D camera:", err);
    $("#pgm-src").textContent = "CAM 2 · TACTICAL (3D UNAVAILABLE)";
  }
  buildControls();
  initAgents();
  initAudience();
  initPairing();
  initFocus();
  initFactCheck();
  initDecisions();
  initCues();
  initStoryViews();
  initToast();
  initPicker({ onPick: pick, onStory: playStory });
  initStory({ restart, setMode, setSpeed, pick, openPicker });
  setMode(new URLSearchParams(location.search).get("view") === "studio" ? "studio" : "fan");
  requestAnimationFrame(frame);
}

/** Called from a tap: unlock sound (Safari, iOS) and speech, then play the guided story. */
function playStory() {
  unlockSpeech();
  unlockAudio();
  startStory();
}

/** Watch as one demo fan: the first pick starts the match, later picks switch fan on the same match. */
async function pick(id) {
  unlockSpeech();
  unlockAudio();
  exitStory();
  const first = !app.es;
  app.profileId = id;
  pendingJoin = LATE_JOIN[id] ?? null;
  if (first) { app.speed = 10; connect(); return; }
  const s = app.snapshot;
  if (pendingJoin != null && s && s.period === 2 && s.minute >= pendingJoin) { restart(); return; }  // too late to join late
  hideCatchup();
  $("#gazette").hidden = true;
  await post(`profile?id=${id}`);
  joinIfLate();
}

function joinIfLate() {
  const s = app.snapshot;
  if (pendingJoin == null || !s) return;
  const minute = pendingJoin;
  pendingJoin = null;
  if (s.period === 1 || s.minute < minute) { hideCatchup(); post(`join?minute=${minute}`); }
}

function setMode(mode) {
  document.body.dataset.mode = mode;
  for (const b of document.querySelectorAll("#view button")) b.classList.toggle("on", b.dataset.view === mode);
  emit("view", { mode });
}

function setSpeed(speed) {
  app.speed = speed;
  renderControls();
  return post(`speed?value=${speed}`);
}

function buildControls() {
  $("#speeds").innerHTML = SPEEDS.map((s) => `<button data-speed="${s}">×${s}</button>`).join("");
  $("#speeds").addEventListener("click", (e) => {
    const s = Number(e.target.dataset.speed);
    if (!s) return;
    app.speed = s; renderControls(); post(`speed?value=${s}`);
  });
  $("#pause").addEventListener("click", () => { app.paused = !app.paused; renderControls(); post(`pause?paused=${app.paused}`); });
  $("#restart").addEventListener("click", () => { exitStory(); restart(); });
  $("#btn-away").addEventListener("click", () => app.present && post("away"));
  $("#btn-back").addEventListener("click", () => !app.present && post("back"));
  $("#btn-join").addEventListener("click", () => { hideCatchup(); post("join?minute=60"); });
  $("#view").addEventListener("click", (e) => { if (e.target.dataset.view) setMode(e.target.dataset.view); });
  $("#story-btn").addEventListener("click", playStory);
  $("#tk-open").addEventListener("click", () => setMode("studio"));
  $("#outage-btn").addEventListener("click", () => post(`outage?down=${!app.outage}`));
  $("#pref-for").addEventListener("click", (e) => { if (e.target.dataset.for) post(`settings?alert_for=${e.target.dataset.for}`); });
  $("#pref-night").addEventListener("change", (e) => post(`settings?night=${e.target.checked}`));
  $("#pref-spoilers").addEventListener("change", (e) => post(`settings?spoilers=${e.target.checked}`));
  onMessage("open-picker", openPicker);
  const clock = () => { $("#ph-time").textContent = storyClock() || new Date().toTimeString().slice(0, 5); };
  clock(); setInterval(clock, 1000);
  document.addEventListener("visibilitychange", () => {
    if (!$("#auto-away").checked || !app.es || storyActive()) return;   // the guided story drives presence itself
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
  Object.assign(app, { cards: new Map(), notes: [], timeline: [], awayBands: [], present: true, holder: null, pos: {}, topSpeed: {} });
  hideCatchup(); clearOverlays();
  $("#gazette").hidden = true;
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
    app.eventsById.set(e.id, e);                  // the decision chain cites events by id
    if (app.eventsById.size > 900) app.eventsById.delete(app.eventsById.keys().next().value);
    if (isReplaying()) {                        // the program feed is showing a replay
      buffer(e);
      if (e.type !== "goal") return;
      interruptForLive();                         // …unless a goal is scored live
      if (program) program.celebrate(e.team);
      return;
    }
    applyEvent(e);
    if (e.type === "goal" && program) program.celebrate(e.team);
    if (e.type === "sprint") app.topSpeed[e.player] = Math.max(app.topSpeed[e.player] || 0, e.speed_kmh);
    const fav = profile()?.favourite_player_id;           // player focus: the followed player is tagged all match
    if (fav && e.player === fav && ["pass", "carry", "shot"].includes(e.type) && performance.now() - app.lastFavTag > 20000) {
      app.lastFavTag = performance.now();
      favouriteTag(fav);
    }
  });
  on("snapshot", (s) => { app.snapshot = s; app.snapshotAt = performance.now(); renderScore(); renderMetric(profile()); });
  on("gazette", (g) => { renderGazette(g, profile()); renderCatchup({ ...g, late_join: false }); playVoice(g); });
  on("cue", (c) => { if (!isReplaying()) showCue(c); });   // live graphics wait during a replay
  on("card", (c) => {
    const isNew = !app.cards.has(c.moment_id);
    app.cards.set(c.moment_id, c); renderRundown(); refreshBanner(c);
    if (isNew && c.type === "milestone" && !isReplaying()) milestoneTag(c);
  });
  on("timeline", (t) => app.timeline.push(t));
  on("notification", (n) => {
    app.notes.unshift(n); renderNotes();
    if (!n.silent) { buzz(n.kind === "come_back"); toast(n); }   // night mode: delivered without a buzz
  });
  on("settings", (st) => { app.settings = st; renderPrefs(); });
  on("presence", (p) => {
    app.present = p.present; app.awayBands = p.away_bands;
    if (!p.present) hideCatchup();
    renderPresence();
  });
  on("catchup", (c) => {
    const d = c.delta || {};
    const spoiler = !app.settings?.spoilers && !c.late_join && d.score_then !== d.score_now && (c.replay || []).length;
    toast({ kind: "catchup", text: c.late_join ? "The story so far is ready on the phone." : "Your catch-up is ready on the phone." });
    if (spoiler) {                       // the score waits for the replay
      renderVeiledCatchup();
      let shown = false;
      const reveal = () => { if (shown) return; shown = true; renderCatchup(c); playVoice(c); };
      onMessage("replay-end", reveal);
      setTimeout(reveal, 30000);
    } else {
      renderCatchup(c);
      playVoice(c);
    }
    playReplay(c, program);
  });
  on("agent", () => {});         // forwarded to the AGENTS monitor through emit()
  on("crowd", (c) => { app.crowd = c; });   // also drawn by the AUD monitor
  on("device", () => {});        // phone paired / unpaired
  on("outage", (o) => renderOutage(o.down));
  on("end", () => put("banner", `<div class="bn" style="--team:#ecebe6"><div class="bn-k">FULL-TIME</div>
      <div class="bn-t">${app.teams[app.home].name} ${app.snapshot?.score_str ?? ""} ${app.teams[app.away].name}</div></div>`, 120, 999));
}

function onState(s) {
  Object.assign(app, {
    speed: s.speed, paused: s.paused, profileId: s.profile.id, present: s.present, awayBands: s.away_bands,
    snapshot: s.snapshot, snapshotAt: performance.now(), timeline: s.timeline, lineup: s.lineup,
    cards: new Map(s.cards.map((c) => [c.moment_id, c])), notes: [...s.notifications].reverse(),
    possession: s.snapshot.possession, crowd: s.crowd, settings: s.settings,
  });
  renderControls(); renderScore(); renderProfiles(); renderPresence(); renderNotes(); renderRundown(); renderData(); renderPrefs();
  renderMetric(profile());
  renderOutage(Boolean(s.outage));
  const fav = profile()?.favourite_player_id;               // sprints before a join or a seek were not streamed
  if (fav) {
    fetch(`/api/session/${app.session}/player/${fav}`).then((r) => r.json()).then((pl) => {
      app.topSpeed[fav] = Math.max(app.topSpeed[fav] || 0, pl.stats.top_speed_kmh || 0) || undefined;
      renderMetric(profile());
    }).catch(() => {});
  }
  if (program) program.setFavourite(profile()?.favourite_player_id || null);
  $("#btn-join").disabled = s.snapshot.period === 2 && s.snapshot.minute >= 60;
  joinIfLate();
}

/** Failure drill: the LLM is cut for this session; agents keep the show going on verified templates. */
function renderOutage(down) {
  app.outage = down;
  $("#outage-badge").hidden = !down;
  $("#outage-btn").classList.toggle("on", down);
  $("#outage-btn").textContent = down ? "⚡ RESTORE THE LLM" : "⚡ CUT THE LLM";
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
