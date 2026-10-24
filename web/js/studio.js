/* Studio control room, the producer's view: one card per moment in the LIVE AGENT FEED, telling the
 * whole chain — moment detected (with its events) → Analyst wrote → Verifier ✓, or ✗ with the
 * draft struck through and the reason, then the corrected version → on air — and one card per
 * audience call-back (why now, how many fans, the same call as three segments get it).
 * Below: the audience in five numbers. The raw feed (cues JSON, engine data, timeline) folds away. */

import { $, app, esc, on, teamName, teamColour, LANG_NAME } from "./state.js";

const MAX_CARDS = 40;   // the whole match stays in the feed: scroll down to an earlier fact-check
const cards = new Map();          // key → { key, kind, t, minute, team, steps, call, el }
window.__feed = cards;            // read-only handle for automated UI checks
const queue = [];
let timer = null;
let liveCount = 2;
const fmt = (n) => Number(n || 0).toLocaleString("en-US");
const plural = (n, one, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;
const surname = (pid) => esc(app.roster[pid]?.name.split(" ").at(-1) || pid || "");
const TYPE = { goal: "GOAL", big_chance: "BIG CHANCE", red_card: "RED CARD", penalty: "PENALTY", shape_change: "SHAPE CHANGE",
  momentum_swing: "MOMENTUM SWING", half_time: "HALF-TIME", full_time: "FULL-TIME", milestone: "MILESTONE", substitution: "SUBSTITUTION" };

export function initStudio() {
  on("agent", (step) => { queue.push({ step }); if (!timer) pump(); });
  on("crowd", (c) => {
    for (const call of c.calls || []) {
      const key = `call:${call.t}`;
      if (cards.has(key)) cards.get(key).call = call;               // a later frame may add its "called it"
      else if (!queue.some((q) => q.call?.t === call.t)) queue.push({ call });
    }
    if (!timer) pump();
    renderNumbers(c);
  });
  on("state", (s) => { reset(); for (const call of s.crowd?.calls || []) applyCall(call); renderNumbers(s.crowd); render(); });
  on("card", (c) => { if (cards.has(c.moment_id)) render(); });
  for (const t of ["talking_point", "talking_points"]) on(t, () => setTimeout(render, 0));   // after the desk stores it
  $("#feed").addEventListener("click", (e) => {
    const b = e.target.closest("[data-preview]");
    if (b) { const card = cards.get(b.dataset.preview); card.open = !card.open; render(); }
  });
  $("#raw-toggle").addEventListener("click", () => {
    const open = document.body.classList.toggle("raw-open");
    $("#raw-toggle").textContent = open ? "RAW FEED ▾" : "RAW FEED ▸";
    $("#raw-toggle").setAttribute("aria-expanded", String(open));
  });
  fetch("/api/live").then((r) => r.json()).then((l) => { liveCount = l.length; render(); }).catch(() => {});
  render();
}

function reset() { cards.clear(); queue.length = 0; }
const apply = (item) => (item.step ? applyStep(item.step) : applyCall(item.call));

/* steps arrive in bursts (precomputed replies are instant): replay them one by one so a rejection can be followed */
function pump() {
  while (queue.length > 10) apply(queue.shift());                  // a backlog (after a jump): catch up at once
  const item = queue.shift();
  if (!item) { timer = null; render(); return; }
  apply(item);
  render();
  const tally = $("#feed-tally");
  tally.className = "tally live";
  clearTimeout(pump.idle);
  pump.idle = setTimeout(() => { tally.className = "tally amber"; }, 1500);
  timer = setTimeout(pump, queue.length > 20 ? 40 : queue.length > 6 ? 160 : 380);
}

/* ------------------------------------------------------------------ state */

function applyStep(s) {
  if (s.agent === "Watcher") return;                                  // the studio follows the audience, not one fan
  const key = s.moment_id || s.label;                                  // two moments can share a label ("81' big chance")
  if (!key) return;
  let card = cards.get(key);
  if (!card) {
    const m = /^(\d+)' (.+)$/.exec(s.label || "");
    card = { key, id: s.moment_id, kind: m ? "moment" : "story", minute: m ? Number(m[1]) : s.minute,
      type: m ? m[2].replace(/ /g, "_") : "story", t: performance.now(), steps: [] };
    cards.set(key, card);
  }
  card.steps.push(s);
  card.t = performance.now();
  trim();
}

function applyCall(call) {
  const key = `call:${call.t}`;
  const card = cards.get(key);
  if (card) { card.call = call; return; }                          // a later frame may add its "called it"
  cards.set(key, { key, kind: "call", minute: call.minute, call, t: performance.now(), steps: [] });
  trim();
}

function trim() {
  const sorted = [...cards.values()].sort(order);
  for (const c of sorted.slice(MAX_CARDS)) cards.delete(c.key);
}

/* newest match moment first; a call-back sits just above the moment it called */
const order = (a, b) => (b.call?.t ?? momentT(b)) - (a.call?.t ?? momentT(a));
function momentT(card) {
  const c = momentCard(card);
  return c ? c.t : card.minute * 60;
}
const matches = (card, c) => c.minute === card.minute && c.type === card.type;
const momentCard = (card) => app.cards.get(card.id) || [...app.cards.values()].find((c) => matches(card, c));

/* ------------------------------------------------------------------ rendering */

function render() {
  const el = $("#feed");
  if (!el) return;
  const list = [...cards.values()].sort(order);
  if (!list.length) {
    el.innerHTML = `<div class="feed-wait"><b>Watching ${liveCount} live matches · ${fmt(app.crowd?.size || 10000)} viewers</b>
      <span>Every key moment appears here with the agents' work on it: what the engine detected, what the Analyst wrote,
      what the Verifier checked, and which fans the Watcher called back.</span></div>`;
    return;
  }
  el.innerHTML = list.map((c) => {
    const html = c.kind === "call" ? callCard(c) : c.kind === "moment" ? momentHtml(c) : storyCard(c);
    const fresh = !c.shown;                                          // only a new card slides in, not every refresh
    c.shown = true;
    return fresh ? html.replace('class="fd-card', 'class="fd-card new') : html;
  }).join("");
}

/** Where the text on air comes from: LIVE LLM (a Foundry call now), RECORDED (a verified model reply recorded
 * once and replayed: the offline demo) or TEMPLATE (built from verified facts, no model). */
const SOURCE = {
  live: ["LIVE LLM", "Written by the model just now (Microsoft Foundry), then verified"],
  recorded: ["RECORDED", "A verified model reply, recorded once and replayed (offline demo)"],
  template: ["TEMPLATE", "Built from verified facts, no model call"],
};
export const sourceBadge = (kind) => (kind ? `<span class="b src-${kind}" title="${SOURCE[kind][1]}">${SOURCE[kind][0]}</span>` : "");
function sourceOf(steps) {
  if (steps.some((s) => s.step === "template")) return "template";
  const drafts = steps.filter((s) => s.step === "draft");
  if (!drafts.length) return null;
  return drafts.at(-1).cached === false ? "live" : "recorded";
}
const badges = (card) => sourceBadge(sourceOf(card.steps.filter((s) => s.agent !== "Researcher" && s.writer !== "Researcher")));

function momentHtml(card) {
  const c = momentCard(card);
  const team = c?.team;
  const events = (c?.evidence_event_ids || []).map((id) => app.eventsById.get(id)).filter(Boolean).slice(-2);
  const engine = card.steps.find((s) => s.agent === "Engine");
  const imp = /importance (\d+)/.exec(engine?.detail || "")?.[1] ?? c?.importance;
  const rows = [`<li class="engine"><i>ENGINE</i><div>Detected${imp ? ` · importance ${imp}` : ""}${events.length
    ? `<span class="evs">${events.map((e) => describeEvent(e)).join(" · ")}</span>` : ""}</div></li>`];
  const researcher = card.steps.filter((s) => s.agent === "Researcher" || s.writer === "Researcher");
  for (const s of card.steps.filter((x) => !researcher.includes(x))) {
    if (s.agent === "Analyst" && s.step === "draft") rows.push(`<li class="analyst"><i>ANALYST</i><div>Draft #${s.attempt}: “${esc(s.detail)}”</div></li>`);
    else if (s.step === "rejected") {
      rows.push(`<li class="verifier bad"><i>VERIFIER</i><div><b>✗ Rejected</b> ${s.draft ? `<q>${strike(s.draft, s.detail)}</q>` : ""}
        <span class="why">${esc(reason(s.detail))}</span></div></li>`);
    } else if (s.step === "verified") rows.push(`<li class="verifier ok"><i>VERIFIER</i><div><b>✓ Verified</b> every number and name checked</div></li>`);
    else if (s.step === "template") rows.push(`<li class="verifier tpl"><i>FALLBACK</i><div>No draft passed: a template built from verified facts</div></li>`);
    else if (s.step === "unavailable") rows.push(`<li class="verifier tpl"><i>FOUNDRY</i><div>Model unavailable: ${esc(s.detail)}</div></li>`);
  }
  const tp = app.talking?.[card.id];
  const rejected = researcher.filter((x) => x.step === "rejected");
  for (const s of rejected) {
    rows.push(`<li class="verifier bad"><i>VERIFIER</i><div><b>✗ Talking point rejected</b> ${s.draft ? `<q>${strike(s.draft, s.detail)}</q>` : ""}
      <span class="why">${esc(reason(s.detail))}</span></div></li>`);
  }
  // after a rejection, every point of the version that passed (the corrected sentence included); otherwise the first
  const shown = tp ? (rejected.length && tp.source === "llm" ? tp.points : tp.points.slice(0, 1)) : [];
  if (tp) rows.push(`<li class="researcher"><i>RESEARCHER</i><div>${tp.source === "llm" ? "✓" : "⚑"} ${shown.map((p) => `“${esc(p.text)}”`).join(" ")}
    ${sourceBadge(sourceOf(researcher) || (tp.source === "llm" ? "recorded" : "template"))}
    <small class="src">${esc(tp.points[0].source)} → Research Desk</small></div></li>`);
  const done = card.steps.some((s) => (s.step === "verified" || s.step === "template") && s.writer !== "Researcher");
  const prior = callBefore(c);
  return `<article class="fd-card ${card.type}" style="--team:${teamColour(team)}">
    <header><b>${card.minute}'</b><span>${TYPE[card.type] || esc(card.type).toUpperCase()}${team ? ` · ${esc(teamName(team))}` : ""}</span>${badges(card)}</header>
    <ol>${rows.join("")}</ol>
    ${done && c && !c.pending ? `<footer><span class="air">ON AIR</span><b>${esc(c.headline)}</b><small>${esc(c.why_it_matters || "")}</small></footer>` : ""}
    ${prior ? `<div class="called">✓ The Watcher called ${fmt(total(prior))} fans back ${Math.max(1, Math.round((c.t - prior.t) / 60))}' before</div>` : ""}
  </article>`;
}

function storyCard(card) {
  const last = card.steps.at(-1);
  return `<article class="fd-card story"><header><b>${card.minute}'</b><span>STORYTELLER · ${esc(card.key)}</span>${badges(card)}</header>
    <ol><li class="verifier ${last.step === "verified" ? "ok" : ""}"><i>${esc(last.agent.toUpperCase())}</i><div>${esc(last.step)}${
      last.detail ? ` · ${esc(last.detail)}` : ""}</div></li></ol></article>`;
}

const total = (call) => call.called.attacking + call.called.defending + call.called.neutral;
function callBefore(c) {
  if (!c || c.type !== "goal") return null;
  return (app.crowd?.calls || []).filter((k) => k.team === c.team && k.t < c.t && c.t - k.t <= 300).at(-1) || null;
}

function callCard(card) {
  const k = card.call, r = k.reasons, team = esc(teamName(k.team));
  const opp = esc(teamName(k.team === app.home ? app.away : app.home));
  const segName = (s) => (s.side === "player" || (!s.club_id && s.favourite_player_id)
    ? `Follows ${esc(app.roster[s.favourite_player_id]?.name || "")}` : `${esc(teamName(s.club_id))} fans`);
  const preview = card.open && k.segments ? `<div class="segs">${k.segments.map((s) => `<div class="seg-c" style="--team:${teamColour(s.club_id || app.roster[s.favourite_player_id]?.team)}">
      <b>${segName(s)}</b><small>${LANG_NAME[s.language]} · ${s.level}</small><p>“${esc(s.text)}”</p></div>`).join("")}</div>` : "";
  return `<article class="fd-card call" style="--team:${teamColour(k.team)}">
    <header><b>${k.minute}'</b><span>CALL-BACK · ${team.toUpperCase()} PUSHING</span>${sourceBadge("template")}</header>
    <ol>
      <li class="watcher"><i>WHY NOW</i><div>Danger <b>${k.danger}</b>/100, rising +${k.slope} in 30 s ·
        ${plural(r.box_entries, "box entry", "box entries")}, ${plural(r.shots, "shot")} in 2 min${r.main_channel ? ` · ${r.main_channel === "centre" ? "through the centre" : `down the ${r.main_channel}`}` : ""}</div></li>
      <li class="watcher"><i>RULE</i><div>≥ ${k.threshold} and rising · no own shot for ${k.since_own_shot_s} s · ${Math.round(k.cooldown_s / 60)}' since the last call ·
        sustained pressure, not a prediction</div></li>
      <li class="watcher big"><i>WATCHER</i><div><b>${fmt(total(k))}</b> of ${fmt(k.away)} away fans called back:
        ${fmt(k.called.attacking)} ${team} · ${fmt(k.called.defending)} ${opp} · ${fmt(k.called.neutral)} neutral</div></li>
    </ol>
    ${k.goal ? `<div class="called">✓ Called it: goal ${k.goal.minute}', ${k.goal.lead_s} s later</div>` : ""}
    <button class="key preview" data-preview="${esc(card.key)}">${card.open ? "HIDE PREVIEW" : "PREVIEW ▸ the same call for 3 fans"}</button>${preview}
  </article>`;
}

function renderNumbers(c) {
  if (!c) return;
  const goal = (c.back_in_time || []).at(-1);
  const naive = (c.analyst_calls || 0) + (c.catchups || 0);
  const tiles = [
    ["VIEWERS", fmt(c.size), ""], ["AWAY NOW", fmt(c.away), ""], ["CALLED BACK", fmt(c.alerts_sent), "call-backs sent"],
    [goal ? `BACK FOR THE ${goal.minute}' GOAL*` : "BACK FOR A GOAL*", goal ? fmt(goal.fans) : "–", "fans back in time"],
    ["LLM CALLS", fmt(c.llm_calls), `vs ${fmt(naive)} with one call per catch-up`],
  ];
  $("#numbers").innerHTML = tiles.map(([k, v, s]) => `<div class="num"><span>${k}</span><b>${v}</b><small>${s}</small></div>`).join("")
    + `<div class="num-note">* simulated: 65% of called fans return · 10,000 synthetic viewers</div>`;
}

