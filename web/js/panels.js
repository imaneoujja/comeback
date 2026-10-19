/* Gallery monitors: DATA, RUNDOWN, TIMELINE and the FAN device feed. */

import { $, app, esc, teamColour, teamName, profile, sizeCanvas } from "./state.js";
import { TYPE_LABEL, tag } from "./graphics.js";

const LANG_LABEL = { en: "English", fr: "Français", es: "Español" };

/* ------------------------------------------------------------------ DATA */

export function renderData() {
  const s = app.snapshot;
  if (!s) return;
  const h = s.teams[s.home], a = s.teams[s.away];
  const pct = (v) => (v == null ? "–" : `${Math.round(v * 100)}%`);
  const rows = [
    ["SHOTS", h.shots, a.shots], ["XG", h.xg.toFixed(2), a.xg.toFixed(2)],
    ["POSSESSION", pct(h.possession), pct(a.possession)], ["POSS · LAST 5'", pct(h.possession_5min), pct(a.possession_5min)],
    ["PASS ACC", pct(h.pass_accuracy), pct(a.pass_accuracy)], ["AVG PASS DIFF", h.avg_pass_difficulty ?? "–", a.avg_pass_difficulty ?? "–"],
    ["BOX ENTRIES", h.box_entries, a.box_entries], ["PLAYERS", h.players_on_pitch, a.players_on_pitch],
  ];
  $("#data").innerHTML = `<table><tr><th></th><th style="color:${teamColour(s.home)}">${s.home}</th><th style="color:${teamColour(s.away)}">${s.away}</th></tr>
    ${rows.map(([k, x, y]) => `<tr><td>${k}</td><td class="v">${x}</td><td class="v">${y}</td></tr>`).join("")}</table>
    <div>CHAOS ${s.chaos_per_min.toFixed(1)} DUELS+TURNOVERS/MIN</div>`;
}

/* ------------------------------------------------------------------ RUNDOWN */

