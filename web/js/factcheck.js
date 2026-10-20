/* FACT-CHECK on the program feed: when the Verifier rejects a draft, viewers see the
 * draft with the wrong words struck through, the Verifier's reason, and then the version
 * that passed. It follows the paced AGENTS steps, so it stays in sync with the ticker.
 * Only the first rejection of a text is shown; later drafts only update the outcome. */

import { $, esc, on } from "./state.js";
import { storyActive, storyStep } from "./story.js";

// Wording the Verifier's numerical-advantage rule is about, most specific first: the first
// pattern found in the quoted sentence is struck through (else the whole sentence is).
const CLAIMS = [/numerical (?:dis)?advantage|man advantage|extra man|full[- ]strength/gi, /ten[- ]m[ae]n|10 men/gi];
const HOLD_MS = 15000;
let current = null;            // { label, timer }
const writer = {};             // label → { agent, preview } of the latest draft

export function initFactCheck() {
  on("agent-shown", (s) => {
    if (s.step === "draft") writer[s.label] = { agent: s.agent, preview: s.detail };
    else if (s.step === "rejected" && s.draft) show(s);
    else if (current?.label === s.label && (s.step === "verified" || s.step === "template")) resolve(s);
  });
  on("state", hide);
}

function show(s) {
  if (current?.label === s.label) return;                  // already on screen: the outcome will follow
  if (storyActive() && storyStep() < 8) return;            // the guided story shows its fact-check in act 3
  const { quote, reason } = parse(s.detail);
  const el = $("#factcheck");
  el.innerHTML = `<div class="fc-k"><span>AI CREW · FACT-CHECK</span><span>${esc(s.label.toUpperCase())}</span></div>
    <div class="fc-d">${esc((writer[s.label]?.agent || "Writer").toUpperCase())} · DRAFT #${s.attempt}</div>
    <div class="fc-t">${highlight(s.draft, quote, s.detail)}</div>
    <div class="fc-r"><b>✗ VERIFIER</b> ${esc(reason)}</div>
    <div class="fc-n" id="fc-n">↺ Sent back for a rewrite…</div>`;
  el.hidden = false;
  el.classList.remove("in"); void el.offsetWidth; el.classList.add("in");
  clearTimeout(current?.timer);
  current = { label: s.label, timer: setTimeout(hide, HOLD_MS) };
}

function resolve(s) {
  const n = $("#fc-n");
  if (!n) return;
  n.className = `fc-n ${s.step === "verified" ? "ok" : "tpl"}`;
  n.innerHTML = s.step === "verified"
    ? `✓ DRAFT #${s.attempt} VERIFIED, ON AIR: “${esc(writer[s.label]?.preview || "")}”`
    : "⚠ No draft passed: a template built from verified facts went on air instead.";
  clearTimeout(current.timer);
  current.timer = setTimeout(hide, 7000);
}

function hide() {
  clearTimeout(current?.timer);
  current = null;
  const el = $("#factcheck");
  if (el) { el.hidden = true; el.innerHTML = ""; }
}

/** Verifier issues look like "'<sentence>': <reason>" or "These numbers are not in the facts: 36. …". */
function parse(detail) {
  const m = /^'(.+)': (.+)$/s.exec(detail || "");
  const text = m ? m[2] : detail || "";
  return { quote: m ? m[1] : null, reason: text.split(/(?<=\.)\s/)[0] };
}

/** The draft as HTML, with the wrong part struck through. */
function highlight(draft, quote, detail) {
  const spans = [];
  const numbers = /not in the facts: ([^.]+)\./.exec(detail || "");
  if (numbers) {
    for (const n of numbers[1].split(/,\s*/)) {
      const re = new RegExp(`(?<![\\d.])${n.replace(/[.]/g, "\\.")}(?![\\d])`, "g");
      for (const m of draft.matchAll(re)) spans.push([m.index, m.index + m[0].length]);
    }
  } else if (quote && draft.includes(quote)) {
    const start = draft.indexOf(quote);
    const found = CLAIMS.map((re) => [...quote.matchAll(re)]).find((matches) => matches.length) || [];
    const claims = found.map((m) => [start + m.index, start + m.index + m[0].length]);
    spans.push(...(claims.length ? claims : [[start, start + quote.length]]));
  }
  spans.sort((a, b) => a[0] - b[0]);
  let html = "", at = 0;
  for (const [a, b] of spans) {
    if (a < at) continue;
    html += esc(draft.slice(at, a)) + `<del>${esc(draft.slice(a, b))}</del>`;
    at = b;
  }
  return `“${html + esc(draft.slice(at))}”`;
}
