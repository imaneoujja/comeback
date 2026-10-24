/* Panels around the program feed: the fan's companion (presence, alert rules, alerts sent),
 * the "Previously on…" catch-up on the TV, and the studio's DATA, RUNDOWN and TIMELINE. */

import { $, app, esc, teamColour, sizeCanvas, emit, on, isStudio } from "./state.js";
import { TYPE_LABEL, tag } from "./graphics.js";
import { stopSpeech } from "./voice.js";
import { playVoice, stopVoice } from "./replay.js";

const NOTE_LABEL = {
  come_back: "● COME BACK", goal: "● GOAL", big_moment: "● BIG MOMENT", called_it: "✓ CALLED IT", catchup: "PREVIOUSLY ON…",
};
const FOR_LABEL = { threat: "goal threats", equaliser: "equaliser / winner", big: "any big moment", good: "if it gets good" };
const ORIGINAL = { fr: "FRANÇAIS", es: "ESPAÑOL" };
let reading = false;          // a voice-over is playing
let companionVisible = true;  // the companion panel is on screen (not scrolled away on a small screen)
const title = document.title;

on("voice", ({ playing }) => {
  reading = playing;
  const b = $("#listen");
  if (b) { b.classList.toggle("reading", playing); b.textContent = playing ? "■ STOP" : "▶ LISTEN"; }
});

/* ------------------------------------------------------------------ DATA */

export function renderData() {
  const s = app.snapshot;
  if (!s || !isStudio()) return;
  const h = s.teams[s.home], a = s.teams[s.away];
  const pct = (v) => (v == null ? "–" : `${Math.round(v * 100)}%`);
  const rows = [
    ["SHOTS", h.shots, a.shots], ["XG", h.xg.toFixed(2), a.xg.toFixed(2)],
    ["POSSESSION", pct(h.possession), pct(a.possession)], ["POSS · LAST 5'", pct(h.possession_5min), pct(a.possession_5min)],
    ["PASS ACC", pct(h.pass_accuracy), pct(a.pass_accuracy)], ["AVG PASS DIFF", h.avg_pass_difficulty ?? "–", a.avg_pass_difficulty ?? "–"],
    ["BOX ENTRIES · LAST 2'", h.last_2min.box_entries, a.last_2min.box_entries],
    ["BOX ENTRIES · MATCH", h.box_entries, a.box_entries],
    ["DANGER · LAST 2'", Math.round(h.danger), Math.round(a.danger)],
  ];
  $("#data").innerHTML = `<table><tr><th></th><th style="color:${teamColour(s.home)}">${s.home}</th><th style="color:${teamColour(s.away)}">${s.away}</th></tr>
    ${rows.map(([k, x, y]) => `<tr><td>${k}</td><td class="v">${x}</td><td class="v">${y}</td></tr>`).join("")}
    <tr><td>CHAOS · DUELS+TURNOVERS/MIN</td><td class="v" colspan="2">${s.chaos_per_min.toFixed(1)}</td></tr></table>`;
}

/* ------------------------------------------------------------------ RUNDOWN */

export function renderRundown() {
  if (!isStudio()) return;
  const list = [...app.cards.values()].filter((c) => (c.importance >= 50 && c.type !== "danger_peak") || c.type === "milestone")
    .sort((x, y) => y.t - x.t);
  $("#cards").innerHTML = list.length ? list.map((c) => `
    <div class="rd" style="--team:${teamColour(c.team)}"><span class="tcx">${c.minute}'</span><span class="ty">${TYPE_LABEL[c.type] || c.type}</span>
    <span class="hl" title="${esc(c.why_it_matters)}">${esc(c.headline)}</span>${tag(c)}</div>`).join("")
    : `<div class="empty">AWAITING FIRST KEY MOMENT…</div>`;
}

/* ------------------------------------------------------------------ TIMELINE */