export function renderRundown() {
  const list = [...app.cards.values()].filter((c) => c.importance >= 50 && c.type !== "danger_peak").sort((x, y) => y.t - x.t);
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

  for (const b of app.awayBands) {
    const x0 = X(b.from_t), x1 = X(b.to_t ?? nowT), bw = Math.max(2, x1 - x0);
    ctx.save(); ctx.beginPath(); ctx.rect(x0, 2 * dpr, bw, h - 18 * dpr); ctx.clip();
    ctx.fillStyle = "rgba(160,160,160,.12)"; ctx.fillRect(x0, 0, bw, h);
    ctx.strokeStyle = "rgba(160,160,160,.25)"; ctx.lineWidth = dpr;
    for (let x = x0 - h; x < x1; x += 6 * dpr) { ctx.beginPath(); ctx.moveTo(x, h); ctx.lineTo(x + h, 0); ctx.stroke(); }
    ctx.restore();
    ctx.fillStyle = "#9a9892"; ctx.font = `500 ${9 * dpr}px "JetBrains Mono", monospace`; ctx.textAlign = "left";
    ctx.fillText(b.late_join ? "NOT WATCHING" : "AWAY", x0 + 4 * dpr, 12 * dpr);
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

  for (const n of app.notes.filter((x) => x.kind === "come_back")) {
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

/* ------------------------------------------------------------------ FAN DEVICE */

export function renderProfiles() {
  $("#profiles").innerHTML = app.profiles.map((p) => {
    const team = p.club_id || app.roster[p.favourite_player_id]?.team;
    return `<button class="profile ${p.id === app.profileId ? "on" : ""}" data-profile="${p.id}" role="tab"
      aria-selected="${p.id === app.profileId}"><b><i style="background:${teamColour(team)}"></i>${esc(p.name)}</b>
      ${p.language.toUpperCase()} · ${p.level.toUpperCase()}</button>`;
  }).join("");
  const p = profile();
  if (!p) return;
  const who = p.club_id ? `supports <b>${esc(teamName(p.club_id))}</b>`
    : `follows <b>${esc(app.roster[p.favourite_player_id]?.name)}</b> (${esc(app.roster[p.favourite_player_id]?.team)})`;
  $("#fan-card").innerHTML = `<b>${esc(p.name)}</b> ${who} · ${p.level} view · ${LANG_LABEL[p.language]}`;
  $("#fan-src").textContent = `DEVICE FEED · ${p.name.toUpperCase()} · ${p.language.toUpperCase()}`;
}

export function renderPresence() {
  const el = $("#presence");
  const band = app.awayBands.at(-1);
  if (app.present) {
    el.className = "presence";
    el.innerHTML = `<i></i><span>WATCHING LIVE</span>`;
  } else {
    el.className = "presence away";
    el.innerHTML = `<i></i><span>AWAY SINCE ${band ? minuteAt(band.from_t) : ""}'<small>COMEBACK is watching the match for this fan</small></span>`;
  }
  $("#btn-away").disabled = !app.present;
  $("#btn-back").disabled = app.present;
  $("#away-veil").hidden = app.present;
  $("#fan-tally").className = `tally ${app.present ? "green" : "amber"}`;
}

function minuteAt(t) {
  const e = [...app.timeline].reverse().find((x) => x.t <= t);
  return e ? e.minute : Math.floor(t / 60);
}

export function renderNotes() {
  const el = $("#notes");
  if (!app.notes.length) { el.innerHTML = `<div class="empty">Nothing yet. Leave the match and COMEBACK watches it for you.</div>`; return; }
  el.innerHTML = app.notes.slice(0, 6).map((n) => `
    <div class="note ${n.kind}"><div class="note-h"><b>${n.kind === "come_back" ? "● COME BACK" : "● GOAL"}</b><span>${n.minute}'</span></div>
    <div class="note-x">${esc(n.text)}</div></div>`).join("");
}

export function buzz() {
  const fan = document.querySelector(".mon.fan");
  fan.classList.remove("buzz"); void fan.offsetWidth; fan.classList.add("buzz");
}

export function renderCatchup(c) {
  const d = c.delta || {};
  const title = c.late_join ? "The story so far" : `While you were away · ${d.away_minutes} min`;
  const chips = [
    `<span class="chip">${esc(d.score_then)} → <b>${esc(d.score_now)}</b></span>`,
    d.in_control_now ? `<span class="chip">IN CONTROL: ${d.in_control_then && !c.late_join ? `${esc(d.in_control_then)} → ` : ""}<b>${esc(d.in_control_now)}</b></span>` : "",
    d.players_on_pitch_now ? `<span class="chip">${Object.entries(d.players_on_pitch_now).map(([t, n]) => `${esc(t)} ${n}`).join(" v ")}</span>` : "",
  ].join("");
  const el = $("#catchup");
  el.hidden = false;
  el.innerHTML = `<div class="cu-k"><span>PREVIOUSLY ON…</span><button aria-label="Close" id="cu-close">×</button></div>
    <div class="cu-t">${esc(title)}</div><div class="chips">${chips}</div>
    <div class="cu-text">${esc(c.text)}</div>
    <div class="cu-f">${tag(c, "Storyteller")}${"speechSynthesis" in window ? `<button class="key" id="listen">▶ LISTEN</button>` : ""}</div>`;
  $("#cu-close").addEventListener("click", hideCatchup);
  $("#listen")?.addEventListener("click", () => speak(c.text, c.language));
}

function speak(text, lang) {
  speechSynthesis.cancel();
  const u = new SpeechSynthesisUtterance(text);
  u.lang = { en: "en-GB", fr: "fr-FR", es: "es-ES" }[lang] || "en-GB";
  speechSynthesis.speak(u);
}

export function hideCatchup() {
  if ("speechSynthesis" in window) speechSynthesis.cancel();
  const el = $("#catchup"); el.hidden = true; el.innerHTML = "";
}
