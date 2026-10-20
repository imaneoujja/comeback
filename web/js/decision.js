/* The Watcher's decision chain, made visible: for every call-back, a time-stamped card in
 * four steps — events observed (with their ids) → state computed (danger and its trend) →
 * explainable insight (no goal promised) → the decision for THIS fan, NOW.
 * Shown in the STUDIO "DECISIONS" monitor and, large, in the guided story. */

import { $, app, esc, on, teamName, profile } from "./state.js";

const surname = (pid) => esc(app.roster[pid]?.name.split(" ").at(-1) || pid || "");
const clock = (e) => `${e.minute}:${String(e.second).padStart(2, "0")}`;
const decisions = [];

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

export function eventLine(e) {
  return `<div class="ev"><span class="ev-t">${clock(e)}</span><span class="ev-id">${esc(e.id)}</span><span class="ev-x">${describeEvent(e)}</span></div>`;
}

/** The four steps of one call-back, as HTML. ``big`` is the guided-story variant. */
export function decisionCard(n, { big = false } = {}) {
  const f = n.facts, d = f.decision || {};
  const fan = profile();
  const name = esc(fan?.name || "the fan");
  const team = esc(teamName(n.team));
  const evidence = (n.evidence_event_ids || []).map((id) => app.eventsById.get(id)).filter(Boolean).slice(-(big ? 4 : 3));
  const plural = (k, one, many) => `${k} ${k === 1 ? one : many}`;
  const side = f.main_channel ? `, mostly down the ${f.main_channel}` : "";
  const relation = d.relation === "attacking" ? `${team} is ${name}'s club, attacking`
    : d.relation === "defending" ? `${name}'s side is defending against ${team}` : `${name} follows a player in this match`;
  const checks = [
    d.away_for_s != null ? `${name} away for ${Math.max(1, Math.round(d.away_for_s / 60))} min` : `${name} is away`,
    relation,
    `danger ${f.danger} ≥ ${name}'s threshold ${d.threshold}, rising (+${d.slope} in 30 s)`,
    `no own shot for ${d.since_own_shot_s} s (quiet ${d.quiet_after_shot_s} s after a shot)`,
    `call ${d.alert_number} of ${d.max_alerts} this absence · cooldown ${Math.round(d.cooldown_s / 60)} min`,
  ];
  return `<div class="dc ${big ? "big" : ""}">
    <div class="dc-h"><b>${n.minute}'</b><span>CALL-BACK · DECISION CHAIN</span><em>WATCHER · ${name.toUpperCase()}</em></div>
    <ol class="dc-steps">
      <li><i>1</i><div><b>EVENTS OBSERVED</b>${evidence.length ? evidence.map(eventLine).join("")
        : `<span class="dc-x">${plural(f.box_entries, "box entry", "box entries")}, ${plural(f.shots, "shot", "shots")} in 2 min</span>`}</div></li>
      <li><i>2</i><div><b>STATE COMPUTED</b><span class="dc-x">Danger ${esc(n.team)} <em>${f.danger}</em>/100 ▲ +${d.slope} in 30 s ·
        ${plural(f.box_entries, "box entry", "box entries")}, ${plural(f.shots, "shot", "shots")} in the last 2 min${side}</span></div></li>
      <li><i>3</i><div><b>INSIGHT</b><span class="dc-x">${team} ${f.box_entries ? `got into the box ${plural(f.box_entries, "time", "times")} in 2 minutes` : "are pressing high"}${side}:
        sustained pressure, not a prediction. In unseen matches, 54% of goals came after such a call; most calls are not followed by a goal.</span></div></li>
      <li><i>4</i><div><b>DECISION · WHY ${name.toUpperCase()}, WHY NOW</b>${checks.map((c) => `<span class="dc-ok">✓ ${c}</span>`).join("")}
        <span class="dc-out">→ buzz the phone (${esc((fan?.language || "").toUpperCase())}): “${esc(n.text)}”</span></div></li>
    </ol></div>`;
}

export function initDecisions() {
  on("notification", (n) => {
    if (n.kind !== "come_back") return;
    decisions.unshift(n);
    render();
  });
  on("state", (st) => {          // (re)connect, seek, profile switch: the fan's own call-backs so far
    decisions.length = 0;
    decisions.push(...st.notifications.filter((n) => n.kind === "come_back").reverse());
    render();
  });
}

function render() {
  const el = $("#decisions");
  if (!decisions.length) {
    el.innerHTML = `<div class="empty">No call-back yet. Leave the match and the Watcher's reasoning appears here.</div>`;
    return;
  }
  el.innerHTML = decisionCard(decisions[0]) + (decisions.length > 1
    ? `<div class="dc-prev">EARLIER · ${decisions.slice(1).map((n) => `${n.minute}' danger ${n.facts.danger}`).join(" · ")}</div>` : "");
  const tally = $("#decisions-tally");
  tally.className = "tally live";
  clearTimeout(render.t);
  render.t = setTimeout(() => { tally.className = "tally amber"; }, 2500);
}
