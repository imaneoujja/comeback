/* The fan's full-time receipt, in words (shared by the TV and the paired phone).
 * Alerts are judged with the README's definitions, which the server sends with the numbers. */

const plural = (n, one, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;

/** ``seconds``: time this screen spent catching the fan up (replays + voice-overs), or 0 if unknown. */
export function receiptLines(r, seconds = 0) {
  const secs = seconds >= 1 ? ` in ${Math.round(seconds)} seconds` : "";
  let big;
  if (!r.goals) big = r.absences || r.late_join ? `No goals, and you caught up on what you missed${secs}.` : "No goals, and you saw every minute.";
  else if (r.goals_caught_up) big = `You were live for ${r.goals_live} of ${r.goals} goals, and caught up on the rest${secs}.`;
  else if (r.absences) {
    big = `You were live for ${r.goals === 1 ? "the only goal" : `all ${r.goals} goals`}, and caught up on ${plural(r.minutes_away, "minute")} away${secs}.`;
  } else big = `You were live for ${r.goals === 1 ? "the only goal" : `all ${r.goals} goals`}.`;
  const small = [`Watched ${r.minutes_live} of ${r.minutes_followed} minutes live`,
    r.alerts ? `${plural(r.alerts, "call-back")}, ${r.alerts_came_true} followed by a chance (xG ≥ ${r.chance_min_xg}) within ${r.chance_horizon_s} s`
      : "no call-back needed"];
  if (r.goals) small.push(`${r.goals_announced} of ${plural(r.goals, "goal")} announced in the ${r.anticipation_min} minutes before`);
  return { big, small: small.join(" · ") };
}
