"""The synthetic league around the live matches: standings, form, head-to-head, player season stats,
injuries, records, and the context facts a commentator would use ("talking points").

The data is built by ``scripts/build_league.py`` (matches simulated and read by the same engine) and
committed in ``data/league/league.json``. Everything here is a deterministic query: no model call.
"""

import functools
import json
from pathlib import Path
from typing import Any

LEAGUE_PATH = Path(__file__).resolve().parents[1] / "data" / "league" / "league.json"
RESEARCH_TYPES = {"goal", "big_chance", "red_card", "penalty", "momentum_swing", "shape_change", "half_time",
                  "full_time"}


@functools.cache
def load_league(path: Path = LEAGUE_PATH) -> "League":
    return League(json.loads(path.read_text(encoding="utf-8")))


class League:
    """Read-only queries over one synthetic season (matchdays played so far) and the last one."""

    def __init__(self, data: dict[str, Any]) -> None:
        self.data = data
        self.clubs: dict[str, str] = data["clubs"]
        self.players: dict[str, dict[str, Any]] = data["players"]
        self.results: list[dict[str, Any]] = data["results"]

    # ------------------------------------------------------------ standings & form

    def standings(self, extra: list[dict[str, Any]] = ()) -> list[dict[str, Any]]:
        """The table after the played matchdays (plus ``extra`` results, e.g. a live score)."""
        rows = {c: {"club": c, "name": n, "p": 0, "w": 0, "d": 0, "l": 0, "gf": 0, "ga": 0, "pts": 0, "form": []}
                for c, n in self.clubs.items()}
        for r in [*self.results, *extra]:
            (h, a), (gh, ga) = (r["home"], r["away"]), r["score"]
            for club, f, against in ((h, gh, ga), (a, ga, gh)):
                row = rows[club]
                row["p"] += 1
                row["gf"] += f
                row["ga"] += against
                outcome = "W" if f > against else "D" if f == against else "L"
                row[{"W": "w", "D": "d", "L": "l"}[outcome]] += 1
                row["pts"] += {"W": 3, "D": 1, "L": 0}[outcome]
                row["form"].append(outcome)
        table = sorted(rows.values(), key=lambda r: (-r["pts"], -(r["gf"] - r["ga"]), -r["gf"], r["name"]))
        for i, row in enumerate(table, start=1):
            row["pos"], row["gd"], row["form"] = i, row["gf"] - row["ga"], row["form"][-5:]
        return table

    def position(self, club: str, extra: list[dict[str, Any]] = ()) -> int:
        return next(r["pos"] for r in self.standings(extra) if r["club"] == club)

    def form(self, club: str) -> list[str]:
        return next(r["form"] for r in self.standings() if r["club"] == club)

    # ------------------------------------------------------------ players

    def player_season(self, pid: str) -> dict[str, Any]:
        """Season totals of a player before today's match."""
        apps = [(r["matchday"], r["players"][pid]) for r in self.results if pid in r["players"]]
        tot = {"apps": len(apps), "minutes": 0, "goals": 0, "assists": 0, "xg": 0.0, "shots": 0, "passes": 0,
               "passes_completed": 0, "key_passes": 0, "top_speed_kmh": 0.0, "fastest_shot_kmh": 0.0}
        for _, line in apps:
            for k in ("minutes", "goals", "assists", "xg", "shots", "passes", "passes_completed", "key_passes"):
                tot[k] += line[k]
            tot["top_speed_kmh"] = max(tot["top_speed_kmh"], line["top_speed_kmh"])
            tot["fastest_shot_kmh"] = max(tot["fastest_shot_kmh"], line["fastest_shot_kmh"])
        tot["xg"] = round(tot["xg"], 2)
        tot["pass_accuracy"] = round(tot["passes_completed"] / tot["passes"], 3) if tot["passes"] else None
        tot["goals_last_4"] = sum(line["goals"] for _, line in apps[-4:])
        tot["last_apps"] = min(4, len(apps))
        return {**self.players[pid], **tot}

    def leaders(self, key: str, n: int = 5, min_minutes: int = 0) -> list[dict[str, Any]]:
        rows = [self.player_season(pid) for pid in self.players]
        rows = [r for r in rows if r["minutes"] >= min_minutes and (r[key] or 0) > 0]
        return sorted(rows, key=lambda r: -(r[key] or 0))[:n]

    # ------------------------------------------------------------ head-to-head, injuries, records

    def head_to_head(self, a: str, b: str) -> list[dict[str, Any]]:
        """Meetings between two clubs: last season, then this season."""
        pair = {a, b}
        last = [{**r, "season": self.data["last_season"]} for r in self.data["last_season_results"]
                if {r["home"], r["away"]} == pair]
        this = [{"matchday": r["matchday"], "home": r["home"], "away": r["away"], "score": r["score"],
                 "season": self.data["season"]} for r in self.results if {r["home"], r["away"]} == pair]
        return last + this

    def unavailable(self, club: str | None = None) -> list[dict[str, Any]]:
        name = lambda u: self.players[u["player"]]["name"]  # noqa: E731
        out = [{**i, "kind": "injury", "name": name(i)} for i in self.data["injuries"]]
        out += [{**s, "kind": "suspension", "name": name(s)} for s in self.data["suspensions"]]
        return [u for u in out if club is None or u["club"] == club]

    def records(self) -> dict[str, Any]:
        """Season records so far: biggest win, fastest shot, top speed."""
        biggest = max(self.results, key=lambda r: (abs(r["score"][0] - r["score"][1]), sum(r["score"])))
        fastest = max(self.leaders("fastest_shot_kmh", 1), key=lambda r: r["fastest_shot_kmh"])
        quickest = max(self.leaders("top_speed_kmh", 1), key=lambda r: r["top_speed_kmh"])
        return {"biggest_win": biggest, "fastest_shot": fastest, "top_speed": quickest}

    # ------------------------------------------------------------ talking points

    def talking_facts(self, card: dict[str, Any], home: str, away: str, matchday: int = 10) -> list[dict[str, Any]]:
        """Up to two context facts for a key moment, each with its source in the league data."""
        facts = card.get("facts", {})
        mtype, team = card["type"], card.get("team")
        score = facts.get("score_after") or facts.get("score") or "0-0"
        out: list[dict[str, Any]] = []
        if mtype == "goal" and facts.get("scorer") in self.players:
            s = self.player_season(facts["scorer"])
            today = facts.get("scorer_goals_in_match", 1)
            out.append({"kind": "scorer_season", "name": s["name"], "nth": s["goals"] + today,
                        "recent": s["goals_last_4"] + today, "last_apps": s["last_apps"] + 1,
                        "source": f"season stats · {s['name']}: {plural(s['goals'], 'goal')} in "
                                  f"{plural(s['apps'], 'match', 'matches')} before today"})
        season = self.player_season(facts["player"]) if facts.get("player") in self.players else None
        if mtype in ("big_chance", "penalty") and season and (season["goals"] or season["xg"] >= 1):
            s = season                                # "0 goals, 0.0 xG" is not a talking point
            out.append({"kind": "player_xg", "name": s["name"], "goals": s["goals"], "xg": s["xg"], "apps": s["apps"],
                        "source": f"season stats · {s['name']}: {plural(s['goals'], 'goal')}, {s['xg']} xG, "
                                  f"{plural(s['apps'], 'match', 'matches')}"})
        if mtype == "red_card" and facts.get("player") in self.players:
            player = self.players[facts["player"]]
            nxt = self.next_fixture(player["club"], matchday)
            out.append({"kind": "suspension", "name": player["name"], "matchday": matchday + 1, "opponent": nxt,
                        "source": f"fixtures · matchday {matchday + 1}: {self.clubs[player['club']]} v {nxt}"})
        if mtype == "shape_change" and team:
            missing = self.unavailable(team)
            if missing:
                m = missing[0]
                out.append({"kind": "absence", "team": self.clubs[team], "name": m["name"], "reason": m["reason"],
                            "source": f"injuries · {m['name']} ({m['reason']}), "
                                      f"out since matchday {m.get('since_matchday', '?')}"})
        if mtype in ("momentum_swing", "shape_change", "big_chance") and team and len(out) < 2:
            form = self.form(team)
            out.append({"kind": "form", "team": self.clubs[team], "form": "".join(form), "wins": form.count("W"),
                        "pos": self.position(team),
                        "source": f"standings · {self.clubs[team]}: {''.join(form)} in the last 5"})
        if len(out) < 2 and mtype in ("goal", "red_card", "momentum_swing", "half_time", "full_time"):
            gh, ga = (int(x) for x in score.split("-"))
            focus = team or home
            live = [{"home": home, "away": away, "score": [gh, ga]}]
            before, after = self.position(focus), self.position(focus, live)
            out.append({"kind": "table_if", "final": mtype == "full_time", "team": self.clubs[focus], "score": score,
                        "home": self.clubs[home],
                        "away": self.clubs[away], "pos_before": before, "pos_after": after,
                        "source": f"live table · {self.clubs[focus]} {ordinal(before, 'en')} before kick-off"})
        if len(out) < 2 and mtype in ("half_time", "full_time", "goal"):
            meetings = self.head_to_head(home, away)
            if meetings:
                m = meetings[-1]
                out.append({"kind": "h2h", "home": self.clubs[m["home"]], "away": self.clubs[m["away"]],
                            "score": f"{m['score'][0]}-{m['score'][1]}", "season": m["season"],
                            "matchday": m["matchday"],
                            "source": f"head-to-head · {len(meetings)} meetings since last season"})
        return out[:2]

    def next_fixture(self, club: str, matchday: int) -> str:
        """The club's opponent after ``matchday`` (the season wraps for this demo's 10-matchday calendar)."""
        rounds = self.data["fixtures"]
        r = rounds[matchday % len(rounds)]
        pair = next(p for p in r if club in p)
        return self.clubs[pair[1] if pair[0] == club else pair[0]]


def ordinal(n: int, lang: str) -> str:
    """7 → "7th" / "7e" / "7.º" (1 → "1st" / "1er" / "1.º")."""
    if lang == "fr":
        return "1er" if n == 1 else f"{n}e"
    if lang == "es":
        return f"{n}.º"
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def plural(n: int, one: str, many: str | None = None) -> str:
    return f"{n} {one if n == 1 else many or one + 's'}"
