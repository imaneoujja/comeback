/* "Who are you?": the first screen. The viewer either plays the guided story or picks
 * one demo fan and watches as that fan. The same screen comes back on "Switch". */

import { $, app, esc, teamColour, teamName } from "./state.js";

const LANG = { en: "English", fr: "Français", es: "Español" };
const HOOK = {
  omar: "Watching a 4 a.m. kick-off from another time zone. Leave whenever you like: COMEBACK calls Omar back.",
  sofia: "Supports the other side. Same match, another story, in English.",
  reda: "Follows one striker. Joins at 60' and gets the story so far, in Spanish.",
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
      <span class="wf-h">${esc(HOOK[p.id] || "")}</span><span class="wf-go">WATCH AS ${esc(p.name.toUpperCase())} ▸</span></button>`;
  }).join("");
  $("#wl-fans").addEventListener("click", (e) => {
    const card = e.target.closest("[data-fan]");
    if (card) { closePicker(); handlers.onPick(card.dataset.fan); }
  });
  $("#wl-story").addEventListener("click", () => { closePicker(); handlers.onStory(); });
  $("#welcome").classList.remove("loading");          // the match is loaded: the choices become live
  $("#wl-story").disabled = false;
  $("#wl-story-t").textContent = "Play the 90-second story";
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
