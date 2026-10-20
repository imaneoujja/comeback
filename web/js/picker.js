/* "Who are you?": the first screen. The viewer either plays the guided story or picks
 * one demo fan and watches as that fan. The same screen comes back on "Switch". */

import { $, app, esc, teamColour, teamName, IS_DEMO, DEMO_MATCH, MATCH_ID } from "./state.js";

const LANG = { en: "English", fr: "Français", es: "Español" };
const HOOK = {
  omar: "Steps away at 63' for a kids' match next door. COMEBACK calls Omar back before the big moment.",
  sofia: "Supports the other side. Same match, another story, in English.",
  reda: "Follows one striker. Joins at 60' and gets the story so far, in Spanish.",
};
const HOOK_OTHER = {
  omar: "Supports the home side. Leave whenever you like: the same Watcher calls Omar back, live.",
  sofia: "Supports the away side, in English. Same match, another story.",
  reda: "Follows the away number 9. Joins at 60' and gets the story so far, in Spanish.",
};

let handlers = {};

/** ``onPick(profileId)`` and ``onStory()`` are called from a click (audio can be unlocked there). */
export function initPicker({ onPick, onStory }) {
  handlers = { onPick, onStory };
  $("#wl-fans").innerHTML = app.profiles.map((p) => {
    const fav = app.roster[p.favourite_player_id];
    const team = p.club_id || fav?.team;
    const who = p.club_id ? `${teamName(p.club_id)} fan` : `Follows ${fav?.name || "a player"}`;
    return `<button class="wl-fan" data-fan="${p.id}" style="--team:${teamColour(team)}">
      <b>${esc(p.name)}</b><span class="wf-m">${esc(who)} · ${p.level} · ${LANG[p.language] || p.language}</span>
      <span class="wf-h">${esc((IS_DEMO ? HOOK : HOOK_OTHER)[p.id] || "")}</span><span class="wf-go">WATCH AS ${esc(p.name.toUpperCase())} ▸</span></button>`;
  }).join("");
  $("#wl-fans").addEventListener("click", (e) => {
    const card = e.target.closest("[data-fan]");
    if (card) { closePicker(); handlers.onPick(card.dataset.fan); }
  });
  $("#wl-story").addEventListener("click", () => { closePicker(); handlers.onStory(); });
  fetch("/api/matches").then((r) => r.json()).then((list) => {
    const other = list.filter((m) => m.match_id !== MATCH_ID);
    $("#wl-other").innerHTML = other.map((m) => m.match_id === DEMO_MATCH
      ? `<a href="/">← Back to the demo match (${esc(m.home)} v ${esc(m.away)}, scripted storyline)</a>`
      : `<a href="/?match=${encodeURIComponent(m.match_id)}">Try another match: ${esc(m.home)} v ${esc(m.away)}
         <small>unscripted · same engine, Watchers and Verifier, live</small></a>`).join("");
  }).catch(() => {});
  if (!IS_DEMO) {                                       // the guided story belongs to the scripted demo match
    $("#wl-story").hidden = true;
    $(".wl-or").textContent = "Unscripted match: pick a fan and watch it yourself";
  }
  $("#welcome").classList.remove("loading");          // the match is loaded: the choices become live
  $("#wl-story").disabled = false;
  $("#wl-story-t").textContent = "Play the story";
  $("#wl-story").focus();
  $("#wl-x").addEventListener("click", closePicker);
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !$("#wl-x").hidden) closePicker(); });
}

export function openPicker() {
  for (const card of document.querySelectorAll(".wl-fan")) card.classList.toggle("on", card.dataset.fan === app.profileId);
  $("#wl-x").hidden = false;                    // once the match runs, the picker can be dismissed
  $("#welcome").classList.remove("gone");
  $("#wl-story").focus();
}

function closePicker() { $("#welcome").classList.add("gone"); }
