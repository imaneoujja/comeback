/* COMEBACK: boot, the setup screen, the SSE stream, controls and the render loop.
 * Two views of the same engine: a FAN (the TV and a companion panel to pair a phone) and a
 * STUDIO (the broadcaster's control room). The setup screen decides which, and for whom. */

import { $, app, SPEEDS, post, newSessionId, applyEvent, step, emit, on as onMessage, profile, fanLabel, fanTeam,
  teamColour, isStudio, LANG_NAME } from "./state.js";
import {
  renderScore, renderTimecode, showCue, expireOverlays, refreshBanner, clearOverlays, put, favouriteTag, renderMetric,
  renderGazette, milestoneTag, flashStat, statShowing,
} from "./graphics.js";
import {
  renderData, drawTimeline, renderPresence, renderNotes, renderCatchup, hideCatchup, initToast, notify,
  renderPrefs,
} from "./panels.js";
import { drawTactical } from "./tactical.js";
import { initPairing } from "./pairing.js";
import { unlockSpeech } from "./voice.js";
import { isReplaying, buffer, playReplay, playVoice, interruptForLive, unlockAudio, cancelReplay, stopVoice } from "./replay.js";
import { initSetup, openSetup, liveMatch } from "./setup.js";
import { initAutoplay, startAutoplay, stopAutoplay, autoplayActive } from "./autoplay.js";
import { initCues } from "./cues.js";
import { initStudio } from "./studio.js";
import { initMissed, showMissed, hideMissed } from "./missed.js";

let program = null;          // 3D renderer, or null → 2D fallback on the PGM canvas
let programFor = null;       // the fixture the 3D stadium is dressed for
let pendingStart = null;     // what to do once the stream is open: "away" | "join" | "seek" | null
let pendingCard = null;      // a catch-up card waiting for its replay to end
let missedPlan = null;       // the return screen, shown once the voice-over has finished
let voicePlaying = false;
let catchupClock = null;     // timing the current catch-up (replay + voice-over) for the receipt
const MAX_CATCHUP_S = 120;
const MISSED_AFTER_READING_MS = 12000;   // no voice-over: time to read the card first
let lastFrame = performance.now();
let lastSlow = 0;
const matches = new Map();

async function boot() {
  buildControls();
  initPairing();
  initCues();
  initStudio();
  initToast();
  initMissed();
  initAutoplay({ setSpeed });
  requestAnimationFrame(frame);
  await initSetup({ getMatch, onStart: start, onNav: (mode) => {
    for (const b of document.querySelectorAll("#product-nav button")) b.classList.toggle("on", b.dataset.nav === mode);
  } });
}

function getMatch(id) {
  if (!matches.has(id)) matches.set(id, fetch(`/api/match/${encodeURIComponent(id)}`).then((r) => r.json()));
  return matches.get(id);
}

/** Load a fixture: teams, rosters, colours. */
async function useMatch(id) {
  const match = await getMatch(id);
  Object.assign(app, { matchId: id, match, durationT: match.duration_t, home: match.home.id, away: match.away.id, teams: {}, roster: {} });
  for (const side of ["home", "away"]) {
    const club = match[side];
    app.teams[club.id] = { ...club, isHome: side === "home" };
    for (const p of club.players) app.roster[p.id] = { ...p, team: club.id };
  }
  document.documentElement.style.setProperty("--home", app.teams[app.home].colour);
  document.documentElement.style.setProperty("--away", app.teams[app.away].colour);
  $(".lg-home-name").textContent = app.teams[app.home].name.toUpperCase();
  $(".lg-away-name").textContent = app.teams[app.away].name.toUpperCase();
  for (const a of document.querySelectorAll("[data-overlays]")) a.href = `/api/overlays/${id}`;
}

