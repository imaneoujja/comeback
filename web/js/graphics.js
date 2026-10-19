/* Broadcast graphics on the PGM: score bug, danger strip, overlay cues (one slot per layer). */

import { $, app, esc, teamColour, teamName, level, clockText } from "./state.js";

const MIN_WALL_S = { lower_third: 2.6, top_right: 2.6, banner: 5.5 };
export const TYPE_LABEL = {
  goal: "GOAL", big_chance: "BIG CHANCE", red_card: "RED CARD", penalty: "PENALTY",
  shape_change: "SHAPE CHANGE", momentum_swing: "MOMENTUM SWING", half_time: "HALF-TIME",
  full_time: "FULL-TIME", milestone: "MILESTONE", substitution: "SUBSTITUTION", danger_peak: "DANGER",
};
const slots = {};

export function renderScore() {
  const s = app.snapshot;
  if (!s) return;
  const bug = $("#scorebug");
  bug.querySelector(".sb-code.h").textContent = s.home;
  bug.querySelector(".sb-code.a").textContent = s.away;
  bug.querySelector(".sb-num.h").textContent = s.score[s.home];
  bug.querySelector(".sb-num.a").textContent = s.score[s.away];
  bug.querySelector(".sb-reds.h").innerHTML = "<i></i>".repeat(s.teams[s.home].red_cards);
  bug.querySelector(".sb-reds.a").innerHTML = "<i></i>".repeat(s.teams[s.away].red_cards);
  $("#clock").textContent = clockText(s);
  $("#bar-score").innerHTML = `<b style="color:${teamColour(s.home)}">${s.home}</b><span>${s.score[s.home]}–${s.score[s.away]}</span>
    <b style="color:${teamColour(s.away)}">${s.away}</b><span class="m">${clockText(s)}</span>`;
  $("#danger").innerHTML = `<div class="dg-title">DANGER INDEX</div>` + [s.home, s.away].map((code) => {
    const t = s.teams[code];
    const hot = t.danger >= 55 && t.danger_slope > 0;
    return `<div class="dg-row ${hot ? "hot" : ""}"><b>${code}</b><div class="dg-bar"><i style="width:${Math.min(100, t.danger)}%;background:${teamColour(code)}"></i></div><span class="dg-val">${Math.round(t.danger)}</span></div>`;
  }).join("");
}

/** SMPTE-style timecode (25 fps) running between snapshots. */
export function renderTimecode(now) {
  const s = app.snapshot;
  if (!s) return;
  const t = s.t + (app.paused ? 0 : Math.min(3, ((now - app.snapshotAt) / 1000) * app.speed));
  const h = Math.floor(t / 3600), m = Math.floor((t % 3600) / 60), sec = Math.floor(t % 60), f = Math.floor((t % 1) * 25);
  $("#timecode").textContent = [h, m, sec, f].map((n) => String(n).padStart(2, "0")).join(":");
}

export function tag(item, kind = "Analyst") {
  if (!item || item.pending) return `<span class="tags"><span class="tag wait">${kind.toUpperCase()} WRITING…</span></span>`;
  if (item.source === "llm") {
    const rev = item.attempts > 1 ? ` <span class="tag rev">REVISED ${item.attempts - 1}×</span>` : "";
    return `<span class="tags"><span class="tag">✓ ${kind.toUpperCase()} → VERIFIER</span>${rev}</span>`;
  }
  return `<span class="tags"><span class="tag tpl">TEMPLATE · VERIFIED FACTS</span></span>`;
}

export function showCue(cue) {
  const now = performance.now();
  const cur = slots[cue.layer];
  if (cur && cur.until > now && cur.priority > cue.priority) return;
  const html = cueHtml(cue);
  if (!html) return;
  const wall = Math.max(MIN_WALL_S[cue.layer], (cue.t_out - cue.t_in) / app.speed);
  put(cue.layer, html, wall, cue.priority, cue.data.moment_id);
}

export function put(layer, html, seconds, priority = 50, momentId = null) {
  slots[layer] = { until: performance.now() + seconds * 1000, priority, momentId };
  const el = $(`#ov-${layer}`);
  el.classList.remove("out");
  el.innerHTML = html;
}

