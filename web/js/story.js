/* The bar above the match. In "story" mode it captions a guided run of the demo:
 * Omar leaves at 63', is called back twice, returns at 70.5' and sees the 71' goal live;
 * then a jump to 80' shows the Verifier catching a real mistake by the Analyst at 81'.
 * The story only drives the normal controls (seek, speed, away, back): everything on
 * screen is the real system at work. Otherwise the bar says what the viewer can try. */

import { $, app, MATCH_ID, post, on, profile, esc, teamName } from "./state.js";

const STEPS = 9;
const LEAVE_AT = 63, BACK_AT = 70.5;   // the precomputed demo window (verified LLM text + neural voice)
const FACT_CHECK_FROM = 80.3;          // just before the 81' big chance, whose first draft the Verifier rejects
let run = null;                        // the story being played, or null
let hooks = {};
let scaleLine = "";

export const storyActive = () => Boolean(run);
export const storyStep = () => run?.step ?? 0;

/** ``h``: { restart(), setMode(mode), setSpeed(speed), pick(profileId), openPicker() } */
export function initStory(h) {
  hooks = h;
  on("state", () => { if (run && !run.seeked) seekToStart(); else if (!run) hint(); });
  on("presence", () => { if (!run) hint(); });
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
  caption(1, `<b>Meet Omar</b>: an Emberfield fan who reads French and likes the numbers.
    It's the hour mark, and Emberfield are losing 0‑2 at home.`);
}

export function exitStory() {
  if (!run) return;
  run = null;
  document.body.classList.remove("story-on");
  hooks.setSpeed(10);
  hint();
}

async function seekToStart() {
  run.seeked = true;
  await post("seek?minute=59");
  await hooks.setSpeed(20);
}

const minuteOf = (s) => (s.period === 2 ? s.minute + s.second / 60 : 0);

function onSnapshot(s) {
  if (!run || !run.seeked) return;
  const m = minuteOf(s);
  if (run.step === 1 && m >= LEAVE_AT && app.present) {
    caption(2, `${LEAVE_AT}' · <b>Omar leaves the room.</b> The match goes on, and COMEBACK keeps watching it for Omar.`);
    post("away");
  }
  if (run.step >= 2 && !run.back && m >= BACK_AT) comeBack();
}

function onNotification(n) {
  if (!run || n.kind !== "come_back") return;
  run.calls += 1;
  if (run.calls === 1) {
    caption(3, `${n.minute}' · ${esc(teamName(n.team))} are pushing. <b>Omar's phone rings</b>, with the reason, in French. →`);
  } else if (run.calls === 2) {
    caption(4, `${n.minute}' · The danger keeps rising. <b>A second call, before anything has happened.</b> This time, Omar comes back.`);
    hooks.setSpeed(5);
  }
}

async function comeBack() {
  run.back = true;
  caption(5, `<b>Omar is back.</b> The screen replays what was missed while a neural voice explains what changed:
    in French, from Emberfield's side.`);
  await hooks.setSpeed(1);          // real time: the voice-over ends just before the next goal
  await post("back");
}

function onEvent(e) {
  if (!run || !run.back || run.goal || e.type !== "goal") return;
  run.goal = true;
  caption(6, `${e.minute}' · <b>GOAL.</b> Omar saw it live. Other apps notify you after the goal;
    COMEBACK called two minutes before, and said why.`);
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
  caption(9, `Behind the scenes: an <b>Analyst</b>, a <b>Verifier</b>, a <b>Watcher</b> per fan and a <b>Storyteller</b>
    share one match brain. ${scaleLine}`,
  [["studio", "SEE THE AGENTS ▸"], ["sofia", "WATCH AS SOFIA"], ["reda", "WATCH AS REDA"], ["story", "↺ REPLAY"]]);
  run = null;
  document.body.classList.remove("story-on");
  hooks.setSpeed(10);
}

function act(name) {
  if (name === "studio") hooks.setMode("studio");
  else if (name === "story") startStory();
  else if (name === "exit") exitStory();
  else if (name === "picker") hooks.openPicker();
  else hooks.pick(name);
}

/* ------------------------------------------------------------------ rendering */

function caption(step, html, actions = [["exit", "EXIT STORY ✕"]]) {
  if (run) run.step = step;
  const bar = $("#storybar");
  bar.classList.add("story");
  $("#st-step").innerHTML = `<span>STORY · ${step}/${STEPS}</span>
    <span class="st-dots">${Array.from({ length: STEPS }, (_, i) => `<i class="${i < step ? "on" : ""}"></i>`).join("")}</span>`;
  setText(html);
  setActions(actions);
}

/** Outside the story: one line on what this viewer can do right now. */
function hint() {
  const p = profile();
  if (!p) return;
  $("#storybar").classList.remove("story");
  $("#st-step").innerHTML = `<span>WATCHING AS ${esc(p.name.toUpperCase())}</span>`;
  setText(app.present
    ? `<b>Leave whenever you like</b>: switch tabs, or press I'M AWAY on the phone. COMEBACK will call ${esc(p.name)} back
       before the big moment, then show what was missed.`
    : `<b>${esc(p.name)} is away.</b> COMEBACK keeps watching the match and will ring the phone when it heats up.`);
  setActions([["picker", "SWITCH FAN"]]);
}

function setText(html) {
  const el = $("#st-text");
  el.innerHTML = html;
  el.style.animation = "none"; void el.offsetWidth; el.style.animation = "";
}

function setActions(actions) {
  $("#st-act").innerHTML = actions.map(([id, label]) => `<button class="key" data-act="${id}">${label}</button>`).join("");
}
