/* Auto-director (studio): one monitor is ON AIR at a time, the others dim.
 * PGM by default; DECISIONS then PERSONALIZE when the audience is called back; AGENTS when
 * the Verifier rejects or passes a text; AUD right after a goal. Requests that cannot
 * interrupt the current shot are queued, so the 71' goal plays as PGM → AGENTS → AUD → PGM. */

import { $, on } from "./state.js";

const QUEUE_MAX_AGE_MS = 15000;
let current = { id: "pgm", until: 0, priority: 0 };
let queue = [];
let auto = true;

export function initFocus() {
  on("crowd-call", () => { request("decisions", 6, 3); request("pers", 6, 3); });
  on("agent-shown", (s) => {
    if (s.agent === "Verifier") request("agents", s.step === "rejected" ? 6 : 3, s.step === "rejected" ? 2.5 : 1);
  });
  on("event", (e) => {
    if (e.type !== "goal") return;
    request("pgm", 3.5, 4);
    setTimeout(() => request("aud", 5, 2), 3500);
  });
  for (const mon of document.querySelectorAll(".mon[data-mon]")) {
    mon.querySelector(".mon-label").addEventListener("click", () => request(mon.dataset.mon, 8, 5));
  }
  $("#auto-direct").addEventListener("click", () => {
    auto = !auto;
    $("#auto-direct").classList.toggle("on", auto);
    queue = [];
    apply();
  });
  setInterval(tick, 200);
  apply();
}

function request(id, seconds, priority) {
  if (!auto) return;
  const now = performance.now();
  const shot = { id, until: now + seconds * 1000, priority, seconds, at: now };
  if (current.until <= now || priority > current.priority) {
    if (current.until > now && current.id !== id) queue.unshift({ ...current, seconds: (current.until - now) / 1000, at: now });
    current = shot;
    apply();
  } else if (current.id === id) {
    current.until = Math.max(current.until, shot.until);
  } else if (!queue.some((q) => q.id === id)) {
    queue.push(shot);
  }
}

function tick() {
  const now = performance.now();
  if (!auto || current.until > now) return;
  queue = queue.filter((q) => now - q.at < QUEUE_MAX_AGE_MS);
  const next = queue.shift();
  current = next ? { ...next, until: now + next.seconds * 1000 } : { id: "pgm", until: 0, priority: 0 };
  apply();
}

function apply() {
  $(".gallery").classList.toggle("focus-mode", auto);
  const onAir = auto ? current.id : "pgm";
  for (const mon of document.querySelectorAll(".mon[data-mon]")) mon.classList.toggle("focus", mon.dataset.mon === onAir);
}
