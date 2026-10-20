/* The bar above the match.
 *
 * Story mode captions a guided run of the demo: kick-off is at 4 a.m. in Omar's time zone;
 * Omar falls asleep at 63', the phone buzzes twice, Omar is up at 70.5' and sees the 71'
 * goal live; then a jump to 80' shows the Verifier catching a real mistake by the Analyst.
 * The story only drives the normal controls (seek, speed, away, back): everything on screen
 * is the real system at work.
 *
 * Otherwise the bar is a guide: one line on what this viewer can usefully do right now
 * (skip to the second half, leave while a team is pushing, read the catch-up…). */

import { $, app, MATCH_ID, post, on, profile, esc, teamName } from "./state.js";

const STEPS = 9;
const LEAVE_AT = 63, BACK_AT = 70.5;   // the precomputed demo window (verified LLM text + neural voice)
const FACT_CHECK_FROM = 80.3;          // just before the 81' big chance, whose first draft the Verifier rejects
const KICK_OFF_MIN = 4 * 60;           // 4:00 a.m. local time in the story
const HALF_TIME_MIN = 15;
const SKIP_TO = 59.5;
let run = null;                        // the story being played, or null
let nightSession = null;               // the session the story played in (its phone keeps the 4 a.m. clock)
let hooks = {};
let scaleLine = "";
let shown = "";                        // the hint currently on screen (re-rendered only when it changes)

export const storyActive = () => Boolean(run);
export const storyStep = () => run?.step ?? 0;

/** "05:18" in the story's time zone, or null outside the story. */
export function nightClock() {
  const s = app.snapshot;
  if (!s || nightSession !== app.session || app.profileId !== "omar") return null;
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
  on("snapshot", onSnapshot);
  on("notification", onNotification);
  on("event", onEvent);
  on("agent-shown", onAgent);
  $("#storybar").addEventListener("click", (e) => {
    const b = e.target.closest("[data-act]");
    if (b) act(b.dataset.act);
  });
  fetch(`/api/scale/${MATCH_ID}`).then((r) => r.json()).then(({ curve }) => {
    const big = curve.at(-1), fmt = (n) => n.toLocaleString("en-US");
    scaleLine = `${fmt(big.fans)} fans cost <b>${fmt(big.llm_calls)} LLM calls</b>, not ${fmt(big.naive_llm_calls)}.`;
  }).catch(() => {});
}

export function startStory() {
  run = { step: 0, seeked: false, calls: 0, back: false, goal: false };
  document.body.classList.add("story-on");
  hooks.setMode("fan");
  app.profileId = "omar";
  app.speed = 20;
  hooks.restart();
  nightSession = app.session;
  caption(1, `<b>Meet Omar</b>, an Emberfield fan who reads French. In Omar's time zone, kick-off was at
    <b>4 a.m.</b> It's the hour mark, and Emberfield are losing 0‑2.`);
}

export function exitStory() {
  if (!run) return;
  run = null;
  document.body.classList.remove("story-on");
  hooks.setSpeed(10);
  hint(true);
}

async function seekToStart() {
  run.seeked = true;
  await post("seek?minute=59");
  // the server applies the absence at exact minutes: the story never depends on how fast this browser reacts
  await post(`schedule?away=${LEAVE_AT}&back=${BACK_AT}`);
  await hooks.setSpeed(20);
}

function onSnapshot() {
  if (!run) hint();
}

function onPresence({ present }) {
  if (!present && run.step === 1) {
    caption(2, `${LEAVE_AT}' · ${(nightClock() || "5:20").replace(/^0/, "")} a.m. <b>Omar can't stay awake</b> and goes to sleep.
      The phone stays on the nightstand; COMEBACK keeps watching.`);
  } else if (present && run.step >= 2 && !run.back) {
    wakeUp();
  }
}

function onNotification(n) {
  if (!run || n.kind !== "come_back") return;
  run.calls += 1;
  if (run.calls === 1) {
    caption(3, `${n.minute}' · ${esc(teamName(n.team))} are pushing. <b>The phone buzzes</b>, with the reason, in French. →`);
  } else if (run.calls === 2) {
    caption(4, `${n.minute}' · The danger keeps rising. <b>A second buzz, before anything has happened.</b> Omar gets up.`);
    hooks.setSpeed(5);
  }
}

function wakeUp() {
  run.back = true;
  caption(5, `<b>Omar is up.</b> The screen replays what was missed while a neural voice explains what changed:
    in French, from Emberfield's side.`);
  hooks.setSpeed(1);                // real time: the voice-over ends just before the next goal
}

