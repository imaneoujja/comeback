"""Build the synthetic league around the two live matches: this season so far and last season.

Everything is simulated by the same match simulator and read by the same engine; nothing is real.

* Six fictional clubs. Their squads are the squads of the live matches (Emberfield and Saltmarsh
  Comets from the demo match, Ashvale and Larkhaven from the unscripted one), plus Thornwick and
  Calderbay, and one injured squad member for five clubs (shirt 16): he started the matchdays
  before his injury, then the regular starter took his place.
* This season: a double round robin of 10 matchdays; matchdays 1-9 are played. Matchday 10 holds
  the two live matches (Emberfield v Saltmarsh Comets, Ashvale v Larkhaven) and Thornwick v
  Calderbay. Last season: 10 matchdays, results only.
* Coherence with the live matches (tested): nobody on a live team sheet is injured or suspended;
  a matchday-9 seed is skipped if a red card or a fifth yellow would have suspended one of them.

Usage:
    python scripts/build_league.py        # writes data/league/league.json
"""

import json
import random
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from comeback.engine.match import MatchEngine  # noqa: E402
from comeback.synth.simulator import MatchSimulator, match_metadata  # noqa: E402
from comeback.synth.teams import CLUBS, FIRST_NAMES, LAST_NAMES, Team, _build_player, build_fixture  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "league" / "league.json"
SEASON, LAST_SEASON = "2026-27", "2025-26"
LIVE = {("EMB", "SMC"): "demo-comeback", ("AVW", "LKA"): "random-3112"}
# (club, shirt-16 position, the starter he replaced, injured on matchday, reason, expected back on matchday)
INJURIES = [
    ("EMB", "CB", "EMB-5", 6, "hamstring strain", 12),
    ("SMC", "RW", "SMC-7", 8, "ankle sprain", 11),
    ("LKA", "CM", "LKA-8", 4, "knee ligament", 16),
    ("THU", "ST", "THU-9", 7, "thigh strain", 11),
    ("CBC", "LB", "CBC-3", 9, "concussion protocol", 11),
]
# Surnames kept for the injured players: none of them is worn by anyone on a live team sheet, so a
# talking point about an absent player can never be confused with a player on the pitch.
INJURED_SURNAMES = ("Cindervale", "Mossgrove", "Tallowmere", "Wexcombe", "Ferncastle")


def fixtures() -> list[list[tuple[str, str]]]:
    """A double round robin (circle method). Matchday 10 is the live round at the live venues; its
    first leg (same pairs, venues swapped) is matchday 5."""
    clubs = ["EMB", "AVW", "THU", "CBC", "LKA", "SMC"]     # round 1 pairs EMB-SMC, AVW-LKA, THU-CBC
    rot, circle = clubs[1:], []
    for r in range(5):
        order = [clubs[0], *rot]
        circle.append([(order[i], order[5 - i]) if (r + i) % 2 == 0 else (order[5 - i], order[i]) for i in range(3)])
        rot = rot[-1:] + rot[:-1]
    pairs = {frozenset(p) for p in LIVE}
    live_round = next(r for r in circle if pairs <= {frozenset(p) for p in r})
    others = [r for r in circle if r is not live_round]
    live_home = [p if p in LIVE else p[::-1] if p[::-1] in LIVE else tuple(sorted(p, key=lambda c: c != "THU"))
                 for p in live_round]
    first_leg = [*others, [(b, a) for a, b in live_home]]
    return first_leg + [[(b, a) for a, b in r] for r in first_leg]


def last_season_fixtures(schedule: list[list[tuple[str, str]]]) -> list[list[tuple[str, str]]]:
    """Last season's calendar: the same pairs in another order, so that no matchday repeats this season's."""
    rng = random.Random(f"calendar:{LAST_SEASON}")
    order = list(range(len(schedule)))
    while any(i == j for i, j in enumerate(order)):
        rng.shuffle(order)
    return [schedule[i] for i in order]


def squads() -> tuple[dict[str, Team], dict[str, tuple[Any, str]]]:
    """The six squads (the live squads exactly as in the live matches) and the injured shirt-16 players."""
    emb, smc = build_fixture("EMB", "SMC", 2026)
    avw, lka = build_fixture("AVW", "LKA", 3112)
    thu, cbc = build_fixture("THU", "CBC", 777)
    teams = {t.club.id: t for t in (emb, smc, avw, lka, thu, cbc)}
    extras = {}
    for (club, position, replaced, *_), surname in zip(INJURIES, INJURED_SURNAMES, strict=True):
        team = teams[club]
        rng = random.Random(f"injured:{club}")
        rng.sample(LAST_NAMES, len(LAST_NAMES))           # keeps the random stream (and his ratings) unchanged
        extras[club] = (_build_player(team.club, 16, position, f"{rng.choice(FIRST_NAMES)} {surname}", rng), replaced)
    return teams, extras


def lineup(team: Team, club: str, matchday: int, extras: dict[str, Any]) -> Team:
    """The team that played on ``matchday``: before his injury, the shirt-16 player started."""
    injury = next((i for i in INJURIES if i[0] == club), None)
    if not injury or matchday >= injury[3]:
        return team
    player, replaced = extras[club]
    starter = next(p for p in team.starting_xi if p.id == replaced)
    stand_in = replace(player, number=starter.number)          # he plays in the spot of the shirt he took over
    return replace(team, starting_xi=tuple(stand_in if p.id == replaced else p for p in team.starting_xi))