/* ------------------------------------------------------------------ helpers */

function describeEvent(e) {
  switch (e.type) {
    case "pass": return `PASS ${surname(e.player)} → ${surname(e.receiver)} · difficulty ${e.difficulty}`;
    case "shot": return `SHOT ${surname(e.player)} · xG ${e.xg.toFixed(2)} · ${Math.round(e.shot_speed_kmh)} km/h · ${e.outcome.replace("_", " ")}`;
    case "goal": return `GOAL ${surname(e.scorer)} · ${e.score_home}-${e.score_away}`;
    case "card": return `${e.color.toUpperCase()} CARD ${surname(e.player)}`;
    case "substitution": return `SUB ${surname(e.player_in)} for ${surname(e.player_out)}`;
    case "carry": case "sprint": return `RUN ${surname(e.player)} · ${Math.round(e.speed_kmh)} km/h`;
    default: return `${e.type.replace("_", " ").toUpperCase()}${e.player ? ` ${surname(e.player)}` : ""}`;
  }
}

/** Verifier issues look like "'<sentence>': <reason>" or "These numbers are not in the facts: 36. …". */
function reason(detail) {
  const m = /^'(.+)': (.+)$/s.exec(detail || "");
  return (m ? m[2] : detail || "").split(/(?<=\.)\s/)[0];
}

