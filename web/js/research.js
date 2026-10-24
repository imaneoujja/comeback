/* Studio RESEARCH DESK: a commentator's notes. On top, ONE card: the next talking point the
 * Researcher recommends, with its source in the league's records. Below, tabs: This match (the
 * engine's pictures), Standings, Form, Players, Injuries, Head-to-head — synthetic league data. */

import { $, app, esc, on, post, teamColour, teamName } from "./state.js";
import { renderMatchInsights, fetchInsights } from "./insights.js";

const LANG = { en: "EN", fr: "FR", es: "ES" };
const TYPE = { goal: "GOAL", big_chance: "BIG CHANCE", red_card: "RED CARD", penalty: "PENALTY", shape_change: "SHAPE CHANGE",
  momentum_swing: "MOMENTUM SWING", half_time: "HALF-TIME", full_time: "FULL-TIME" };
let league = null;
let leagueFor = null;
let tab = "match";
let points = [];
let lang = "en";
let insightsTimer = null;

export function initResearch() {
  $("#rtabs").addEventListener("click", (e) => { if (e.target.dataset.rtab) showRight(e.target.dataset.rtab); });
  $("#desk-tabs").addEventListener("click", (e) => { if (e.target.dataset.dtab) { tab = e.target.dataset.dtab; renderPane(); } });
  $("#tp-card").addEventListener("click", (e) => {
    const l = e.target.dataset.lang;
    if (l && l !== lang) { lang = l; renderTalking(); post(`research?lang=${l}`); }
  });
  on("state", (s) => {
    points = s.talking_points || [];
    lang = s.research_lang || lang;
    app.talking = Object.fromEntries(points.map((tp) => [tp.moment_id, tp]));
    loadLeague().then(() => { renderTalking(); renderPane(); });
  });
  on("talking_point", (tp) => {
    points = [...points.filter((p) => p.moment_id !== tp.moment_id), tp].sort((a, b) => a.t - b.t);
    app.talking = { ...(app.talking || {}), [tp.moment_id]: tp };
    renderTalking();
  });
  on("talking_points", (list) => { points = list; app.talking = Object.fromEntries(list.map((tp) => [tp.moment_id, tp])); renderTalking(); });
}

function showRight(which) {
  for (const b of document.querySelectorAll("#rtabs [data-rtab]")) b.classList.toggle("on", b.dataset.rtab === which);
  $("#feed").hidden = which !== "feed";
  $("#desk").hidden = which !== "desk";
  $("#rtab-src").textContent = which === "feed" ? "ENGINE → ANALYST → VERIFIER → WATCHER" : `RESEARCHER · SYNTHETIC LEAGUE ${league?.season || ""}`;
  if (which === "desk") renderPane();
}

async function loadLeague() {
  if (leagueFor === app.matchId && league) return;
  leagueFor = app.matchId;
  league = await fetch(`/api/league/${app.matchId}`).then((r) => r.json()).catch(() => null);
}

/* ------------------------------------------------------------------ the one card on top */
function renderTalking() {
  const el = $("#tp-card");
  const tp = points.at(-1);
  const langs = Object.entries(LANG).map(([k, v]) => `<button data-lang="${k}" class="${k === lang ? "on" : ""}">${v}</button>`).join("");
  if (!tp) {
    el.innerHTML = `<div class="tp-k"><span>NEXT TALKING POINT</span><span class="seg tp-lang">${langs}</span></div>
      <p class="tp-wait">At the next key moment, the Researcher pulls context from the league's records: the scorer's season,
      the table if the score holds, form, injuries, head-to-head.</p>`;
    return;
  }
  el.innerHTML = `<div class="tp-k"><span>NEXT TALKING POINT · ${tp.minute}' ${TYPE[tp.type] || ""}${tp.team ? ` · ${esc(teamName(tp.team))}` : ""}</span>
      <span class="b ${tp.source === "llm" ? "pre" : "tpl"}">${tp.source === "llm" ? "researcher → verifier" : "template"}</span>
      <span class="seg tp-lang">${langs}</span></div>
    ${tp.points.map((p) => `<div class="tp-point" style="--team:${teamColour(tp.team)}"><b>${esc(p.text)}</b>
      <small>Source: ${esc(p.source)}</small></div>`).join("")}`;
}

/* ------------------------------------------------------------------ tabs */
async function renderPane() {
  const el = $("#desk-pane");
  for (const b of document.querySelectorAll("#desk-tabs button")) b.classList.toggle("on", b.dataset.dtab === tab);
  clearInterval(insightsTimer);
  if (tab === "match") {
    const draw = async () => { if (!$("#desk").hidden && tab === "match") renderMatchInsights(el, await fetchInsights(), true); };
    await draw();
    insightsTimer = setInterval(draw, 8000);
    return;
  }
  if (!league) { el.innerHTML = `<div class="in-empty">League data unavailable.</div>`; return; }
  el.innerHTML = { standings, form, players, injuries, h2h }[tab]();
}

