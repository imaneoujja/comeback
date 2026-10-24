/* Broadcast graphics on the PGM: score bug, danger strip, overlay cues (one slot per layer). */

import { $, app, esc, teamColour, teamName, level, clockText, fanLabel } from "./state.js";
import { receiptLines } from "./receipt.js";

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
  const analyst = level() === "analyst";          // numbers for analysts, words for casual fans
  const word = (d) => (d >= 44 ? "HIGH" : d >= 25 ? "BUILDING" : "CALM");
  const trend = (sl) => (sl > 2 ? " ▲" : sl < -2 ? " ▼" : "");
  $("#danger").innerHTML = `<div class="dg-title">${analyst ? "DANGER · LAST 2 MIN · 0–100" : "HOW CLOSE TO A CHANCE"}</div>` + [s.home, s.away].map((code) => {
    const t = s.teams[code];
    const hot = t.danger >= 55 && t.danger_slope > 0;
    return `<div class="dg-row ${hot ? "hot" : ""}"><b>${code}</b><div class="dg-bar"><i style="width:${Math.min(100, t.danger)}%;background:${teamColour(code)}"></i></div><span class="dg-val">${analyst ? Math.round(t.danger) + trend(t.danger_slope) : word(t.danger)}</span></div>`;
  }).join("");
  renderControl();
}

