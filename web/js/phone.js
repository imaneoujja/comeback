/* The fan's real phone, paired with a control-room session through a QR code.
 * iPhone Safari cannot vibrate, so a call-back takes over the screen, rings, and
 * speaks the reason out loud in the fan's language (unlocked by the first tap). */

import { speak, unlockSpeech, stopSpeech } from "./voice.js";

const $ = (s) => document.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const session = new URLSearchParams(location.search).get("session");
const st = { profile: null, present: true, notes: [], snapshot: null, teams: {} };
let audio = null;
let pendingSpeech = null;            // text waiting for the profile (its language) to arrive

if (!session) {
  $("#pair-hint").textContent = "Open this page by scanning the QR code shown in the COMEBACK control room.";
  $("#pair-btn").disabled = true;
}

$("#pair-btn").addEventListener("click", async () => {
  unlockSound();
  try { await navigator.wakeLock?.request("screen"); } catch { /* not supported: fine */ }
  const match = await fetch("/api/match/demo-comeback").then((r) => r.json());
  for (const side of ["home", "away"]) st.teams[match[side].id] = match[side];
  connect();
});
$("#away").addEventListener("click", () => post("away"));
$("#back").addEventListener("click", () => post("back"));
$("#to-back").addEventListener("click", () => { closeTakeover(); post("back"); });
$("#to-x").addEventListener("click", closeTakeover);

function post(action) { return fetch(`/api/session/${session}/${action}`, { method: "POST" }); }

/* ------------------------------------------------------------------ sound & voice (iOS needs a user tap first) */

function unlockSound() {
  audio = new (window.AudioContext || window.webkitAudioContext)();
  const buf = audio.createBuffer(1, 1, 22050);
  const src = audio.createBufferSource(); src.buffer = buf; src.connect(audio.destination); src.start(0);
  unlockSpeech();
}

function ring(notes = [880, 1320, 880, 1320]) {
  if (!audio) return;
  notes.forEach((f, i) => {
    const o = audio.createOscillator(), g = audio.createGain();
    const t0 = audio.currentTime + i * 0.22;
    o.frequency.value = f; o.type = "sine";
    g.gain.setValueAtTime(0.0001, t0); g.gain.exponentialRampToValueAtTime(0.5, t0 + 0.02); g.gain.exponentialRampToValueAtTime(0.0001, t0 + 0.2);
    o.connect(g).connect(audio.destination); o.start(t0); o.stop(t0 + 0.21);
  });
}

function say(text) {
  if (!st.profile) { pendingSpeech = text; return; }      // never guess the language
  speak(text, st.profile.language);
}

/* ------------------------------------------------------------------ stream */

function connect() {
  const es = new EventSource(`/api/stream?session=${encodeURIComponent(session)}&device=true`);
  const on = (type, fn) => es.addEventListener(type, (m) => fn(JSON.parse(m.data)));
  es.onopen = () => { $("#ph-live").textContent = "● PAIRED"; $("#ph-live").className = "ph-live on"; };
  es.onerror = () => { $("#ph-live").textContent = "RECONNECTING…"; $("#ph-live").className = "ph-live"; };
  on("state", (s) => {
    Object.assign(st, { profile: s.profile, present: s.present, notes: [...s.notifications].reverse(), snapshot: s.snapshot });
    $("#pair").hidden = true; $("#main").hidden = false;
    render();
    if (pendingSpeech) { const text = pendingSpeech; pendingSpeech = null; say(text); }
  });
  on("snapshot", (s) => { st.snapshot = s; renderScore(); });
  on("presence", (p) => { st.present = p.present; if (!p.present) $("#catchup").hidden = true; render(); });
  on("notification", (n) => { st.notes.unshift(n); renderNotes(); takeover(n); });
  on("catchup", renderCatchup);
  on("gazette", (g) => renderCatchup({ ...g, final: true }));
}

/* ------------------------------------------------------------------ render */

function render() {
  const p = st.profile;
  if (p) {
    const team = p.club_id ? st.teams[p.club_id]?.name : null;
    $("#who").innerHTML = `<b>${esc(p.name)}</b> · ${team ? `supports ${esc(team)}` : "neutral"} · ${p.language.toUpperCase()}`;
  }
  $("#state").className = `state ${st.present ? "" : "away"}`;
  $("#state").textContent = st.present ? "● WATCHING THE MATCH" : "● AWAY — COMEBACK IS WATCHING FOR YOU";
  $("#away").disabled = !st.present;
  $("#back").disabled = st.present;
  renderScore(); renderNotes();
}

function renderScore() {
  const s = st.snapshot;
  if (!s) return;
  $("#score").innerHTML = `<b>${s.home} ${s.score[s.home]}–${s.score[s.away]} ${s.away}</b> &nbsp; ${s.minute}'`;
}

function renderNotes() {
  $("#notes").innerHTML = st.notes.length ? st.notes.slice(0, 8).map((n) => `
    <div class="note ${n.kind}"><div class="nh"><b>${n.kind === "come_back" ? "● COME BACK" : "● GOAL"}</b><span>${n.minute}'</span></div>
    <div class="nx">${esc(n.text)}</div></div>`).join("") : `<div class="empty">Leave the match: COMEBACK will call you back before the big moment.</div>`;
}

function takeover(n) {
  const el = $("#takeover");
  el.className = `takeover ${n.kind === "goal" ? "goal" : ""}`;
  $("#to-k").textContent = n.kind === "goal" ? `GOAL · ${n.minute}'` : `COME BACK · ${n.minute}'`;
  $("#to-t").textContent = n.text;
  el.hidden = false;
  ring(n.kind === "goal" ? [660, 990, 1320] : undefined);
  setTimeout(() => say(n.text), 900);
}

function closeTakeover() { $("#takeover").hidden = true; stopSpeech(); }

function renderCatchup(c) {
  closeTakeover();
  const d = c.delta || {};
  const el = $("#catchup");
  el.hidden = false;
  el.innerHTML = `<div class="ck">PREVIOUSLY ON…</div>
    <div class="ct">${c.final ? esc(c.headline || "Full-time") : c.late_join ? "The story so far" : `You were away ${d.away_minutes} min`}</div>
    <div class="cx">${esc(c.text)}</div>
    <div class="cf"><span>${c.source === "llm" ? "✓ STORYTELLER → VERIFIER" : "TEMPLATE · VERIFIED FACTS"}</span>
    <button class="btn" id="listen">▶ LISTEN</button></div>`;
  $("#listen").addEventListener("click", () => speak(c.text, c.language || st.profile?.language));
}