export function drawTimeline() {
  const c = $("#timeline");
  const dpr = sizeCanvas(c);
  const ctx = c.getContext("2d");
  const w = c.width, h = c.height, pad = 10 * dpr, mid = h * 0.5;
  const X = (t) => pad + (t / app.durationT) * (w - 2 * pad);
  ctx.clearRect(0, 0, w, h);
  const nowT = app.snapshot?.t || 0;
  const studio = isStudio();

  for (const b of studio ? [] : app.awayBands) {
    const x0 = X(b.from_t), x1 = X(b.to_t ?? nowT), bw = Math.max(2, x1 - x0);
    ctx.save(); ctx.beginPath(); ctx.rect(x0, 2 * dpr, bw, h - 18 * dpr); ctx.clip();
    ctx.fillStyle = "rgba(255,176,0,.10)"; ctx.fillRect(x0, 0, bw, h);
    ctx.strokeStyle = "rgba(255,176,0,.22)"; ctx.lineWidth = dpr;
    for (let x = x0 - h; x < x1; x += 6 * dpr) { ctx.beginPath(); ctx.moveTo(x, h); ctx.lineTo(x + h, 0); ctx.stroke(); }
    ctx.restore();
    ctx.fillStyle = "#ffb000"; ctx.font = `500 ${9 * dpr}px "JetBrains Mono", monospace`; ctx.textAlign = "left";
    ctx.fillText(b.late_join ? "NOT WATCHING YET" : "YOU WERE AWAY", x0 + 4 * dpr, 12 * dpr);
  }

  ctx.strokeStyle = "#262626"; ctx.lineWidth = dpr;
  ctx.beginPath(); ctx.moveTo(pad, mid); ctx.lineTo(w - pad, mid); ctx.stroke();
  ctx.fillStyle = "#6f6d68"; ctx.font = `400 ${9 * dpr}px "JetBrains Mono", monospace`; ctx.textAlign = "center";
  const ht = app.timeline.find((e) => e.period === 2)?.t;
  for (let m = 0; m <= 90; m += 15) ctx.fillText(`${m}'`, X(m <= 45 ? m * 60 : (ht ?? 2700) + (m - 45) * 60), h - 3 * dpr);

  const bw = Math.max(1.5 * dpr, (w - 2 * pad) / 100 - dpr);
  for (const e of app.timeline) {
    const diff = (e.control[app.home] ?? 0) - (e.control[app.away] ?? 0);
    const bh = Math.min(1, Math.abs(diff) / 0.5) * (mid - 16 * dpr);
    ctx.fillStyle = teamColour(diff >= 0 ? app.home : app.away);
    ctx.globalAlpha = 0.7;
    ctx.fillRect(X(e.t), diff >= 0 ? mid - bh : mid, bw, bh);
  }
  ctx.globalAlpha = 1;

  // call-backs: this fan's own (fan view) or the whole audience's (studio)
  const calls = studio ? (app.crowd?.calls || []) : app.notes.filter((x) => x.kind === "come_back");
  for (const n of calls) {
    const x = X(n.t);
    ctx.strokeStyle = "rgba(255,59,48,.75)"; ctx.setLineDash([3 * dpr, 3 * dpr]);
    ctx.beginPath(); ctx.moveTo(x, 6 * dpr); ctx.lineTo(x, h - 16 * dpr); ctx.stroke(); ctx.setLineDash([]);
    ctx.fillStyle = "#ff3b30"; ctx.beginPath(); ctx.arc(x, 7 * dpr, 3.5 * dpr, 0, Math.PI * 2); ctx.fill();
  }

  for (const card of app.cards.values()) {
    const x = X(card.t);
    const y = card.team ? (card.team === app.home ? mid - 26 * dpr : mid + 26 * dpr) : mid;
    const col = card.team ? teamColour(card.team) : "#cfcdc6";
    if (card.type === "goal") {
      ctx.fillStyle = col; ctx.strokeStyle = "#fff"; ctx.lineWidth = 1.6 * dpr;
      ctx.beginPath(); ctx.arc(x, y, 6 * dpr, 0, Math.PI * 2); ctx.fill(); ctx.stroke();
    } else if (card.type === "red_card") {
      ctx.fillStyle = "#ff3b30"; ctx.fillRect(x - 3 * dpr, y - 5 * dpr, 6 * dpr, 10 * dpr);
    } else if (card.type === "shape_change") {
      ctx.fillStyle = col; ctx.beginPath();
      ctx.moveTo(x, y - 6 * dpr); ctx.lineTo(x + 6 * dpr, y); ctx.lineTo(x, y + 6 * dpr); ctx.lineTo(x - 6 * dpr, y); ctx.fill();
    } else if (card.type === "big_chance") {
      ctx.strokeStyle = col; ctx.lineWidth = 1.8 * dpr; ctx.beginPath(); ctx.arc(x, y, 5 * dpr, 0, Math.PI * 2); ctx.stroke();
    } else if (card.type === "half_time") {
      ctx.strokeStyle = "#3a3a3a"; ctx.beginPath(); ctx.moveTo(x, 4 * dpr); ctx.lineTo(x, h - 16 * dpr); ctx.stroke();
    }
  }
  ctx.strokeStyle = "#ffb000"; ctx.lineWidth = 1.5 * dpr;
  ctx.beginPath(); ctx.moveTo(X(nowT), 2 * dpr); ctx.lineTo(X(nowT), h - 14 * dpr); ctx.stroke();
}