/** The 3D stadium is dressed in the fixture's colours: a new fixture gets a new one. */
async function ensureProgram() {
  if (programFor === app.matchId) return;
  const old = $("#pgm-canvas");
  if (programFor) { const fresh = old.cloneNode(false); old.replaceWith(fresh); }
  programFor = app.matchId;
  try {
    const { createProgram } = await import("./program3d.js");
    program = createProgram($("#pgm-canvas"));
  } catch (err) {
    console.warn("3D program unavailable, using the 2D camera:", err);
    program = null;
    $("#pgm-src").textContent = "CAM 2 · TACTICAL (3D UNAVAILABLE)";
  }
}

/** From the setup screen's START (a click: sound can be unlocked here for Safari and iOS). */
async function start(cfg) {
  unlockSpeech();
  unlockAudio();
  const prev = app.config;
  app.config = cfg;
  setMode(cfg.mode);
  const sameRun = app.es && prev && cfg.mode === "fan" && prev.mode === "fan" && prev.match === cfg.match;
  if (sameRun) {                      // same match, same moment: only the fan changes (language, side, style, metric)
    stopAutoplay();
    clearReturnScreen();
    $("#gazette").hidden = true;
    await post(`fan?${fanQuery(cfg)}`);
    return;
  }
  await useMatch(cfg.match);
  await ensureProgram();
  restart(cfg.mode === "studio" ? "seek" : "join");   // a live match: you join it where it is
}

function fanQuery(cfg) {
  const q = cfg.mode === "studio" ? { side: "home", lang: "en", level: "analyst" }
    : { side: cfg.side, lang: cfg.lang, level: cfg.level, metric: cfg.metric, ...(cfg.player ? { player: cfg.player } : {}) };
  return new URLSearchParams(q).toString();
}

function setMode(mode) {
  document.body.dataset.mode = mode;
  const studio = mode === "studio";
  $("#tl-src").textContent = studio ? "MATCH TIMELINE · MOMENTUM · KEY MOMENTS · AUDIENCE CALL-BACKS"
    : "MATCH TIMELINE · MOMENTUM · KEY MOMENTS · YOUR CALL-BACKS";
  $("#lg-alert").textContent = studio ? "AUDIENCE CALL-BACK" : "YOUR CALL-BACK";
  emit("view", { mode });
}

function setSpeed(speed) {
  app.speed = speed;
  renderControls();
  return post(`speed?value=${speed}`);
}