def play(home: Team, away: Team, seed: int, match_id: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    meta = match_metadata(home, away, seed=seed, match_id=match_id, scenario=None)
    return meta, MatchSimulator(home, away, seed=seed, match_id=match_id).run()


def summarise(meta: dict[str, Any], events: list[dict[str, Any]], matchday: int) -> dict[str, Any]:
    """One match of the season as the engine reads it: score, xG, goals, cards, a line per player."""
    engine = MatchEngine(meta)
    for e in events:
        engine.process(e)
    st = engine.state
    end = events[-1]["minute"]
    on = [*meta["home"]["starting_xi"], *meta["away"]["starting_xi"]]
    minutes: dict[str, list[float]] = {p: [0, end] for p in on}
    cards = []
    for e in events:
        if e["type"] == "substitution":
            minutes[e["player_out"]][1] = e["minute"]
            minutes[e["player_in"]] = [e["minute"], end]
        elif e["type"] == "card":
            cards.append({"player": e["player"], "team": e["team"], "color": e["color"], "minute": e["minute"]})
            if e["color"] == "red":
                minutes[e["player"]][1] = e["minute"]
    fastest: dict[str, float] = {}
    for e in events:
        if e["type"] == "shot":
            fastest[e["player"]] = max(fastest.get(e["player"], 0.0), e["shot_speed_kmh"])
    players = {}
    for pid, (start, stop) in minutes.items():
        s = st.players[pid]
        players[pid] = {"minutes": int(stop - start), "goals": s.goals, "assists": s.assists, "xg": round(s.xg, 2),
                        "shots": s.shots, "passes": s.passes, "passes_completed": s.passes_completed,
                        "key_passes": s.key_passes, "top_speed_kmh": s.top_speed_kmh,
                        "fastest_shot_kmh": fastest.get(pid, 0.0)}
    goals = [{"minute": e["minute"], "team": e["team"], "scorer": e["scorer"], "assist": e.get("assist")}
             for e in events if e["type"] == "goal"]
    return {"matchday": matchday, "home": st.home, "away": st.away, "score": [st.score[st.home], st.score[st.away]],
            "xg": [round(st.teams[st.home].xg, 2), round(st.teams[st.away].xg, 2)], "goals": goals, "cards": cards,
            "players": players}


def live_sheet() -> set[str]:
    """Every player on the team sheet of a live match."""
    ids = set()
    for match_id in LIVE.values():
        meta = json.loads((ROOT / "data" / "matches" / f"{match_id}.jsonl").read_text().split("\n", 1)[0])
        ids |= {p["id"] for side in ("home", "away") for p in meta[side]["players"]}
    return ids


def suspended(results: list[dict[str, Any]]) -> dict[str, str]:
    """Suspensions for matchday 10: a red card on matchday 9, or a fifth yellow card on matchday 9."""
    out, yellows = {}, {}
    for r in results:
        for c in r["cards"]:
            if c["color"] == "yellow":
                yellows[c["player"]] = yellows.get(c["player"], 0) + 1
                if yellows[c["player"]] == 5 and r["matchday"] == 9:
                    out[c["player"]] = "five yellow cards"
            elif r["matchday"] == 9:
                out[c["player"]] = "red card on matchday 9"
    return out


def build() -> dict[str, Any]:
    teams, extras = squads()
    sheet = live_sheet()
    schedule = fixtures()
    results: list[dict[str, Any]] = []
    for md, round_ in enumerate(schedule[:9], start=1):
        for k, (h, a) in enumerate(round_):
            home, away = lineup(teams[h], h, md, extras), lineup(teams[a], a, md, extras)
            for offset in range(50):                      # skip seeds that would suspend a live player
                meta, events = play(home, away, 20_000 + md * 100 + k * 10 + offset, f"s{md:02d}-{h}-{a}")
                summary = summarise(meta, events, md) | {"seed": meta["seed"]}
                if md < 9 or not (set(suspended([*results, summary])) & sheet):
                    break
            results.append(summary)
    last = []
    for md, round_ in enumerate(last_season_fixtures(schedule), start=1):
        for k, (h, a) in enumerate(round_):
            seed = 90_000 + md * 100 + k
            _, events = play(teams[h], teams[a], seed, f"p{md:02d}-{h}-{a}")
            score = [sum(1 for e in events if e["type"] == "goal" and e["team"] == c) for c in (h, a)]
            last.append({"matchday": md, "home": h, "away": a, "score": score, "seed": seed})
    players = {p.id: {"id": p.id, "club": c, "name": p.name, "number": p.number, "position": p.position}
               for c, team in teams.items() for p in team.players}
    for club, (p, _) in extras.items():
        players[p.id] = {"id": p.id, "club": club, "name": p.name, "number": p.number, "position": p.position}
    injuries = [{"player": extras[c][0].id, "club": c, "reason": reason, "since_matchday": md,
                 "back_matchday": back, "replaced_by": replaced} for c, _, replaced, md, reason, back in INJURIES]
    suspensions = [{"player": pid, "club": players[pid]["club"], "reason": why}
                   for pid, why in suspended(results).items()]
    return {"season": SEASON, "last_season": LAST_SEASON, "clubs": {c: CLUBS[c].name for c in teams},
            "players": players, "fixtures": [[list(p) for p in r] for r in schedule], "played_matchdays": 9,
            "live": {mid: list(pair) for pair, mid in LIVE.items()}, "results": results,
            "last_season_results": last, "injuries": injuries, "suspensions": suspensions}


if __name__ == "__main__":
    league = build()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(league, ensure_ascii=False, separators=(",", ":")))
    print(f"{len(league['results'])} matches this season, {len(league['last_season_results'])} last season, "
          f"{len(league['injuries'])} injuries, {len(league['suspensions'])} suspensions → {OUT}")