/* ------------------------------------------------------------------ the fan's companion */

export function renderPresence() {
  const el = $("#presence");
  const band = app.awayBands.at(-1);
  if (app.present) {
    el.className = "cp-presence";
    el.innerHTML = `<i></i><span>WATCHING LIVE</span>`;
  } else {
    el.className = "cp-presence away";
    el.innerHTML = `<i></i><span>AWAY SINCE ${band ? minuteAt(band.from_t) : ""}'<small>COMEBACK is watching the match for you</small></span>`;
  }
  $("#btn-away").disabled = !app.present;
  $("#btn-back").disabled = app.present;
  $("#away-veil").hidden = app.present || isStudio();
}

function minuteAt(t) {
  const e = [...app.timeline].reverse().find((x) => x.t <= t);
  return e ? e.minute : Math.floor(t / 60);
}

export function renderNotes() {
  const el = $("#notes");
  if (!app.notes.length) {
    el.innerHTML = `<div class="empty">Nothing yet. Step away and COMEBACK watches the match for you.</div>`;
    return;
  }
  el.innerHTML = app.notes.slice(0, 5).map((n) => `
    <div class="note ${n.kind}"><div class="note-h"><b>${NOTE_LABEL[n.kind] || n.kind}${n.silent ? " · SILENT" : ""}</b><span>${n.minute}'</span></div>
    <div class="note-x">${esc(n.text)}</div></div>`).join("");
}

/** The fan's alert rules (opt-in). */
export function renderPrefs() {
  const st = app.settings || { alert_for: "threat", spoilers: false, night: false };
  for (const b of document.querySelectorAll("#pref-for button")) b.classList.toggle("on", b.dataset.for === st.alert_for);
  $("#pref-night").checked = st.night;
  $("#pref-spoilers").checked = st.spoilers;
  $("#prefs-sum").textContent = `${FOR_LABEL[st.alert_for]}${st.night ? " · night" : ""} · ${st.spoilers ? "scores on" : "no spoilers"}`;
}

/** On a small screen the companion can be scrolled away: notifications then also appear as a toast. */
export function initToast() {
  const panel = $("#companion");
  new IntersectionObserver(([e]) => { companionVisible = e.intersectionRatio > 0.2; }, { threshold: [0, 0.2, 1] }).observe(panel);
  $("#toast").addEventListener("click", () => {
    panel.scrollIntoView({ behavior: "smooth", block: "start" });
    $("#toast").hidden = true;
  });
  document.addEventListener("visibilitychange", () => { if (!document.hidden) document.title = title; });
}