function buildControls() {
  $("#speeds").innerHTML = SPEEDS.map((s) => `<button data-speed="${s}">×${s}</button>`).join("");
  $("#speeds").addEventListener("click", (e) => { const s = Number(e.target.dataset.speed); if (s) setSpeed(s); });
  $("#pause").addEventListener("click", () => { app.paused = !app.paused; renderControls(); post(`pause?paused=${app.paused}`); });
  $("#restart").addEventListener("click", () => restart(null));               // from kick-off
  $("#autoplay-btn").addEventListener("click", () => { closeDemo(); restart("autoplay"); });
  $("#jump-go").addEventListener("click", () => { const m = Number($("#jump-min").value); if (m > 0) post(`seek?minute=${m}`); });
  $("#fan-chip").addEventListener("click", () => openSetup("fan"));
  $("#product-nav").addEventListener("click", (e) => { if (e.target.dataset.nav) openSetup(e.target.dataset.nav); });
  $("#demo-btn").addEventListener("click", () => ($("#demo").hidden ? openDemo() : closeDemo()));
  $("#demo-x").addEventListener("click", closeDemo);
  document.addEventListener("keydown", (e) => {
    if (e.key.toLowerCase() !== "d" || e.metaKey || e.ctrlKey || ["INPUT", "SELECT", "TEXTAREA"].includes(e.target.tagName)) return;
    if ($("#demo").hidden) openDemo(); else closeDemo();
  });
  $("#cp-quiet-go").addEventListener("click", () => post("settings?alert_for=good"));
  $("#btn-away").addEventListener("click", () => { stopAutoplay(); if (app.present) post("away"); });
  $("#btn-back").addEventListener("click", () => { stopAutoplay(); if (!app.present) post("back"); });
  $("#outage-btn").addEventListener("click", () => post(`outage?down=${!app.outage}`));
  $("#pref-for").addEventListener("click", (e) => { if (e.target.dataset.for) post(`settings?alert_for=${e.target.dataset.for}`); });
  $("#pref-night").addEventListener("change", (e) => post(`settings?night=${e.target.checked}`));
  $("#pref-spoilers").addEventListener("change", (e) => post(`settings?spoilers=${e.target.checked}`));
  document.addEventListener("visibilitychange", () => {     // switching tab = leaving the match
    if (!app.es || isStudio() || autoplayActive() || document.body.classList.contains("configuring")) return;
    if (document.hidden) { if (app.present) post("away"); } else if (!app.present) post("back");
  });
  onMessage("replay-end", () => {               // the catch-up card follows the replay
    if (!pendingCard) return;
    const { c, voice } = pendingCard;
    pendingCard = null;
    renderCatchup(c);
    if (voice) playVoice(c);
    planMissed(c);
  });
  onMessage("replay-end", () => { if (catchupClock) { catchupClock.replay = true; stopCatchupClock(); } });
  onMessage("voice", ({ playing }) => {
    if (catchupClock && playing) catchupClock.started = true;
    if (catchupClock && !playing && catchupClock.started) { catchupClock.voice = true; stopCatchupClock(); }
    voicePlaying = playing;
    if (!playing && missedPlan?.waitVoice) { missedPlan.waitVoice = false; missedPlan.timer = setTimeout(toMissed, 1500); }
  });
  onMessage("show-missed", toMissed);
  onMessage("show-story", () => { if (app.lastCatchup) renderCatchup(app.lastCatchup); });
}

/** The receipt's "caught up in X seconds": from the catch-up's arrival to the end of its replay and voice. */
function stopCatchupClock(force = false) {
  const clock = catchupClock;
  if (!clock || (!force && !(clock.replay && clock.voice))) return;
  catchupClock = null;
  app.catchupSeconds += Math.min(MAX_CATCHUP_S, (performance.now() - clock.start) / 1000);
}

/** After the story (card + voice), the TV turns to "What you missed". */
function planMissed(c) {
  clearTimeout(missedPlan?.timer);
  missedPlan = c.missed?.players?.length ? { c, waitVoice: voicePlaying } : null;
  if (missedPlan && !voicePlaying) missedPlan.timer = setTimeout(toMissed, MISSED_AFTER_READING_MS);
}

function toMissed() {
  const plan = missedPlan;
  clearTimeout(plan?.timer);
  missedPlan = null;
  const c = plan?.c || app.lastCatchup;
  if (!c || (plan && $("#catchup").hidden)) return;   // the fan closed the card: leave the match alone
  if (showMissed(c.missed)) $("#catchup").hidden = true;
}

function clearReturnScreen() {
  clearTimeout(missedPlan?.timer);
  missedPlan = null;
  hideMissed();
  hideCatchup();
}

function renderControls() {
  for (const b of document.querySelectorAll("#speeds button")) b.classList.toggle("on", Number(b.dataset.speed) === app.speed);
  $("#pause").textContent = app.paused ? "PLAY" : "PAUSE";
}

function openDemo() { $("#demo").hidden = false; $("#demo-btn").classList.add("on"); }
function closeDemo() { $("#demo").hidden = true; $("#demo-btn").classList.remove("on"); }

/** A new session on the same match. ``then``: "join" (live, the story so far), "seek" (studio, live),
 * "autoplay" (the demo scenario) or null (from kick-off). */
