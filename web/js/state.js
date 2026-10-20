/* Shared client state and the "match physics" both renderers read:
 * ball position (with height for lofted passes) and smoothed player positions,
 * all in pitch coordinates (x 0..105 towards the away goal, y 0..68). */

export const MATCH_ID = "demo-comeback";
export const SPEEDS = [1, 5, 10, 20, 40];
export const L = 105, W = 68;

export const $ = (sel) => document.querySelector(sel);
export const esc = (s) => String(s ?? "")
  .replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]))
  .replace(/(\d)-(\d)/g, "$1‑$2");   // keep scores like 1-2 on one line

export const app = {
  session: newSessionId(), profileId: "omar", speed: 10, paused: false,
  match: null, teams: {}, home: null, away: null, roster: {}, profiles: [],
  snapshot: null, snapshotAt: performance.now(), timeline: [], cards: new Map(), notes: [], awayBands: [], present: true,
  lineup: {}, possession: null, holder: null,
  ball: { x: L / 2, y: W / 2, z: 0 }, ballAnim: null, pos: {},
  events: [], durationT: 5700, listeners: {}, topSpeed: {}, lastFavTag: 0, eventsById: new Map(), crowd: null,
};

window.__comeback = app;   // read-only handle for automated UI checks and debugging

export function newSessionId() { return Math.random().toString(36).slice(2, 12); }

export async function post(path) {
  const res = await fetch(`/api/session/${app.session}/${path}`, { method: "POST" });
  return res.ok ? res.json() : null;
}

/* tiny pub/sub so modules can react to stream messages without importing each other */
export function on(type, fn) { (app.listeners[type] ||= []).push(fn); }
export function emit(type, data) { for (const fn of app.listeners[type] || []) fn(data); }

export const teamColour = (team) => app.teams[team]?.colour || "#ecebe6";
export const teamName = (team) => app.teams[team]?.name || team;
export const isHome = (team) => team === app.home;
export const level = () => app.profiles.find((p) => p.id === app.profileId)?.level || "casual";
export const profile = () => app.profiles.find((p) => p.id === app.profileId);

export function clockText(s) {
  if (!s) return "00:00";
  if (s.period === 1 && s.minute >= 45) return `45+${s.minute - 44}'`;
  if (s.period === 2 && s.minute >= 90) return `90+${s.minute - 89}'`;
  return `${String(s.minute).padStart(2, "0")}:${String(s.second).padStart(2, "0")}`;
}

/* ------------------------------------------------------------------ events → ball & holder */

function animateBall(x, y, ex, ey, realSeconds, height = 0) {
  const wall = Math.min(0.95, Math.max(0.12, realSeconds / app.speed));
  app.ballAnim = { x0: x, y0: y, x1: ex, y1: ey, h: height, start: performance.now(), dur: wall * 1000 };
}

function snapBall(x, y) { animateBall(app.ball.x, app.ball.y, x, y, 0.15 * app.speed); }

export function applyEvent(e) {
  const team = e.team;
  switch (e.type) {
    case "pass": {
      app.possession = team;
      app.holder = null;
      const secs = e.distance_m / Math.max(5, e.ball_speed_kmh / 3.6);
      const loft = e.distance_m > 22 ? Math.min(9, e.distance_m * 0.13) : (e.cross ? 4 : 0);
      animateBall(e.x, e.y, e.end_x, e.end_y, secs, loft);
      if (e.success) setTimeout(() => { app.holder = e.receiver; }, Math.min(950, (secs / app.speed) * 1000));
      break;
    }
    case "carry":
    case "sprint": {
      app.possession = team;
      app.holder = e.player;
      const dist = Math.hypot(e.end_x - e.x, e.end_y - e.y);
      animateBall(e.x, e.y, e.end_x, e.end_y, dist / Math.max(2, e.speed_kmh / 3.6));
      break;
    }
    case "shot": {
      app.possession = team;
      app.holder = null;
      const gx = isHome(team) ? L + 0.6 : -0.6;
      const wide = e.outcome === "off_target";
      const gy = W / 2 + (wide ? (Math.random() < 0.5 ? -5.5 : 5.5) : (Math.random() - 0.5) * 5);
      animateBall(e.x, e.y, gx, gy, 0.9, wide ? 3 : 1.4);
      break;
    }
    case "possession_change":
      app.possession = e.to_team; app.holder = e.player; snapBall(e.x, e.y); break;
    case "throw_in": case "goal_kick": case "corner":
      app.possession = team; app.holder = e.player; snapBall(e.x, e.y); break;
    case "period_start":
      app.possession = team; app.holder = null; snapBall(L / 2, W / 2); break;
    case "goal":
      app.holder = null; break;
    case "substitution": {
      const lineup = app.lineup[team];
      const spot = e.spot || lineup[e.player_out];
      delete lineup[e.player_out];
      if (spot) lineup[e.player_in] = spot;
      app.pos[e.player_in] = app.pos[e.player_out];
      delete app.pos[e.player_out];
      break;
    }
    case "card":
      if (e.color === "red") { delete app.lineup[team][e.player]; delete app.pos[e.player]; }
      break;
    default:
      break;
  }
}