/** A notification reached the fan: flag the browser tab if they switched away, a toast if the panel is hidden. */
export function notify(n) {
  if (document.hidden) document.title = `${n.kind === "come_back" ? "● COME BACK" : NOTE_LABEL[n.kind] || "●"} · ${n.text}`;
  const panel = $("#companion");
  panel.classList.remove("ping"); void panel.offsetWidth; panel.classList.add("ping");
  if (companionVisible) return;
  const el = $("#toast");
  el.className = `toast ${n.kind}`;
  el.innerHTML = `<b>${NOTE_LABEL[n.kind] || ""}${n.minute ? ` · ${n.minute}'` : ""}</b><span>${esc(n.text)}</span>`;
  el.hidden = false;
  clearTimeout(notify.timer);
  notify.timer = setTimeout(() => { el.hidden = true; }, 7000);
}

/* ------------------------------------------------------------------ "Previously on…" on the TV */

export function renderCatchup(c) {
  const d = c.delta || {};
  const head = c.final ? "FULL-TIME" : c.late_join ? "THE STORY SO FAR" : `WHILE YOU WERE AWAY · ${d.away_minutes} MIN`;
  const title = c.final ? c.headline || "Full-time" : c.late_join ? "Previously on…" : "Welcome back";
  const chips = [
    d.score_then != null ? `<span class="chip">${esc(d.score_then)} → <b>${esc(d.score_now)}</b></span>` : "",
    d.in_control_now ? `<span class="chip">IN CONTROL: ${d.in_control_then && !c.late_join ? `${esc(d.in_control_then)} → ` : ""}<b>${esc(d.in_control_now)}</b></span>` : "",
    d.players_on_pitch_now ? `<span class="chip">${Object.entries(d.players_on_pitch_now).map(([t, n]) => `${esc(t)} ${n}`).join(" v ")}</span>` : "",
  ].join("");
  const el = $("#catchup");
  el.hidden = false;
  el.innerHTML = `<div class="cu-k"><span>${head}</span><button aria-label="Close" id="cu-close">×</button></div>
    <div class="cu-t">${esc(title)}</div><div class="chips">${chips}</div>
    <div class="cu-text">${esc(c.text)}</div>
    <div class="cu-ai" id="cu-ai">AI-written for you · fact-checked against the match data${c.source === "template" ? " (template)" : ""}</div>
    <div class="cu-f">${tag(c, "Storyteller")}<span class="cu-btns">${c.missed?.players?.length ? `<button class="key hot" id="to-missed">WHAT YOU MISSED ▸</button>` : ""}${c.text_en ? `<button class="key" id="show-en">SHOW ENGLISH</button>` : ""}
      <button class="key ${reading ? "reading" : ""}" id="listen" aria-label="Read the catch-up aloud">${reading ? "■ STOP" : "▶ LISTEN"}</button></span></div>`;
  el.classList.remove("in"); void el.offsetWidth; el.classList.add("in");
  $("#cu-close").addEventListener("click", hideCatchup);
  $("#to-missed")?.addEventListener("click", () => emit("show-missed", {}));
  $("#show-en")?.addEventListener("click", (e) => {        // for viewers who do not read the fan's language
    const english = e.target.textContent === "SHOW ENGLISH";
    el.querySelector(".cu-text").textContent = english ? c.text_en : c.text;
    $("#cu-ai").textContent = english ? "English translation (AI), checked: same numbers and names as the original"
      : "AI-written for you · fact-checked against the match data";
    e.target.textContent = english ? `SHOW ${ORIGINAL[c.language] || "ORIGINAL"}` : "SHOW ENGLISH";
  });
  $("#listen").addEventListener("click", () => (reading ? stopVoice() : playVoice(c)));
}

export function hideCatchup() {
  stopVoice();
  stopSpeech();
  const el = $("#catchup"); el.hidden = true; el.innerHTML = "";
  emit("catchup-closed", {});
}