/** Control vs chaos, live: who controls ball and passing (last 5 min), and how broken the game is. */
export function renderControl() {
  const s = app.snapshot;
  if (!s) return;
  const h = s.teams[s.home].control, a = s.teams[s.away].control;
  const share = h + a > 0 ? h / (h + a) : 0.5;
  const chaos = s.chaos_per_min;
  const mood = chaos >= 3.2 ? "end to end, chaotic" : chaos >= 2 ? "open game" : "calm, controlled";
  const leader = share >= 0.6 ? s.home : share <= 0.4 ? s.away : null;
  const bar = `<div class="cc-bar"><i style="width:${(share * 100).toFixed(0)}%;background:${teamColour(s.home)}"></i><i style="background:${teamColour(s.away)}"></i></div>`;
  $("#control").innerHTML = level() === "analyst"
    ? `<div class="cc-k">CONTROL vs CHAOS · 5 MIN</div>${bar}
       <div class="cc-v">${s.home} <b>${h.toFixed(2)}</b> · ${s.away} <b>${a.toFixed(2)}</b> · chaos <b>${chaos.toFixed(1)}</b>/min</div>`
    : `<div class="cc-k">THE GAME RIGHT NOW</div>${bar}
       <div class="cc-v">${leader ? `<b>${esc(teamName(leader))}</b> in control` : "Nobody in control"} · ${mood}</div>`;
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
      return speedTag(d, "SPEED", `${d.speed_kmh.toFixed(1)} KM/H`,
        `${d.distance_m} M SPRINT · ${d.distance_with_ball_m} M WITH THE BALL`);
    case "distance":
      return speedTag(d, "DISTANCE", `${d.threshold_m} M`,
        `WITH THE BALL · TOP SPEED ${d.top_speed_kmh ? d.top_speed_kmh.toFixed(1) + " KM/H" : "–"}`);
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

function speedTag(d, kicker, big, line) {
  const [first, ...rest] = d.player_name.split(" ");
  return `<div class="lt" style="--team:${teamColour(d.team)}"><div class="lt-num">${d.number}</div><div class="lt-body">
    <div class="lt-k">${kicker} · ${esc(first)} <b>${esc(rest.join(" ").toUpperCase())}</b></div>
    <div class="lt-big">${big}</div><div class="lt-meta">${line}</div></div></div>`;
}

/** Lower third for the player a fan follows ("player focus"). */
export function favouriteTag(pid) {
  const info = app.roster[pid];
  if (!info) return;
  const [first, ...rest] = info.name.split(" ");
  put("lower_third", `<div class="lt fav" style="--team:${teamColour(info.team)}"><div class="lt-num">${info.number}</div>
    <div class="lt-body"><div class="lt-k">★ YOUR PLAYER</div><div class="lt-name">${esc(first)} <b>${esc(rest.join(" "))}</b></div>
    <div class="lt-meta">${esc(info.position)} · ${esc(teamName(info.team))}</div></div></div>`, 2.8, 58);
}

const METRIC = {
  xg: { label: "xG", value: (t) => t.xg.toFixed(2) },
  possession: { label: "POSSESSION", value: (t) => `${Math.round(t.possession * 100)}%` },
  pass_difficulty: { label: "AVG PASS DIFFICULTY", value: (t) => t.avg_pass_difficulty ?? "–" },
};

/** The single number this fan said they care about (profile.focus_metric). */
export function renderMetric(fan) {
  const el = $("#metric");
  const s = app.snapshot;
  if (!fan?.focus_metric || !s) { el.hidden = true; return; }
  el.hidden = false;
  if (fan.focus_metric === "top_speed") {
    const pid = fan.favourite_player_id;
    const name = app.roster[pid]?.name.split(" ").at(-1).toUpperCase() || "";
    const mine = app.topSpeed[pid];
    const best = (code) => (s.teams[code].top_sprint_kmh ? s.teams[code].top_sprint_kmh.toFixed(1) : "–");
    el.innerHTML = `<span class="mk">YOUR METRIC · TOP SPEED</span>
      <span class="mv">${esc(name)} ${mine ? `${mine.toFixed(1)}<small>KM/H</small>` : "<small>NO SPRINT YET</small>"}</span>
      <span class="ms">MATCH BEST ${s.home} ${best(s.home)} · ${s.away} ${best(s.away)}</span>`;
    return;
  }
  const m = METRIC[fan.focus_metric];
  if (!m) { el.hidden = true; return; }
  el.innerHTML = `<span class="mk">YOUR METRIC · ${m.label}</span>
    <span class="mv"><b style="color:${teamColour(s.home)}">${s.home}</b> ${m.value(s.teams[s.home])} – ${m.value(s.teams[s.away])} <b style="color:${teamColour(s.away)}">${s.away}</b></span>`;
}

/** Full-time: the fan's own front page, written by the Storyteller, under their receipt. */
export function renderGazette(g, fan, catchupSeconds = 0) {
  const r = g.receipt ? receiptLines(g.receipt, catchupSeconds) : null;
  const s = app.snapshot;
  const home = app.teams[app.home].name, away = app.teams[app.away].name;
  const el = $("#gazette");
  el.innerHTML = `<div class="gz">
    <div class="gz-top"><span>FULL-TIME EDITION</span><span class="gz-mast">The Comeback Gazette</span>
      <span>WRITTEN FOR YOU · ${esc(fanLabel(fan).toUpperCase())} · ${esc((g.language || "").toUpperCase())}</span></div>
    ${r ? `<div class="gz-receipt"><span class="gz-rk">YOUR MATCH</span><b>${esc(r.big)}</b><small>${esc(r.small)}</small></div>` : ""}
    <div class="gz-score">${esc(home)} <b>${s ? s.score[app.home] : ""}–${s ? s.score[app.away] : ""}</b> ${esc(away)}</div>
    <h1 class="gz-h">${esc(g.headline || "")}</h1>
    <div class="gz-body"><p class="gz-text">${esc(g.text)}</p>
      <aside class="gz-side"><div class="gz-k">KEY MOMENTS</div>${(g.key_moments || []).map((k) =>
        `<div class="gz-m"><b>${k.minute}'</b> ${esc(k.headline)}</div>`).join("")}</aside></div>
    <div class="gz-foot"><span>${tag(g, "Storyteller")}</span><button class="key" id="gz-close">CLOSE</button></div></div>`;
  el.hidden = false;
  $("#gz-close").addEventListener("click", () => { el.hidden = true; });
}

export function momentBanner(card) {
  const goal = card.type === "goal";
  const score = goal && card.facts ? ` · ${card.facts.score_after}` : "";
  const why = card.why_it_matters ? `<div class="bn-w">${esc(card.why_it_matters)}</div>` : "";
  return `<div class="bn ${goal ? "goal" : ""}" style="--team:${teamColour(card.team)}">
    <div class="bn-k">${TYPE_LABEL[card.type] || ""} · ${card.minute}'${esc(score)}</div>
    <div class="bn-t">${esc(card.headline || TYPE_LABEL[card.type])}</div>${why}<div class="bn-f">${tag(card)}</div></div>`;
}

/** Milestones (top speed, 50 completed passes, fastest shot so far): a short top-right graphic. */
export function milestoneTag(card) {
  const f = card.facts || {};
  const [title, value] = {
    top_speed_so_far: ["TOP SPEED OF THE MATCH", `${f.speed_kmh} KM/H`],
    "50_completed_passes": ["50 COMPLETED PASSES", `${Math.round((f.pass_accuracy || 0) * 100)}% ACCURACY`],
    fastest_shot_so_far: ["FASTEST SHOT OF THE MATCH", `${f.shot_speed_kmh} KM/H`],
  }[f.milestone] || ["MILESTONE", ""];
  put("top_right", `<div class="stat" style="--team:${teamColour(card.team)}"><div class="stat-k">MILESTONE · ${title}</div>
    <div class="stat-m" style="font-size:20px;font-weight:700">${esc(f.player_name || "")}</div>
    <div class="stat-s">${value}</div></div>`, 4, 45);
}
