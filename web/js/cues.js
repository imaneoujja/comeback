/* CUES monitor: the overlay cues as a broadcast graphics renderer would receive them —
 * timed, renderer-agnostic JSON (the same objects GET /api/overlays/{match} returns). */

import { $, esc, on } from "./state.js";

const MAX = 24;
const lines = [];

export function initCues() {
  on("cue", (c) => {
    lines.unshift(line(c));
    lines.length = Math.min(lines.length, MAX);
    $("#cues").innerHTML = lines.join("");
    const tally = $("#cues-tally");
    tally.className = "tally live";
    clearTimeout(initCues.t);
    initCues.t = setTimeout(() => { tally.className = "tally amber"; }, 600);
  });
  on("state", () => { lines.length = 0; $("#cues").innerHTML = `<div class="empty">Cues appear as the match is rendered…</div>`; });
}

function line(c) {
  const data = Object.fromEntries(Object.entries(c.data).filter(([k]) => !["team", "moment_id"].includes(k)).slice(0, 4));
  const json = JSON.stringify({ t_in: c.t_in, t_out: c.t_out, layer: c.layer, template: c.template,
    priority: c.priority, audience: c.audience, data });
  return `<div class="cue"><b class="cue-t ${esc(c.template)}">${esc(c.template)}</b><code>${esc(json)}</code></div>`;
}