const live = () => [league.home, league.away];
const clubCell = (c, name) => `<span class="club"><i style="background:${league.colours?.[c] || "#666"}"></i>${esc(name || league.standings.find((r) => r.club === c)?.name || c)}</span>`;
const dots = (form) => form.map((f) => `<i class="fd ${f}">${f}</i>`).join("");

function standings() {
  return `<div class="dk-k">${esc(league.season)} · AFTER MATCHDAY ${league.matchday - 1} · LIVE MATCH IN BOLD</div>
    <table class="dk-table"><tr><th>#</th><th></th><th>P</th><th>W</th><th>D</th><th>L</th><th>GD</th><th>PTS</th><th>FORM</th></tr>
    ${league.standings.map((r) => `<tr class="${live().includes(r.club) ? "live" : ""}"><td>${r.pos}</td><td>${clubCell(r.club, r.name)}</td>
      <td>${r.p}</td><td>${r.w}</td><td>${r.d}</td><td>${r.l}</td><td>${r.gd > 0 ? "+" : ""}${r.gd}</td><td><b>${r.pts}</b></td>
      <td class="dots">${dots(r.form)}</td></tr>`).join("")}</table>`;
}

function form() {
  return `<div class="dk-k">LAST FIVE MATCHES · OLDEST → LATEST</div>${league.standings.filter((r) => live().includes(r.club)).concat(
    league.standings.filter((r) => !live().includes(r.club))).map((r) => `
    <div class="dk-form ${live().includes(r.club) ? "live" : ""}">${clubCell(r.club, r.name)}<span class="dots big">${dots(r.form)}</span>
      <span class="dk-m">${r.form.filter((f) => f === "W").length} W · ${r.gf} scored · ${r.ga} conceded</span></div>`).join("")}`;
}

function players() {
  const block = (title, rows, value) => `<div class="dk-lead"><div class="dk-k">${title}</div>${rows.map((p, i) => `
    <div class="dk-row"><span class="n">${i + 1}</span><span class="who">${esc(p.name)}<small>${esc(league.standings.find((r) => r.club === p.club)?.name || p.club)}</small></span>
      <b>${value(p)}</b></div>`).join("")}</div>`;
  const L = league.leaders;
  return `<div class="dk-grid">${block("GOALS", L.goals, (p) => p.goals)}${block("ASSISTS", L.assists, (p) => p.assists)}
    ${block("xG", L.xg, (p) => p.xg.toFixed(1))}${block("TOP SPEED · KM/H", L.top_speed_kmh, (p) => p.top_speed_kmh.toFixed(1))}</div>
    <div class="dk-rec">Season records: fastest shot <b>${esc(league.records.fastest_shot.name)}</b> ${league.records.fastest_shot.fastest_shot_kmh} km/h ·
      biggest win <b>${esc(clubName(league.records.biggest_win.home))} ${league.records.biggest_win.score.join("-")} ${esc(clubName(league.records.biggest_win.away))}</b>
      (matchday ${league.records.biggest_win.matchday})</div>`;
}

const clubName = (c) => league.standings.find((r) => r.club === c)?.name || c;

function injuries() {
  const rows = [...league.unavailable].sort((a, b) => live().includes(b.club) - live().includes(a.club));
  return `<div class="dk-k">UNAVAILABLE FOR MATCHDAY ${league.matchday}</div>${rows.map((u) => `
    <div class="dk-inj ${live().includes(u.club) ? "live" : ""}">${clubCell(u.club)}<b>${esc(u.name)}</b>
      <span>${esc(u.reason)}</span><small>${u.kind === "injury" ? `out since matchday ${u.since_matchday} · back matchday ${u.back_matchday}` : "suspended"}</small></div>`).join("")
    || `<div class="in-empty">Everyone is available.</div>`}`;
}

function h2h() {
  const rows = [...league.head_to_head].reverse();
  const wins = (c) => league.head_to_head.filter((m) => (m.home === c && m.score[0] > m.score[1]) || (m.away === c && m.score[1] > m.score[0])).length;
  const draws = league.head_to_head.filter((m) => m.score[0] === m.score[1]).length;
  return `<div class="dk-k">${esc(clubName(league.home))} v ${esc(clubName(league.away))} · SINCE LAST SEASON</div>
    <div class="dk-h2h"><div><b>${wins(league.home)}</b><span>${esc(clubName(league.home))} wins</span></div><div><b>${draws}</b><span>draws</span></div>
      <div><b>${wins(league.away)}</b><span>${esc(clubName(league.away))} wins</span></div></div>
    ${rows.map((m) => `<div class="dk-row"><span class="n">${esc(m.season)}</span><span class="who">matchday ${m.matchday}</span>
      <b>${esc(clubName(m.home))} ${m.score[0]}-${m.score[1]} ${esc(clubName(m.away))}</b></div>`).join("")}`;
}