export function clearOverlays() {
  for (const layer of Object.keys(slots)) { slots[layer] = null; $(`#ov-${layer}`).innerHTML = ""; }
}

export function expireOverlays(now) {
  for (const [layer, o] of Object.entries(slots)) {
    if (o && o.until < now) {
      const el = $(`#ov-${layer}`);
      el.classList.add("out");
      slots[layer] = null;
      setTimeout(() => { if (!slots[layer]) el.innerHTML = ""; }, 300);
    }
  }
}

export function refreshBanner(card) {
  const o = slots.banner;
  if (o && o.momentId === card.moment_id) $("#ov-banner").innerHTML = momentBanner(card);
}

function cueHtml(cue) {
  const d = cue.data;
  const team = `--team:${teamColour(d.team)}`;
  switch (cue.template) {
    case "player_tag": {
      const [first, ...rest] = d.player_name.split(" ");
      const stat = d.goals ? `${d.goals} GOAL${d.goals > 1 ? "S" : ""}` : `${d.passes_completed} PASSES COMPLETED`;
      return `<div class="lt" style="${team}"><div class="lt-num">${d.number}</div><div class="lt-body">
        <div class="lt-name">${esc(first)} <b>${esc(rest.join(" "))}</b></div>
        <div class="lt-meta">${esc(d.position)} · ${esc(teamName(d.team))} · ${stat}</div></div></div>`;
    }
    case "pass_quality":
      return `<div class="stat" style="${team}"><div class="stat-k">PASS DIFFICULTY · ${esc(d.label.toUpperCase())}</div>
        <div class="stat-v">${d.difficulty}<small>/100</small></div><div class="meter"><i style="width:${d.difficulty}%"></i></div>
        <div class="stat-m">${esc(d.player_name)} → ${esc(d.receiver_name)}</div>
        <div class="stat-s">${d.distance_m} M · ${Math.round(d.ball_speed_kmh)} KM/H</div></div>`;
    case "shot_speed": {
      const outcome = { goal: "GOAL", saved: "SAVED", blocked: "BLOCKED", off_target: "OFF TARGET" }[d.outcome];
      const detail = level() === "analyst" ? `XG ${d.xg.toFixed(2)} · ${outcome}` : (d.xg >= 0.25 ? `BIG CHANCE · ${outcome}` : outcome);
      return `<div class="stat" style="${team}"><div class="stat-k">SHOT SPEED</div>
        <div class="stat-v">${d.shot_speed_kmh.toFixed(1)}<small>KM/H</small></div>
        <div class="stat-m">${esc(d.player_name)}</div><div class="stat-s">${detail}</div></div>`;
    }
    case "sprint":
      return `<div class="stat" style="${team}"><div class="stat-k">TOP SPEED</div>
        <div class="stat-v">${d.speed_kmh.toFixed(1)}<small>KM/H</small></div>
        <div class="stat-m">${esc(d.player_name)}</div><div class="stat-s">${d.distance_m} M SPRINT</div></div>`;
    case "danger":
      return `<div class="bn danger" style="${team}"><div class="bn-k">DANGER ▲ ${esc(teamName(d.team).toUpperCase())}</div>
        <div class="bn-t">${d.box_entries} box entries in ${Math.round(d.window_s / 60)} minutes</div>
        <div class="bn-w">Danger index ${d.danger}/100${d.main_channel ? ` · attacking down the ${d.main_channel}` : ""}</div></div>`;
    case "moment":
      return momentBanner(app.cards.get(d.moment_id) || d);
    default:
      return "";
  }
}

export function momentBanner(card) {
  const goal = card.type === "goal";
  const score = goal && card.facts ? ` · ${card.facts.score_after}` : "";
  const why = card.why_it_matters ? `<div class="bn-w">${esc(card.why_it_matters)}</div>` : "";
  return `<div class="bn ${goal ? "goal" : ""}" style="--team:${teamColour(card.team)}">
    <div class="bn-k">${TYPE_LABEL[card.type] || ""} · ${card.minute}'${esc(score)}</div>
    <div class="bn-t">${esc(card.headline || TYPE_LABEL[card.type])}</div>${why}<div class="bn-f">${tag(card)}</div></div>`;
}
