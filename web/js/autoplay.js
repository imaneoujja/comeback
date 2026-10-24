/* Demo controls → AUTOPLAY: the fan's absence, run for them so the whole loop fits in two minutes,
 * then on to full time and the receipt.
 * The match starts at 59'; the server applies the absence at exact minutes (63' → 70.5'),
 * so the window never depends on how fast this browser reacts. The rate follows the action:
 * fast while away, real time on return (replay and voice-over), then back to normal.
 * No captions: what is on screen is the product at work. Any manual away/back takes over. */

import { app, post, on } from "./state.js";

const LEAVE_AT = 63, BACK_AT = 70.5;   // the window whose texts and voices are precomputed
const APPROACH_AT = 68;                // slow down before the return
const MAX_REAL_TIME_S = 45;
let run = null;
let setSpeed = () => {};

export const autoplayActive = () => Boolean(run);

export function initAutoplay(hooks) {
  ({ setSpeed } = hooks);
  on("snapshot", (s) => {
    if (run?.phase === "away" && s.period === 2 && s.minute >= APPROACH_AT) { run.phase = "approach"; setSpeed(10); }
  });
  on("presence", ({ present }) => {
    if (!run) return;
    if (!present) { run.phase = "away"; setSpeed(20); return; }
    if (run.phase === "away" || run.phase === "approach") back();
  });
  on("event", (e) => { if (run?.phase === "back" && e.type === "goal") setTimeout(finish, 6000); });
  on("voice", ({ playing }) => { if (run?.phase === "back" && !playing && run.spoke) finish(); else if (playing && run) run.spoke = true; });
}

/** Called once the stream is open (first "state" message). */
export async function startAutoplay() {
  stopAutoplay();
  run = { phase: "start", timer: null, spoke: false };
  await post("seek?minute=59");
  await post(`schedule?away=${LEAVE_AT}&back=${BACK_AT}`);
  await setSpeed(20);
}

/** The viewer took over (pressed away/back): drop the plan, keep the rate. */
export function stopAutoplay() {
  clearTimeout(toFullTime);
  if (!run) return;
  clearTimeout(run.timer);
  if (run.phase === "start" || run.phase === "away" || run.phase === "approach") post("schedule");
  run = null;
}

function back() {
  run.phase = "back";
  setSpeed(1);                                     // real time: the replay, the voice-over, then the next moment
  run.timer = setTimeout(finish, MAX_REAL_TIME_S * 1000);
}

const TO_FULL_TIME_AFTER_MS = 30000;   // time to look at "What you missed", then on to the receipt
let toFullTime = null;

function finish() {
  if (!run) return;
  clearTimeout(run.timer);
  run = null;
  setSpeed(10);
  clearTimeout(toFullTime);
  toFullTime = setTimeout(() => { if (app.speed === 10) setSpeed(40); }, TO_FULL_TIME_AFTER_MS);
}
