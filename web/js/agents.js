/* AGENTS monitor: the multi-agent system working live — a lit pipeline and a log.
 * Steps arrive in bursts (cached LLM replies are instant), so they are replayed
 * one by one with a short delay: the viewer can actually follow a rejection. */

import { $, esc, on, emit } from "./state.js";

const NODES = [
  ["Engine", "ENGINE"], ["Analyst", "ANALYST"], ["Verifier", "VERIFIER"],
  ["Watcher", "WATCHERS"], ["Storyteller", "STORYTELLER"], ["Fallback", "FALLBACK"],
];
const STEP_LABEL = {
  moment: "MOMENT", draft: "DRAFT", voice: "VOICE", full_time: "FULL-TIME", rejected: "✗ REJECTED", verified: "✓ VERIFIED", template: "TEMPLATE",
  unavailable: "LLM DOWN", restored: "LLM BACK", called_it: "✓ CALLED IT", come_back: "▲ CALL BACK", goal: "GOAL ALERT", watching: "WATCHING", back: "FAN BACK", join: "LATE JOIN",
};
const queue = [];
const log = [];
const counts = { cards: 0, revised: 0, fallback: 0, alerts: 0, stories: 0 };
let timer = null;

export function initAgents() {
  const el = $("#agents");
  el.innerHTML = `<div class="ag">
    <div class="ag-pipe">${NODES.map(([id, label]) => `<span class="ag-node" data-node="${id}">${label}</span>`).join("")}</div>
    <div class="ag-log" id="ag-log"></div>
    <div class="ag-count" id="ag-count"></div></div>`;
  renderCounts();
  on("agent", (step) => { queue.push(step); if (!timer) pump(); });
  on("crowd-call", (c) => {          // the audience's Watcher decision (computed once for every fan)
    const n = c.called.attacking + c.called.defending + c.called.neutral;
    queue.push({ agent: "Watcher", step: "come_back", minute: c.minute, label: "audience",
      detail: `${c.team} danger ${c.danger} & rising → ${n.toLocaleString("en-US")} away fans called back` });
    if (!timer) pump();
  });
  on("state", () => { queue.length = 0; log.length = 0; $("#ag-log").innerHTML = ""; });
}

function pump() {
  const step = queue.shift();
  if (!step) { timer = null; return; }
  show(step);
  const delay = queue.length > 20 ? 60 : queue.length > 6 ? 180 : 420;
  timer = setTimeout(pump, delay);
}

function show(s) {
  if (s.step === "verified" && s.detail === "Analyst") counts.cards += 1;
  if (s.step === "verified" && s.detail === "Storyteller") counts.stories += 1;
  if (s.step === "rejected") counts.revised += 1;
  if (s.step === "template") counts.fallback += 1;
  if (s.step === "come_back") counts.alerts += 1;

  for (const n of document.querySelectorAll(".ag-node")) n.className = "ag-node";
  const node = document.querySelector(`.ag-node[data-node="${s.agent}"]`);
  if (node) node.className = `ag-node ${s.step === "rejected" || s.step === "unavailable" ? "bad" : s.step === "verified" ? "ok" : "on"}`;
  document.querySelector("#agents-tally").className = "tally live";
  clearTimeout(show.idle);
  show.idle = setTimeout(() => { document.querySelector("#agents-tally").className = "tally amber"; }, 1500);

  const attempt = s.attempt ? ` #${s.attempt}` : "";
  const cls = lineClass(s);
  log.unshift(`<div class="ag-line ${cls}"><span class="m">${s.minute ?? ""}'</span><span class="a">${s.agent.toUpperCase()}</span>
    <span class="s">${STEP_LABEL[s.step] || s.step.toUpperCase()}${attempt}</span>
    <span class="d">${esc(s.label || "")}${s.detail ? ` · ${esc(s.detail)}` : ""}${s.cached ? " <i>cache</i>" : ""}</span></div>`);
  log.length = Math.min(log.length, 40);
  emit("agent-shown", s);
  $("#ag-log").innerHTML = log.join("");
  renderCounts();
}

function lineClass(s) {
  if (s.step === "rejected" || s.step === "unavailable") return "bad";
  return s.step === "verified" || s.step === "called_it" || s.step === "restored" ? "ok" : s.step === "come_back" ? "hot" : "";
}

function renderCounts() {
  $("#ag-count").innerHTML = `CARDS <b>${counts.cards}</b> · REVISIONS <b>${counts.revised}</b> · FALLBACKS <b>${counts.fallback}</b>
    · STORIES <b>${counts.stories}</b> · CALL-BACKS <b>${counts.alerts}</b>`;
}
