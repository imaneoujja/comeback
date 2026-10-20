/* The bar above the match.
 *
 * Story mode is a guided, captioned run of the demo in three acts:
 *   1. PITCHSIDE — Omar leaves at 63' for a kids' match next door; the TV is off but the
 *      engine keeps ingesting; the phone buzzes twice, each time with its decision chain.
 *   2. LIVING ROOM — Omar is back at 70.5': replay + neural voice, the 71' goal live, then
 *      the same moment as three different fans get it.
 *   3. BACKSTAGE — the STUDIO view: agents and overlay cues, a real Verifier catch at 81',
 *      the LLM cut live (templates keep the show on air), the audience and the cost.
 * A pipeline strip (INGEST → INTERPRET → EXPLAIN → RENDER → PERSONALIZE) lights the
 * stages each step shows. The story only drives the normal controls (seek, schedule,
 * speed, outage): everything on screen is the real system at work.
 *
 * Outside the story the bar is a guide: what this viewer can usefully do right now. */

import { $, app, MATCH_ID, post, on, emit, profile, esc, teamName } from "./state.js";
import { showPitchside, pitchsideDecision, showPersonalize } from "./storyviews.js";

const STEPS = 12;
const STAGES = ["INGEST", "INTERPRET", "EXPLAIN", "RENDER", "PERSONALIZE"];
const ACTS = { 1: "ACT 1 · PITCHSIDE", 2: "ACT 2 · LIVING ROOM", 3: "ACT 3 · BACKSTAGE" };
const LEAVE_AT = 63, BACK_AT = 70.5;   // the precomputed demo window (verified LLM text + neural voice)
const FACT_CHECK_FROM = 80.3;          // just before the 81' big chance, whose first draft the Verifier rejects
const OUTAGE_FROM = 84.2;              // just before the 84' goal: its card is written while the LLM is cut
const KICK_OFF_MIN = 15 * 60;          // a Saturday, 3 p.m. kick-off
const HALF_TIME_MIN = 15;
const SKIP_TO = 59.5;
const VISION = "The future of football isn't more screens. It's a match that fits your life.";
let run = null;                        // the story being played, or null
let storySession = null;               // the session the story played in (its phone shows the story's clock)
let hooks = {};
let scale = null;
let shown = "";                        // the hint currently on screen (re-rendered only when it changes)

export const storyActive = () => Boolean(run);
export const storyStep = () => run?.step ?? 0;

/** "16:05" on the story's Saturday afternoon, or null outside the story. */
export function storyClock() {
  const s = app.snapshot;
  if (!s || storySession !== app.session || app.profileId !== "omar") return null;
  const minutes = KICK_OFF_MIN + Math.floor(s.t / 60) + (s.period === 2 ? HALF_TIME_MIN : 0);
  return `${String(Math.floor(minutes / 60) % 24).padStart(2, "0")}:${String(minutes % 60).padStart(2, "0")}`;
}

/** ``h``: { restart(), setMode(mode), setSpeed(speed), pick(profileId), openPicker() } */
export function initStory(h) {
  hooks = h;
  on("state", () => { if (run && !run.seeked) seekToStart(); else hint(true); });
  on("presence", (pr) => (run ? onPresence(pr) : hint(true)));
  on("catchup", () => hint(true));
  on("catchup-closed", () => hint(true));
  on("gazette", () => hint(true, "final"));
  on("snapshot", () => { if (!run) hint(); });
  on("notification", onNotification);
  on("event", onEvent);
  on("cue", (c) => { if (run && c.template === "shot_speed" && c.data.outcome === "goal" && !run.shot) run.shot = c.data; });
  on("card", onCard);
  on("agent-shown", onAgent);
  $("#storybar").addEventListener("click", (e) => {
    const b = e.target.closest("[data-act]");
    if (b) act(b.dataset.act);
  });
  fetch(`/api/scale/${MATCH_ID}`).then((r) => r.json()).then(({ curve }) => { scale = curve.at(-1); }).catch(() => {});
}

export function startStory() {
  if (run) cleanUp();
  run = { step: 0, seeked: false, calls: [], back: false, goal: false, timers: [] };
  document.body.classList.add("story-on");
  hooks.setMode("fan");
  app.profileId = "omar";
  app.speed = 40;
  hooks.restart();
  storySession = app.session;
  caption(1, 1, ["INGEST", "INTERPRET"], `<b>Meet Omar</b>, an Emberfield fan who reads French and likes the numbers.
    59': Emberfield are losing 0‑2. Every pass, shot and tackle streams into COMEBACK's match engine.`);
}

export function exitStory() {
  if (!run) return;
  cleanUp();
  hooks.setSpeed(10);
  hint(true);
}

function cleanUp() {
  run.timers.forEach(clearTimeout);
  clearTimeout(run.giveUp);
  if (run.outage) post("outage?down=false");
  run = null;
  document.body.classList.remove("story-on");
  showPitchside(false);
  showPersonalize(null);
}

const later = (ms, fn) => run.timers.push(setTimeout(() => run && fn(), ms));
const fmt = (n) => Number(n).toLocaleString("en-US");