function onEvent(e) {
  if (!run || !run.back || run.goal || e.type !== "goal") return;
  run.goal = true;
  caption(6, `${e.minute}' · <b>GOAL.</b> Omar saw it live. Other apps send the score after the goal;
    COMEBACK woke Omar two minutes before, and said why.`);
  setTimeout(fastForward, 8000);
}

async function fastForward() {
  if (!run) return;
  caption(7, `Fast-forward to 80'. Every key moment is written once by the <b>Analyst</b> agent
    and checked by the <b>Verifier</b> agent before any fan sees it.`);
  await post(`seek?minute=${FACT_CHECK_FROM}`);
  await hooks.setSpeed(5);
  run.giveUp = setTimeout(finale, 30000);     // never stall if no rejection shows up
}

function onAgent(s) {
  if (!run || run.step < 7) return;
  if (run.step === 7 && s.step === "rejected" && s.draft) {
    run.checked = s.label;
    clearTimeout(run.giveUp);
    caption(8, `${esc(s.label)} · <b>The Analyst got a fact wrong. The Verifier caught it</b> and sent it back:
      only a corrected version can go on air. No fan saw the mistake.`);
  } else if (run.step === 8 && s.label === run.checked && (s.step === "verified" || s.step === "template")) {
    setTimeout(finale, 6000);
  }
}

function finale() {
  if (!run) return;
  clearTimeout(run.giveUp);
  caption(9, `<b>The stream asks you to watch. COMEBACK lets you not watch</b>, without missing what matters.
    One match brain and a Watcher per fan: ${scaleLine}`,
  [["studio", "SEE THE AGENTS ▸"], ["sofia", "WATCH AS SOFIA"], ["reda", "WATCH AS REDA"], ["story", "↺ REPLAY"]]);
  run = null;
  shown = "finale";
  document.body.classList.remove("story-on");
  hooks.setSpeed(10);
}

function act(name) {
  if (name === "studio") hooks.setMode("studio");
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
    return ["away", `<b>${name} is away.</b> COMEBACK keeps watching and will buzz the phone when it heats up.
      Come back whenever you like.`, [["back", "I'M BACK"], ["picker", "SWITCH FAN"]]];
  }
  const band = app.awayBands.at(-1);
  if (!band && s && (s.period === 1 || s.minute < 58)) {
    return ["early", `Watching as <b>${name}</b>. The drama starts after the hour: <b>skip ahead</b>, then leave
      (switch tabs or I'M AWAY) and let COMEBACK call ${name} back.`, [["skip", "SKIP TO 60'"], ["picker", "SWITCH FAN"]]];
  }
  if (band && !$("#catchup").hidden) {             // just back: the catch-up comes first
    const text = band.late_join ? `<b>The story so far</b> is on the phone, in ${name}'s language. Now watch live,
      and leave whenever you like.` : `Welcome back. <b>The catch-up on the phone</b> says what changed while ${name}
      was away. Leave again whenever you like.`;
    return ["back", text, [["away", "I'M AWAY"], ["picker", "SWITCH FAN"]]];
  }
  const pushing = s && [s.home, s.away].find((c) => s.teams[c].danger >= 40 && s.teams[c].danger_slope > 0);
  if (pushing && !shown.startsWith("pushing")) {
    return [`pushing:${pushing}`, `<b>${esc(teamName(pushing))} are pushing right now</b> (danger ${Math.round(s.teams[pushing].danger)}/100).
      Leave now and see whether COMEBACK calls ${name} back before anything happens.`, [["away", "I'M AWAY"]]];
  }
  if (shown.startsWith("pushing") && s && [s.home, s.away].some((c) => s.teams[c].danger >= 30)) return null;  // keep it
  return ["present", `<b>Leave whenever you like</b>: switch tabs, or press I'M AWAY. COMEBACK will call ${name} back
    before the big moment, then show what was missed.`, [["away", "I'M AWAY"], ["picker", "SWITCH FAN"]]];
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

function caption(step, html, actions = [["exit", "EXIT STORY ✕"]]) {
  if (run) run.step = step;
  shown = "story";
  const bar = $("#storybar");
  bar.classList.add("story");
  $("#st-step").innerHTML = `<span>STORY · ${step}/${STEPS}</span>
    <span class="st-dots">${Array.from({ length: STEPS }, (_, i) => `<i class="${i < step ? "on" : ""}"></i>`).join("")}</span>`;
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