function restart(then = null) {
  if (!app.config) return;
  if (app.es) app.es.close();
  stopAutoplay();
  cancelReplay();
  stopVoice();
  app.session = newSessionId();
  Object.assign(app, { cards: new Map(), notes: [], timeline: [], awayBands: [], present: true, holder: null, pass: null, pos: {}, topSpeed: {},
    eventsById: new Map(), crowd: null, speed: 10 });
  pendingCard = null;
  app.lastCatchup = null;
  catchupClock = null;
  app.catchupSeconds = 0;
  clearReturnScreen(); clearOverlays();
  $("#gazette").hidden = true;
  pendingStart = then;
  connect();
}

/* ------------------------------------------------------------------ stream */

function connect() {
  const url = `/api/stream?match_id=${encodeURIComponent(app.matchId)}&session=${app.session}&${fanQuery(app.config)}&speed=${app.speed}`;
  const es = new EventSource(url);
  app.es = es;
  const on = (type, fn) => es.addEventListener(type, (m) => { const d = JSON.parse(m.data); fn(d); emit(type, d); });
  on("state", onState);
  on("event", (e) => {
    app.eventsById.set(e.id, e);                  // decision chains cite events by id
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
  on("snapshot", (s) => { app.snapshot = s; app.snapshotAt = performance.now(); renderScore(); renderMetric(profile()); flashStats(s); });
  on("gazette", (g) => {
    if (isStudio()) return;
    stopCatchupClock(true);
    clearReturnScreen();
    renderGazette(g, profile(), app.catchupSeconds);
    playVoice(g);
  });
  on("cue", (c) => { if (!isReplaying()) showCue(c); });   // live graphics wait during a replay
  on("card", (c) => {
    const isNew = !app.cards.has(c.moment_id);
    app.cards.set(c.moment_id, c); refreshBanner(c);
    if (isNew && c.type === "milestone" && !isReplaying()) milestoneTag(c);
    if (isNew && c.type === "momentum_swing" && !isReplaying()) flashStat("control", 7);
  });
  on("timeline", (t) => app.timeline.push(t));
  on("notification", (n) => {
    app.notes.unshift(n); renderNotes();
    if (!n.silent) notify(n);                     // night mode: delivered without a buzz
  });
  on("settings", (st) => { app.settings = st; renderPrefs(); renderQuiet(); });
  on("presence", (p) => {
    app.present = p.present; app.awayBands = p.away_bands;
    if (!p.present) { stopCatchupClock(true); clearReturnScreen(); pendingCard = null; }
    renderPresence();
  });
  on("catchup", onCatchup);
  on("crowd", (c) => { app.crowd = c; });   // drawn by the AUD, DECISIONS and PERSONALIZE monitors
  on("outage", (o) => renderOutage(o.down));
  on("end", () => put("banner", `<div class="bn" style="--team:#ecebe6"><div class="bn-k">FULL-TIME</div>
      <div class="bn-t">${app.teams[app.home].name} ${app.snapshot?.score_str ?? ""} ${app.teams[app.away].name}</div></div>`, 120, 999));
  for (const type of ["agent", "device"]) on(type, () => {});   // forwarded to the AGENTS monitor and the pairing panel
}

/** "Previously on…": the TV replays what was missed, then the card; the voice tells the story. */
function onCatchup(c) {
  clearReturnScreen();
  app.lastCatchup = c;
  const d = c.delta || {};
  const clips = (c.replay || []).filter((clip) => clip.events.length);
  stopCatchupClock(true);
  catchupClock = { start: performance.now(), replay: !clips.length || !program, voice: false, started: false };
  if (!clips.length || !program) { renderCatchup(c); playVoice(c); planMissed(c); return; }
  const spoiler = !app.settings?.spoilers && !c.late_join && d.score_then !== d.score_now;
  if (!spoiler) playVoice(c);                    // the voice-over runs over the replay…
  pendingCard = { c, voice: spoiler };           // …unless it would give the score away before the replay does
  playReplay(c, program);
}

function onState(s) {
  Object.assign(app, {
    speed: s.speed, paused: s.paused, fan: s.profile, present: s.present, awayBands: s.away_bands,
    snapshot: s.snapshot, snapshotAt: performance.now(), timeline: s.timeline, lineup: s.lineup,
    cards: new Map(s.cards.map((c) => [c.moment_id, c])), notes: [...s.notifications].reverse(),
    possession: s.snapshot.possession, crowd: s.crowd, settings: s.settings,
  });
  renderControls(); renderScore(); renderFanChip(); renderPresence(); renderNotes(); renderData(); renderPrefs();
  renderMetric(profile());
  renderOutage(Boolean(s.outage));
  const fav = profile()?.favourite_player_id;               // sprints before a join or a seek were not streamed
  if (fav) {
    fetch(`/api/session/${app.session}/player/${fav}`).then((r) => r.json()).then((pl) => {
      app.topSpeed[fav] = Math.max(app.topSpeed[fav] || 0, pl.stats.top_speed_kmh || 0) || undefined;
      renderMetric(profile());
    }).catch(() => {});
  }
  if (program) program.setFavourite(fav || null);
  const todo = pendingStart;
  pendingStart = null;
  const minute = app.config.liveMinute || 0;
  if (todo === "autoplay") startAutoplay();
  else if (todo === "join" && minute) post(`join?minute=${minute}`);
  else if (todo === "seek" && minute) post(`seek?minute=${minute}`);
  renderQuiet();
}

function renderFanChip() {
  const m = app.match;
  const fixture = m ? `${m.home.name} v ${m.away.name}`.toUpperCase() : "";
  $("#bar-sub").textContent = fixture;
  const p = profile();
  if (!p || isStudio()) return;
  $("#fan-chip").innerHTML = `<i style="background:${teamColour(fanTeam(p))}"></i>${fanLabel(p).toUpperCase()} · ${LANG_NAME[p.language].toUpperCase()}
    · ${p.level.toUpperCase()}<span>CHANGE</span>`;
}

/** When a stat graphic has something to say: danger when a side is pushing, then now and then the
 * fan's own metric and (analysts) control vs chaos. Wall-clock spacing keeps the screen clean. */
const lastFlash = { danger: 0, metric: 0, control: 0 };
function flashStats(s) {
  if (isReplaying()) return;
  const now = performance.now();
  const pushing = [s.home, s.away].some((c) => s.teams[c].danger >= 44 && s.teams[c].danger_slope > 0);
  if (pushing && now - lastFlash.danger > 25000) { lastFlash.danger = now; flashStat("danger", 7); return; }
  if (statShowing()) return;
  if (profile()?.focus_metric && now - lastFlash.metric > 60000) { lastFlash.metric = now; flashStat("metric", 6); return; }
  if (profile()?.level === "analyst" && now - lastFlash.control > 90000) { lastFlash.control = now; flashStat("control", 6); }
}

/** A quiet match: offer "only call me if this match gets good". */
function renderQuiet() {
  $("#cp-quiet").hidden = isStudio() || !liveMatch(app.matchId)?.quiet || app.settings?.alert_for === "good";
}

/** Failure drill: the LLM is cut for this session; agents keep the show going on verified templates. */
function renderOutage(down) {
  app.outage = down;
  $("#outage-badge").hidden = !down;
  $("#outage-btn").classList.toggle("on", down);
  $("#outage-btn").textContent = down ? "RESTORE THE LLM" : "SIMULATE LLM OUTAGE";
}

/* ------------------------------------------------------------------ render loop */

function frame(now) {
  const dt = Math.min(0.1, (now - lastFrame) / 1000);
  lastFrame = now;
  if (app.snapshot) {
    step(dt);
    if (program) program.render(dt); else drawTactical($("#pgm-canvas"));
    renderTimecode(now);
    expireOverlays(now);
    if (now - lastSlow > 250) {            // slower monitors: 4 Hz is plenty
      lastSlow = now;
      drawTimeline();
      renderData();
    }
  }
  requestAnimationFrame(frame);
}

boot();