async function seekToStart() {
  run.seeked = true;
  await post("seek?minute=59");
  // the server applies the absence at exact minutes: the story never depends on how fast this browser reacts
  await post(`schedule?away=${LEAVE_AT}&back=${BACK_AT}`);
  await hooks.setSpeed(40);
}

/* ------------------------------------------------------------------ act 1 · pitchside */

function onPresence({ present }) {
  if (!present && run.step === 1) {
    showPitchside(true);
    hooks.setSpeed(20);
    caption(2, 1, ["INGEST", "INTERPRET"], `${LEAVE_AT}' · A kids' match is starting next door. <b>Omar puts the phone away
      and goes pitchside.</b> The TV is off; COMEBACK keeps reading every event.`);
  } else if (present && run.step >= 2 && !run.back) {
    livingRoom();
  }
}

function onNotification(n) {
  if (!run || n.kind !== "come_back") return;
  run.calls.push(n);
  pitchsideDecision(n);
  if (run.calls.length === 1) {
    caption(3, 1, ["INTERPRET", "EXPLAIN"], `${n.minute}' · ${esc(teamName(n.team))} are pushing. <b>One buzz, with the reason.</b>
      Here is how the Watcher decided: the events, the state, the insight, and why Omar, why now.`);
  } else {
    caption(4, 1, ["INTERPRET", "EXPLAIN"], `${n.minute}' · <b>A second buzz, before anything has happened.</b>
      Omar walks back from the touchline.`);
    hooks.setSpeed(10);
  }
}

/* ------------------------------------------------------------------ act 2 · living room */

function livingRoom() {
  run.back = true;
  showPitchside(false);
  caption(5, 2, ["EXPLAIN", "RENDER", "PERSONALIZE"], `<b>Omar is home.</b> The TV replays what was missed while a neural voice
    explains what changed: in French, from Emberfield's side.`);
  hooks.setSpeed(1);                // real time: the voice-over ends just before the next goal
}

function onEvent(e) {
  if (!run || !run.back || run.goal || e.type !== "goal") return;
  run.goal = true;
  caption(6, 2, ["RENDER"], `${e.minute}' · <b>GOAL, seen live.</b> Broadcast graphics (shot speed, xG) and a verified
    "why it matters" card. The phone confirms: COMEBACK called it two minutes ahead.`);
  later(8000, () => {
    showPersonalize(run.calls.at(-1), run.shot);
    caption(7, 2, ["PERSONALIZE"], `<b>Same moment, three fans.</b> Omar (analyst, French), Sofia (casual, English, the other
      side) and Reda (Spanish, player mode) get different words, depth, side and metric. The facts are the same.`);
    later(10000, backstage);
  });
}

/* ------------------------------------------------------------------ act 3 · backstage */

function backstage() {
  showPersonalize(null);
  hooks.setMode("studio");
  caption(8, 3, ["EXPLAIN", "RENDER"], `<b>Backstage.</b> Four agents share one match brain. CUES is timed JSON a broadcast
    renderer can consume; DECISIONS keeps every call-back's reasoning.`);
  emit("focus", { id: "cues", seconds: 6 });
  later(6000, async () => {
    emit("focus", { id: "agents", seconds: 12 });
    await post(`seek?minute=${FACT_CHECK_FROM}`);
    await hooks.setSpeed(5);
    if (run) run.giveUp = setTimeout(cutTheLlm, 25000);  // never stall if no rejection shows up
  });
}

function onAgent(s) {
  if (!run || run.step !== 8 || s.step !== "rejected" || !s.draft || run.checked) return;
  run.checked = s.label;
  clearTimeout(run.giveUp);
  emit("focus", { id: "pgm", seconds: 9 });
  caption(9, 3, ["EXPLAIN"], `${esc(s.label)} · <b>The Analyst got a fact wrong. The Verifier caught it</b> and sent it back:
    only a corrected card can go on air. No fan saw the mistake.`);
  later(9000, cutTheLlm);
}

async function cutTheLlm() {
  if (!run || run.step >= 10) return;
  caption(10, 3, STAGES, `<b>Cut the LLM.</b> Every agent call now fails, like a real outage. The next card still goes on air,
    built from verified facts by a template. The show goes on.`);
  run.outage = true;
  await post("outage?down=true");
  emit("focus", { id: "pgm", seconds: 12 });
  await post(`seek?minute=${OUTAGE_FROM}`);
  await hooks.setSpeed(5);
  if (run) run.giveUp = setTimeout(audience, 15000);
}

function onCard(c) {
  if (!run || run.step !== 10 || c.type !== "goal" || c.pending || c.source !== "template") return;
  clearTimeout(run.giveUp);
  later(5000, audience);
}

async function audience() {
  if (!run || run.step >= 11) return;
  run.outage = false;
  await post("outage?down=false");
  if (!run) return;
  const back = app.crowd?.back_in_time?.find((b) => b.minute === 71);
  emit("focus", { id: "aud", seconds: 10 });
  caption(11, 3, ["PERSONALIZE"], `<b>10,000 simulated fans</b> on the same brain${back ? `: ${fmt(back.fans)} back in time for the
    71' goal (simulation assumption: 65% of called fans return)` : ""}. ${scale ? `${fmt(scale.fans)} fans cost
    <b>${fmt(scale.llm_calls)} LLM calls</b>, not ${fmt(scale.naive_llm_calls)}.` : ""}`);
  later(9000, finale);
}

