// Coherence of the player positions model (web/js/formation.js), run by tests/test_positions.py with Node.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { formationTargets, lineOf, L, W } from "../web/js/formation.js";

const meta = JSON.parse(readFileSync(new URL("../data/matches/demo-comeback.jsonl", import.meta.url), "utf8").split("\n")[0]);
const players = [];
for (const side of ["home", "away"]) {
  for (const p of meta[side].players) {
    if (p.spot) players.push({ id: p.id, team: meta[side].id, sx: p.spot[0], sy: p.spot[1], line: lineOf(p.position, p.spot[0]) });
  }
}
const home = meta.home.id, away = meta.away.id;
const goal = (defending) => (defending === home ? [0, W / 2] : [L, W / 2]);
let checked = 0;
for (const possession of [home, away]) {
  const defending = possession === home ? away : home;
  for (let fx = 5; fx <= 99; fx += 7) {          // up to the penalty spot area, not the goal line
    for (let y = 4; y <= 64; y += 10) {
      const x = possession === home ? fx : L - fx;              // fx: depth in the attacking frame
      const ball = { x, y };
      const holder = players.find((p) => p.team === possession && p.line === "mid").id;
      const t = formationTargets({ players, ball, possession, homeTeam: home, holder });
      // 1. the ball is at the holder's feet
      assert.ok(Math.hypot(t[holder][0] - x, t[holder][1] - y) < 1.5, "holder within 1.5 m of the ball");
      // 2. ball in the last third: at least 4 defending outfield players closer to their goal than the ball
      if (fx >= 70) {
        const [gx, gy] = goal(defending);
        const dBall = Math.hypot(x - gx, y - gy);
        const between = players.filter((p) => p.team === defending && p.line !== "gk")
          .filter((p) => Math.hypot(t[p.id][0] - gx, t[p.id][1] - gy) < dBall).length;
        assert.ok(between >= 4, `only ${between} defenders between the ball (${fx}, ${y}) and the goal`);
      }
      // 3. lines keep their order, for both teams (depth measured towards each team's attack)
      for (const team of [home, away]) {
        const depth = (pid) => (team === home ? t[pid][0] : L - t[pid][0]);
        const mean = (line) => {
          const ids = players.filter((p) => p.team === team && p.line === line && p.id !== holder).map((p) => depth(p.id));
          return ids.reduce((a, b) => a + b, 0) / ids.length;
        };
        assert.ok(mean("gk") < mean("def") && mean("def") < mean("mid") && mean("mid") < mean("fwd"),
          `lines out of order for ${team} with the ball at (${fx}, ${y})`);
      }
      // 4. everybody on the pitch
      for (const [px, py] of Object.values(t)) assert.ok(px >= 0 && px <= L && py >= 0 && py <= W);
      checked += 1;
    }
  }
}
// a pass in flight: the receiver runs to the end of the pass, the passer stays where they played it
const pass = { passer: players[5].id, receiver: players[8].id, x: 40, y: 30, end_x: 60, end_y: 20 };
const t = formationTargets({ players, ball: { x: 50, y: 25 }, possession: home, homeTeam: home, pass });
assert.deepEqual(t[pass.receiver], [60, 20]);
assert.deepEqual(t[pass.passer], [40, 30]);
console.log(`positions ok: ${checked} ball positions`);
