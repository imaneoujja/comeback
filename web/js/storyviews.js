/* Views used by the guided story on the program feed:
 * - "pitchside": the TV is off for the fan, but the engine keeps ingesting every event
 *   (live event feed) and the Watcher's decision chain appears when it calls;
 * - "personalize": the same moment as three fans get it, side by side. */

import { $, app, esc, on, teamColour, teamName } from "./state.js";
import { eventLine, decisionCard } from "./decision.js";

const LANG = { en: "English", fr: "French", es: "Spanish" };
const possessive = (name) => (name.endsWith("s") ? `${name}'` : `${name}'s`);
let feed = [];

export function initStoryViews() {
  on("event", (e) => {
    if ($("#pitchside").hidden || ["period_start", "period_end"].includes(e.type)) return;
    feed.unshift(eventLine(e));
    feed.length = Math.min(feed.length, 9);
    $("#ps-feed").innerHTML = feed.join("");
  });
}

export function showPitchside(show) {
  const el = $("#pitchside");
  el.hidden = !show;
  if (show) { feed = []; $("#ps-feed").innerHTML = ""; $("#ps-dc").innerHTML = ""; el.classList.remove("calling"); }
}

export function pitchsideDecision(note) {
  $("#ps-dc").innerHTML = decisionCard(note, { big: true });
  $("#pitchside").classList.add("calling");
}

/** Three demo fans, one moment: the 69' call-back and the 71' shot as each of them gets it. */
export function showPersonalize(call, shot) {
  const el = $("#personalize");
  if (!call) { el.hidden = true; return; }
  const s = app.snapshot;
  const cols = app.profiles.map((p) => {
    const fav = app.roster[p.favourite_player_id];
    const side = p.club_id || fav?.team;
    const variant = call.variants?.[p.id];
    const analyst = p.level === "analyst";
    const shotLine = shot ? `SHOT SPEED ${shot.shot_speed_kmh.toFixed(1)} KM/H · ${analyst ? `XG ${shot.xg.toFixed(2)} · ` : ""}${shot.outcome === "goal" ? "GOAL" : shot.outcome.toUpperCase()}` : "—";
    const metric = p.focus_metric === "xg" ? `xG ${s.home} ${s.teams[s.home].xg.toFixed(2)} – ${s.teams[s.away].xg.toFixed(2)} ${s.away}`
      : p.focus_metric === "possession" ? `Possession ${s.home} ${Math.round(s.teams[s.home].possession * 100)}% – ${Math.round(s.teams[s.away].possession * 100)}% ${s.away}`
      : p.focus_metric === "top_speed" ? `${esc(fav?.name.split(" ").at(-1) || "")} top speed <span data-top="${p.favourite_player_id}">…</span>` : "—";
    const focus = fav ? `★ ${esc(fav.name)} tagged all match (player mode)` : `${esc(teamName(p.club_id))} first`;
    return `<div class="pz-col" style="--team:${teamColour(side)}">
      <div class="pz-h"><span class="av" style="background:${teamColour(side)}">${esc(p.name[0])}</span>
        <div><b>${esc(p.name)}</b><small>${p.club_id ? `${esc(teamName(p.club_id))} fan` : "follows a player"} · ${p.level} · ${LANG[p.language]}</small></div></div>
      <div class="pz-k">THE ${call.minute}' CALL-BACK</div><div class="pz-v">“${esc(variant?.text || "")}”</div>
      <div class="pz-k">THE 71' SHOT ON THEIR SCREEN</div><div class="pz-v mono">${shotLine}</div>
      <div class="pz-k">FOCUS</div><div class="pz-v">${focus}</div>
      <div class="pz-k">THEIR ONE METRIC</div><div class="pz-v mono">${metric}</div>
      <div class="pz-k">TOLD FROM</div><div class="pz-v">${esc(possessive(teamName(side)))} side, in ${LANG[p.language]}</div></div>`;
  }).join("");
  el.innerHTML = `<div class="pz"><div class="pz-top"><b>PERSONALIZE</b> · SAME MOMENT, THREE FANS
    <span>One set of verified facts. Language, depth, side and metric change per fan.</span></div>
    <div class="pz-cols">${cols}</div></div>`;
  el.hidden = false;
  for (const span of el.querySelectorAll("[data-top]")) {     // the engine's figure, not just the sprints seen live
    fetch(`/api/session/${app.session}/player/${span.dataset.top}`).then((r) => r.json())
      .then((pl) => {
        const top = pl.stats.top_speed_kmh ? `${pl.stats.top_speed_kmh.toFixed(1)} km/h` : "no sprint over 30 km/h yet";
        span.textContent = `${top} · ${pl.stats.goals} goal${pl.stats.goals === 1 ? "" : "s"}`;
      })
      .catch(() => { span.textContent = "—"; });
  }
}