function finale() {
  const actions = [["fan", "FAN VIEW"], ["sofia", "WATCH AS SOFIA"], ["reda", "WATCH AS REDA"], ["story", "↺ REPLAY"]];
  caption(12, 3, STAGES, `<b>${VISION}</b>`, actions);
  cleanUp();
  shown = "finale";
  hooks.setSpeed(10);
}

function act(name) {
  if (name === "studio" || name === "fan") hooks.setMode(name);
  else if (name === "story") startStory();
  else if (name === "exit") exitStory();
  else if (name === "picker") hooks.openPicker();
  else if (name === "skip") post(`seek?minute=${SKIP_TO}`);
  else if (name === "away") { if (app.present) post("away"); }
  else if (name === "back") { if (!app.present) post("back"); }
  else hooks.pick(name);
}

/* ------------------------------------------------------------------ the guide (outside the story) */

/** Which situation the viewer is in, and what to suggest. */
function situation() {
  const p = profile(), s = app.snapshot;
  const name = esc(p.name);
  if (!app.present) {
    return ["away", `<b>${name} is away.</b> COMEBACK keeps watching and will buzz the phone when it matters.
      Come back whenever you like.`, [["back", "I'M BACK"], ["picker", "SWITCH FAN"]]];
  }
  const band = app.awayBands.at(-1);
  if (band && !$("#catchup").hidden) {             // just back: the catch-up comes first
    const text = band.late_join ? `<b>The story so far</b> is on the phone, in ${name}'s language. Now watch live,
      and leave whenever you like.` : `Welcome back. <b>The catch-up on the phone</b> says what changed while ${name}
      was away. Leave again whenever you like.`;
    return ["back", text, [["away", "I'M AWAY"], ["picker", "SWITCH FAN"]]];
  }
  if (!band && s && (s.period === 1 || s.minute < 58)) {
    return ["early", `Watching as <b>${name}</b>. The drama starts after the hour: <b>skip ahead</b>, then leave
      (switch tabs or I'M AWAY) and let COMEBACK call ${name} back.`, [["skip", "SKIP TO 60'"], ["picker", "SWITCH FAN"]]];
  }
  const pushing = s && [s.home, s.away].find((c) => s.teams[c].danger >= 40 && s.teams[c].danger_slope > 0);
  if (pushing && !shown.startsWith("pushing")) {
    return [`pushing:${pushing}`, `<b>${esc(teamName(pushing))} are pushing right now</b>. Put your phone away (I'M AWAY)
      and see whether COMEBACK calls ${name} back before anything happens.`, [["away", "I'M AWAY"]]];
  }
  if (shown.startsWith("pushing") && s && [s.home, s.away].some((c) => s.teams[c].danger >= 30)) return null;  // keep it
  return ["present", `<b>Put your phone away</b>: switch tabs, or press I'M AWAY. COMEBACK will tell ${name} when it
    matters, then show what was missed.`, [["away", "I'M AWAY"], ["picker", "SWITCH FAN"]]];
}

/** Outside the story: one line on what this viewer can do right now. */
function hint(force = false, kind = null) {
  if (run || !profile() || (shown === "finale" && !force)) return;
  if (kind === "final") {
    shown = "final";
    guide(`<b>Full-time.</b> ${esc(profile().name)}'s own front page is on screen: the match told from their side.`,
      [["picker", "SWITCH FAN"], ["story", "▶ PLAY THE STORY"]]);
    return;
  }
  if (shown === "final" && !force) return;
  const next = situation();
  if (!next || (next[0] === shown && !force)) return;
  [shown] = next;
  guide(next[1], next[2]);
}

function guide(html, actions) {
  $("#storybar").classList.remove("story");
  $("#st-step").innerHTML = `<span>WATCHING AS ${esc(profile().name.toUpperCase())}</span>`;
  setText(html);
  setActions(actions);
}

/* ------------------------------------------------------------------ rendering */

function caption(step, actNo, stages, html, actions = [["exit", "EXIT STORY ✕"]]) {
  if (run) run.step = step;
  shown = "story";
  $("#storybar").classList.add("story");
  $("#st-step").innerHTML = `<span>${ACTS[actNo]} · ${step}/${STEPS}</span>
    <span class="pipe" aria-label="Pipeline stages shown">${STAGES.map((st) => `<i class="${stages.includes(st) ? "on" : ""}">${st}</i>`).join("")}</span>`;
  setText(html);
  setActions(actions);
}

function setText(html) {
  const el = $("#st-text");
  el.innerHTML = html;
  el.style.animation = "none"; void el.offsetWidth; el.style.animation = "";
}

function setActions(actions) {
  $("#st-act").innerHTML = actions.map(([id, label]) => `<button class="key" data-act="${id}">${label}</button>`).join("");
}
