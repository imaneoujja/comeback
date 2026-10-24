/* Where the 22 players stand, from the ball and who has it (pure functions, no DOM: tested in Node).
 *
 * Each team keeps a readable shape: a back line, a midfield line and a front line that slide
 * together with the ball. Computed in the attacking frame of the team in possession (it attacks
 * towards x = 105):
 * - the attacking team pushes its lines up behind and around the ball;
 * - the defending team drops its lines between the ball and its own goal: when the ball is in the
 *   last third, the back four (and the keeper) stand closer to the goal than the ball, in or at
 *   the edge of the box;
 * - the ball is always at the feet of its holder (< 1.5 m), or travelling between a passer and a
 *   receiver who runs to meet it. */

export const L = 105, W = 68;
const LINES = {
  GK: "gk", RB: "def", LB: "def", CB: "def", RCB: "def", LCB: "def", RWB: "def", LWB: "def",
  CDM: "mid", DM: "mid", CM: "mid", CAM: "mid", RM: "mid", LM: "mid", AM: "mid",
  LW: "fwd", RW: "fwd", ST: "fwd", CF: "fwd", SS: "fwd",
};
const BASE_X = { gk: 5, def: 27, mid: 50, fwd: 76 };   // where each line's formation spots sit
const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));

/** A player's line from their position, else from their formation spot. */
export function lineOf(position, spotX) {
  if (LINES[position]) return LINES[position];
  return spotX < 15 ? "gk" : spotX < 38 ? "def" : spotX < 64 ? "mid" : "fwd";
}

/** Line heights (attacking frame) for the team with the ball and the team without it. */
export function lineHeights(bx) {
  const attack = { gk: clamp(5 + Math.max(0, bx - 50) * 0.25, 4, 20), def: clamp(bx - 30, 12, 55),
    mid: clamp(bx - 12, 28, 78), fwd: clamp(bx + 6, 45, 96) };
  const def = clamp(bx + 6, 58, 100);
  const mid = clamp(def - 13, 45, 92);
  const defend = { gk: 103, def, mid, fwd: clamp(mid - 18, 35, 80) };
  return { attack, defend };
}

/**
 * Targets in absolute pitch metres for every player on the pitch.
 * ``players``: [{ id, team, line, sx, sy }] with the formation spot (sx, sy) in the player's own
 * attacking frame; ``ball``: {x, y} absolute; ``possession``: team code with the ball;
 * ``homeTeam``: home code (it attacks x = 105); ``holder``: player at the ball, or null;
 * ``pass``: { passer, receiver, x, y, end_x, end_y } while a pass travels, or null.
 */
export function formationTargets({ players, ball, possession, homeTeam, holder = null, pass = null }) {
  const flip = possession !== homeTeam;                       // the frame of the team in possession
  const toFrame = (x, y) => (flip ? [L - x, W - y] : [x, y]);
  const [bx, by] = toFrame(ball.x, ball.y);
  const { attack, defend } = lineHeights(bx);
  const out = {};
  for (const p of players) {
    const line = p.line;
    let x, y;
    if (p.team === possession) {
      x = attack[line] + (line === "gk" ? 0 : (p.sx - BASE_X[line]) * 0.35);
      y = line === "gk" ? 34 + (by - 34) * 0.1 : clamp(p.sy + (by - 34) * 0.25, 3, 65);
    } else {
      const ownY = W - p.sy;                                  // their spot, seen from the attacking frame
      x = defend[line] - (line === "gk" ? 0 : (p.sx - BASE_X[line]) * 0.35);
      const narrow = bx > 82 ? 0.38 : bx > 75 ? 0.45 : bx > 65 ? 0.55 : 0.7;   // a defence under siege closes the middle
      y = line === "gk" ? 34 + (by - 34) * 0.15 : clamp(34 + (ownY - 34) * narrow + (by - 34) * 0.35, 3, 65);
    }
    out[p.id] = [clamp(x, 1, L - 1), y];
  }
  // ball in the last third: the back line tucks in until every defender is goal-side of the ball
  if (bx > 65) {
    const gx = L, gy = W / 2;
    const dBall = Math.hypot(gx - bx, gy - by);
    for (const p of players) {
      if (p.team === possession || p.line !== "def") continue;
      const [x, y] = out[p.id];
      const d = Math.hypot(gx - x, gy - y);
      if (d >= 0.9 * dBall) { const k = (0.85 * dBall) / d; out[p.id] = [gx + (x - gx) * k, gy + (y - gy) * k]; }
    }
  }
  for (const id of Object.keys(out)) out[id] = toFrame(...out[id]);
  if (pass) {                                                 // the receiver runs to meet the ball
    if (out[pass.receiver]) out[pass.receiver] = [pass.end_x, pass.end_y];
    if (out[pass.passer]) out[pass.passer] = [pass.x, pass.y];
  }
  if (holder && out[holder]) {                                // the ball is at the holder's feet
    const dir = flip ? 1 : -1;                                // just behind the ball, towards their own goal
    out[holder] = [ball.x + dir * 0.6, ball.y + 0.3];
  }
  return out;
}

/** The player of ``team`` nearest the ball (who takes it when nobody holds it). */
export function nearestTo(ball, positions, ids) {
  let best = null, bestD = Infinity;
  for (const id of ids) {
    const p = positions[id];
    if (!p) continue;
    const d = Math.hypot(p.x - ball.x, p.y - ball.y);
    if (d < bestD) { bestD = d; best = id; }
  }
  return best;
}