const CLAIMS = [/numerical (?:dis)?advantage|man advantage|extra man|full[- ]strength/gi, /ten[- ]m[ae]n|10 men/gi];
const RESEARCH_CLAIMS = [   // [the Verifier's reason, the words it is about]
  [/^Wrong side/, /\d+\s*[-–]\s*\d+\s+(?:lead|d['’]avance)|(?:lead(?:ing)?|ahead|avance de|ventaja(?: de)?|trail(?:ing)?|behind)\s+\d+\s*[-–]\s*\d+/gi],
  [/fewer goals .* than the xG|more goals .* than the xG/, /superando[^.,]*|clinical[^.,]*|outperform\w*|below (?:his |the )?(?:expected|xg)/gi],
  [/^That meeting was in/, /last season|this season|saison (?:dernière|passée)|cette saison|temporada pasada|esta temporada/gi],
];
function strike(draft, detail) {
  const spans = [];
  const quote = /^'(.+)': /s.exec(detail || "")?.[1];
  const numbers = /not in the facts: ([^.]+)\./.exec(detail || "");
  if (numbers) {
    for (const n of numbers[1].split(/,\s*/)) {
      for (const m of draft.matchAll(new RegExp(`(?<![\\d.])${n.replace(/[.]/g, "\\.")}(?![\\d])`, "g"))) spans.push([m.index, m.index + m[0].length]);
    }
  } else if (RESEARCH_CLAIMS.some(([why]) => why.test(detail || ""))) {    // a Researcher claim check: strike the claim
    const re = RESEARCH_CLAIMS.find(([why]) => why.test(detail))[1];
    for (const m of draft.matchAll(re)) spans.push([m.index, m.index + m[0].length]);
  } else if (quote && draft.includes(quote)) {
    const start = draft.indexOf(quote);
    const found = CLAIMS.map((re) => [...quote.matchAll(re)]).find((ms) => ms.length) || [];
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
  return html + esc(draft.slice(at));
}
