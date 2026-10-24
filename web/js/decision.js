/* DECISIONS monitor (studio): the Watcher's reasoning for each audience-level call-back, in four
 * time-stamped steps — events observed (with their ids) → state computed (danger and its trend)
 * → explainable insight (no goal promised) → the decision: which fans, why now.
 * PERSONALIZE monitor: the same call-back as three audience segments receive it. */

import { $, app, esc, on, emit, teamName, teamColour, LANG_NAME } from "./state.js";

const surname = (pid) => esc(app.roster[pid]?.name.split(" ").at(-1) || pid || "");
const clock = (e) => `${e.minute}:${String(e.second).padStart(2, "0")}`;
const fmt = (n) => Number(n).toLocaleString("en-US");
const plural = (k, one, many) => `${k} ${k === 1 ? one : many}`;
let shown = 0;           // calls already drawn (a new one lights the monitors)

/** One line for a match event, as the engine ingested it. */
export function describeEvent(e) {
  switch (e.type) {
    case "pass":
      return `PASS ${surname(e.player)} → ${surname(e.receiver)} · ${Math.round(e.distance_m)} m · difficulty ${e.difficulty}${e.success ? "" : " · lost"}`;
    case "carry": return `CARRY ${surname(e.player)} · ${Math.round(e.speed_kmh)} km/h`;
    case "sprint": return `SPRINT ${surname(e.player)} · ${e.speed_kmh.toFixed(1)} km/h`;
    case "shot": return `SHOT ${surname(e.player)} · xG ${e.xg.toFixed(2)} · ${Math.round(e.shot_speed_kmh)} km/h · ${e.outcome.replace("_", " ")}`;
    case "pressure": return `PRESSURE ${surname(e.player)} on ${surname(e.target_player)}${e.success ? " · won" : ""}`;
    case "tackle": return `TACKLE ${surname(e.player)} · ${e.won ? "won" : "lost"}`;
    case "possession_change": return `TURNOVER → ${esc(e.to_team)} · ${esc(e.reason || "")}`;
    case "goal": return `GOAL ${surname(e.scorer)} · ${e.score_home}-${e.score_away}`;
    case "card": return `${e.color.toUpperCase()} CARD ${surname(e.player)}`;
    case "substitution": return `SUB ${surname(e.player_in)} for ${surname(e.player_out)}`;
    default: return `${e.type.replace("_", " ").toUpperCase()}${e.player ? ` ${surname(e.player)}` : e.team ? ` ${esc(e.team)}` : ""}`;
  }
}

const eventLine = (e) =>
  `<div class="ev"><span class="ev-t">${clock(e)}</span><span class="ev-id">${esc(e.id)}</span><span class="ev-x">${describeEvent(e)}</span></div>`;

/** The four steps of one audience call-back, as HTML. */
function decisionCard(c) {
  const r = c.reasons, team = esc(teamName(c.team)), opp = esc(teamName(c.team === app.home ? app.away : app.home));
  const evidence = (r.evidence_event_ids || []).map((id) => app.eventsById.get(id)).filter(Boolean).slice(-2);
  const side = r.main_channel ? ` · ${r.main_channel === "centre" ? "through the centre" : `down the ${r.main_channel}`}` : "";
  const total = c.called.attacking + c.called.defending + c.called.neutral;
  const goal = c.goal ? `<span class="dc-goal">✓ CALLED IT · goal ${c.goal.minute}', ${c.goal.lead_s} s after the call</span>` : "";
  return `<div class="dc">
    <div class="dc-h"><b>${clock(c)}</b><span>AUDIENCE CALL-BACK · ${team.toUpperCase()} PUSHING</span><em>WATCHER</em></div>
    <ol class="dc-steps">
      <li><i>1</i><div><b>EVENTS</b>${evidence.length ? evidence.map(eventLine).join("")
        : `<span class="dc-x">${plural(r.box_entries, "box entry", "box entries")}, ${plural(r.shots, "shot", "shots")} in 2 min</span>`}</div></li>
      <li><i>2</i><div><b>STATE</b><span class="dc-x">danger ${esc(c.team)} <em>${c.danger}</em>/100 ▲ +${c.slope} in 30 s ·
        ${plural(r.box_entries, "box entry", "box entries")}, ${plural(r.shots, "shot", "shots")} in 2 min${side}</span></div></li>
      <li><i>3</i><div><b>INSIGHT</b><span class="dc-x">sustained ${team} pressure, not a prediction</span></div></li>
      <li><i>4</i><div><b>DECISION</b><span class="dc-x"><span class="dc-ok">✓ ${c.danger} ≥ ${c.threshold} and rising</span>
        <span class="dc-ok">✓ no own shot for ${c.since_own_shot_s} s</span> <span class="dc-ok">✓ cooldown ${Math.round(c.cooldown_s / 60)} min</span>
        <span class="dc-out">→ <b>${fmt(total)}</b> of ${fmt(c.away)} away fans called: ${fmt(c.called.attacking)} ${team} ·
        ${fmt(c.called.defending)} ${opp} · ${fmt(c.called.neutral)} neutral</span></span></div></li>
    </ol>${goal}</div>`;
}

function renderDecisions(calls) {
  const el = $("#decisions");
  if (!calls.length) {
    el.innerHTML = `<div class="empty">No call-back yet. When a side builds real pressure, the Watcher's reasoning appears here.</div>`;
    return;
  }
  const earlier = calls.slice(0, -1).reverse().slice(0, 6)
    .map((c) => `${c.minute}' ${esc(c.team)} ${c.danger}${c.goal ? " ✓" : ""}`).join(" · ");
  el.innerHTML = decisionCard(calls.at(-1)) + (earlier ? `<div class="dc-prev">EARLIER · ${earlier}</div>` : "");
}

function segmentName(s) {
  if (s.side === "player") return `Follows ${app.roster[s.favourite_player_id]?.name || s.favourite_player_id}`;
  return `${teamName(s.club_id)} fans`;
}

function renderSegments(calls) {
  const c = calls.at(-1);
  const el = $("#pers");
  if (!c?.segments) { el.innerHTML = `<div class="empty">The latest call-back, as three different fans receive it.</div>`; return; }
  const team = (s) => s.club_id || app.roster[s.favourite_player_id]?.team;
  el.innerHTML = `<div class="ps-top">${c.minute}' · ${esc(teamName(c.team))} pushing · same facts: danger ${c.danger},
      ${plural(c.reasons.box_entries, "box entry", "box entries")} in 2 min</div>
    <div class="ps-cols">${c.segments.map((s) => `<div class="ps-col" style="--team:${teamColour(team(s))}">
      <div class="ps-h"><b>${esc(segmentName(s))}</b><small>${LANG_NAME[s.language]} · ${s.level}</small></div>
      <div class="ps-v">“${esc(s.text)}”</div></div>`).join("")}</div>`;
}

function render(crowd) {
  const calls = crowd?.calls || [];
  renderDecisions(calls);
  renderSegments(calls);
  if (calls.length > shown) {
    for (const id of ["decisions-tally", "pers-tally"]) $(`#${id}`).className = "tally live";
    clearTimeout(render.t);
    render.t = setTimeout(() => { for (const id of ["decisions-tally", "pers-tally"]) $(`#${id}`).className = "tally amber"; }, 2500);
    if (shown) emit("crowd-call", calls.at(-1));   // not on (re)connect
  }
  shown = calls.length;
}

export function initDecisions() {
  on("crowd", render);
  on("state", (s) => { shown = 0; render(s.crowd); shown = s.crowd?.calls?.length || 0; });
}