/* ------------------------------------------------------------------ positions */

function playerTargets() {
  const poss = app.possession || app.home;
  const flip = !isHome(poss);
  const toFrame = (x, y) => (flip ? [L - x, W - y] : [x, y]);   // absolute ⇄ possessing team's frame
  const [bx, by] = toFrame(app.ball.x, app.ball.y);
  const out = {};
  const now = performance.now();
  for (const team of [app.home, app.away]) {
    for (const [pid, [sx, sy]] of Object.entries(app.lineup[team] || {})) {
      const gk = app.roster[pid]?.position === "GK";
      let x, y;
      if (team === poss) {
        if (gk) { x = sx + Math.max(0, bx - 50) * 0.1; y = sy; }
        else {
          x = Math.min(Math.max(sx + (bx - 45) * 0.45, 2), Math.min(95, Math.max(84, bx + 6)));
          y = sy + (by - sy) * 0.2;
        }
      } else {
        const mx = L - sx, my = W - sy;
        const pull = gk ? 0.04 : 0.3;
        x = mx + (bx - mx) * pull; y = my + (by - my) * pull;
      }
      const seed = pid.charCodeAt(0) * 3 + pid.length * 7 + sx;
      const wobble = Math.sin(now / 1100 + seed) * 0.7;
      out[pid] = toFrame(x + wobble, y + Math.cos(now / 1300 + seed) * 0.5);
    }
  }
  if (app.holder && out[app.holder]) out[app.holder] = [app.ball.x - 0.7, app.ball.y + 0.5];
  return out;
}

/** Advance ball and players by ``dt`` seconds of wall time. */
export function step(dt) {
  const now = performance.now();
  if (app.ballAnim) {
    const a = app.ballAnim;
    const k = Math.min(1, (now - a.start) / a.dur);
    const ease = 1 - Math.pow(1 - k, 2);
    app.ball = { x: a.x0 + (a.x1 - a.x0) * ease, y: a.y0 + (a.y1 - a.y0) * ease, z: 4 * a.h * k * (1 - k) };
    if (k >= 1) app.ballAnim = null;
  }
  const targets = playerTargets();
  const follow = 1 - Math.exp(-dt * (2.2 + app.speed * 0.22));
  for (const [pid, [tx, ty]] of Object.entries(targets)) {
    const p = app.pos[pid] || (app.pos[pid] = { x: tx, y: ty, vx: 0, vy: 0 });
    const nx = p.x + (tx - p.x) * follow, ny = p.y + (ty - p.y) * follow;
    p.vx = (nx - p.x) / Math.max(dt, 1e-3); p.vy = (ny - p.y) / Math.max(dt, 1e-3);
    p.x = nx; p.y = ny;
  }
  for (const pid of Object.keys(app.pos)) if (!targets[pid]) delete app.pos[pid];
  return targets;
}

/* ------------------------------------------------------------------ canvas helper */

export function sizeCanvas(c) {
  const r = c.getBoundingClientRect();
  const dpr = Math.min(2, window.devicePixelRatio || 1);
  const w = Math.max(1, Math.round(r.width * dpr)), h = Math.max(1, Math.round(r.height * dpr));
  if (c.width !== w || c.height !== h) { c.width = w; c.height = h; }
  return dpr;
}
