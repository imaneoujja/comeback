/* P5 — "Previously on…": when a fan comes back, the program feed rewinds and replays
 * the moments they missed (behind-the-goal camera, REPLAY bug, stingers) while a
 * neural voice (Azure AI Speech) reads their catch-up. Live events that arrive
 * meanwhile are buffered and applied when the replay hands back to live. */

import { $, app, applyEvent, isHome, emit } from "./state.js";
import { put, momentBanner, clearOverlays } from "./graphics.js";
import { speak, stopSpeech } from "./voice.js";

const REPLAY_RATE = 1.6;                 // match seconds per wall second inside a clip
const ON_BALL = new Set(["pass", "carry", "sprint", "shot", "goal", "possession_change", "throw_in", "corner", "goal_kick"]);
const TYPE = { goal: "GOAL", big_chance: "BIG CHANCE", red_card: "RED CARD", penalty: "PENALTY" };
let active = null;
let voice = null;

export const isReplaying = () => Boolean(active && !active.done);
export function buffer(event) { active.buffer.push(event); }

/** A live goal beats any replay: cut straight back to live (like a real gallery would). */
export function interruptForLive() {
  if (active && !active.done) { active.interrupted = true; finish(); }
}

let program_ = null;
function finish() {
  if (!active || active.done) return;
  active.done = true;
  clearOverlays();                                   // replay graphics leave with the replay
  program_?.setCamera("main");
  app.speed = active.speed;
  for (const e of active.buffer) applyEvent(e);     // catch up with live, in order
  active.buffer = [];
  $("#replay-bug").hidden = true;
  $("#pgm-mode").textContent = "LIVE";
  emit("replay-end", { interrupted: Boolean(active.interrupted) });
}

/** Play the fan's voice-over (neural audio if available, browser speech otherwise). */
export function playVoice(c) {
  stopVoice();
  if (c.audio) {
    voice = new Audio(c.audio);
    voice.play().catch(() => speak(c.text, c.language));
  } else {
    speak(c.text, c.language);
  }
}

export function stopVoice() {
  if (voice) { voice.pause(); voice = null; }
  stopSpeech();
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function stinger(text) {
  const el = $("#stinger");
  el.innerHTML = `<span>COMEBACK</span><b>${text}</b>`;
  el.classList.remove("go"); void el.offsetWidth; el.classList.add("go");
  return sleep(450);
}

export async function playReplay(c, program) {
  const clips = (c.replay || []).filter((clip) => clip.events.length);
  if (!clips.length || !program || isReplaying()) return;
  program_ = program;
  active = { buffer: [], speed: app.speed, done: false };
  const run = active;
  emit("replay-start", { clips: clips.length });
  $("#replay-bug").hidden = false;
  $("#pgm-mode").textContent = "REPLAY";
  app.speed = REPLAY_RATE;
  try {
    for (const clip of clips) {
      if (run.done) break;
      await stinger("REPLAY");
      if (run.done) break;
      $("#replay-label").textContent = `${clip.minute}' ${TYPE[clip.type] || ""} · YOU MISSED THIS`;
      program.setCamera("goal", { side: isHome(clip.team) ? 1 : -1 });
      const card = app.cards.get(clip.moment_id);
      if (card) put("banner", momentBanner(card), 6, 200, clip.moment_id);
      const events = clip.events.filter((e) => ON_BALL.has(e.type));
      for (let i = 0; i < events.length && !run.done; i += 1) {
        applyEvent(events[i]);
        const next = events[i + 1];
        await sleep(next ? Math.min(1400, Math.max(120, ((next.t - events[i].t) / REPLAY_RATE) * 1000)) : 1600);
      }
    }
    await stinger("LIVE");
  } finally {
    if (run === active) finish();
  }
}
