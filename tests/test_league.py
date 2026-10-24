"""The synthetic league around the live matches, and the Researcher's talking points."""

import json
from collections import Counter
from pathlib import Path

from fastapi.testclient import TestClient

from comeback.agents.researcher import (
    ResearchTask,
    ResearchWriter,
    check_claims,
    check_full_names,
    template_point,
)
from comeback.api.server import app
from comeback.engine.match import MatchEngine, load_match
from comeback.league import LEAGUE_PATH, load_league

ROOT = Path(__file__).resolve().parents[1]
client = TestClient(app)


def _sheet(match_id: str) -> dict:
    return json.loads((ROOT / "data" / "matches" / f"{match_id}.jsonl").read_text().split("\n", 1)[0])


def test_the_calendar_is_a_double_round_robin_with_the_live_round_last() -> None:
    lg = load_league()
    rounds = lg.data["fixtures"]
    assert len(rounds) == 10 and Counter(frozenset(p) for r in rounds for p in r) == \
        {frozenset(p): 2 for p in {frozenset(p) for r in rounds for p in r}}
    assert ["EMB", "SMC"] in rounds[9] and ["AVW", "LKA"] in rounds[9]          # matchday 10: the live venues
    assert ["SMC", "EMB"] in rounds[4] and ["LKA", "AVW"] in rounds[4]          # matchday 5: the first legs
    assert len(lg.results) == 27 and {r["matchday"] for r in lg.results} == set(range(1, 10))


def test_the_season_is_coherent_with_the_live_matches() -> None:
    lg = load_league()
    for match_id, (home, away) in lg.data["live"].items():
        sheet = _sheet(match_id)
        for side, club in (("home", home), ("away", away)):
            assert sheet[side]["id"] == club
            squad = {p["id"]: p["name"] for p in sheet[side]["players"]}
            assert all(lg.players[pid]["name"] == name for pid, name in squad.items())   # the same players
            unavailable = {u["player"] for u in lg.unavailable(club)}
            assert not unavailable & set(squad)                    # injured or suspended players are not on the sheet
    for injury in lg.data["injuries"]:
        played = [r["matchday"] for r in lg.results if injury["player"] in r["players"]]
        assert played and max(played) < injury["since_matchday"] <= injury["back_matchday"] - 1
        assert all(injury["replaced_by"] in r["players"] for r in lg.results
                   if r["matchday"] >= injury["since_matchday"] and injury["club"] in (r["home"], r["away"]))


def test_standings_add_up() -> None:
    lg = load_league()
    table = lg.standings()
    assert [r["pos"] for r in table] == list(range(1, 7)) and all(r["p"] == 9 for r in table)
    assert sum(r["pts"] for r in table) == sum(3 if r["score"][0] != r["score"][1] else 2 for r in lg.results)
    assert sum(r["gf"] for r in table) == sum(sum(r["score"]) for r in lg.results)
    goals = sum(lg.player_season(pid)["goals"] for pid in lg.players)
    assert goals == sum(len(r["goals"]) for r in lg.results)        # every goal has a scorer in the season stats


def test_talking_facts_for_the_demo_moments() -> None:
    lg = load_league()
    meta, events = load_match(ROOT / "data" / "matches" / "demo-comeback.jsonl")
    engine = MatchEngine(meta)
    goal = None
    for e in events:
        for m in engine.process(e).moments:
            if m.type == "goal" and m.minute == 71:
                goal = m.to_dict()
    facts = lg.talking_facts(goal, "EMB", "SMC")
    scorer = facts[0]
    before = lg.player_season("EMB-9")["goals"]
    assert scorer["kind"] == "scorer_season" and scorer["nth"] == before + 1 and "season stats" in scorer["source"]
    assert facts[1]["kind"] == "table_if" and facts[1]["score"] == "1-2"
    assert template_point(scorer, "en").startswith(f"{before + 1}th goal of the season for Ciro Oakenfold")
    assert template_point(scorer, "fr").startswith(f"{before + 1}e but de la saison")
    assert template_point(scorer, "es").startswith(f"{before + 1}.º gol de la temporada")


def test_the_verifier_checks_talking_points_against_the_records() -> None:
    lg = load_league()
    card = {"moment_id": "m1", "minute": 71, "type": "goal", "team": "EMB", "headline": "",
            "facts": {"scorer": "EMB-9", "scorer_goals_in_match": 1, "score_after": "1-2"}}
    facts = lg.talking_facts(card, "EMB", "SMC")
    meta = _sheet("demo-comeback")
    roster = {p["id"]: {**p, "team": meta[s]["id"]} for s in ("home", "away") for p in meta[s]["players"]}
    task = ResearchTask(card, facts, "en", {"EMB": "Emberfield", "SMC": "Saltmarsh Comets"}, roster,
                        set(lg.clubs.values()))
    writer = ResearchWriter()
    good = writer.fallback(task)
    assert writer.verify(task, good) == []
    bad = {"points": ["Ciro Oakenfold's 40th goal of the season.", good["points"][1]]}
    assert any("not in the facts" in issue for issue in writer.verify(task, bad))


def test_league_and_research_endpoints() -> None:
    out = client.get("/api/league/demo-comeback").json()
    assert out["matchday"] == 10 and out["standings"][0]["pos"] == 1 and len(out["unavailable"]) >= 5
    assert {"goals", "assists", "xg", "top_speed_kmh", "pass_accuracy"} <= set(out["leaders"])
    assert out["head_to_head"] and all({m["home"], m["away"]} == {"EMB", "SMC"} for m in out["head_to_head"])


def test_the_committed_league_is_reproducible() -> None:
    import importlib.util

    spec = importlib.util.spec_from_file_location("build_league", ROOT / "scripts" / "build_league.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.build() == json.loads(LEAGUE_PATH.read_text())


def test_the_verifier_catches_wrong_claims_from_real_drafts() -> None:
    """Every number and name was right in these drafts of the recording; the claim was not."""
    clubs, season = ("Emberfield", "Saltmarsh Comets"), "2026-27"
    form = {"kind": "form"}
    xg = {"kind": "player_xg", "name": "Ciro Oakenfold", "goals": 12, "xg": 14.07}
    h2h = {"kind": "h2h", "season": "2026-27"}
    wrong = [
        ("With this 2-0 lead at home, Emberfield is on course to keep their position.", form, (0, 2), False),
        ("Ciro Oakenfold ha marcado 12 goles en 9 partidos, superando su xG de 14.07.", xg, (1, 2), False),
        ("Last season's meeting ended in a 1-1 draw on matchday 5.", h2h, (0, 2), False),
        ("This is the first meeting this season, after a 1-1 on matchday 5.", h2h, (0, 2), False),
        ("Emberfield maintain their top spot with this 3-2 win over Saltmarsh Comets.", form, (3, 2), False),
        ("Emberfield est en tête avec deux victoires cette saison.", form, (2, 2), False),
        ("Emberfield cambia a una formación agresiva.", {"kind": "absence", "name": "Quin Cindervale"}, (0, 2), False),
    ]
    for text, fact, score, finished in wrong:
        assert check_claims(text, fact, score, clubs, season, finished), text
    right = [
        ("Si mantienen esta ventaja 0-2 en Emberfield, Saltmarsh Comets subirán al 2.º puesto.", form, (0, 2), False),
        ("Despite trailing 0-2 at home, Emberfield are seizing control.", form, (0, 2), False),
        ("Ciro Oakenfold: 12 goals, slightly below his 14.07 xG.", xg, (1, 2), False),
        ("Emberfield secure a 3-2 victory over Saltmarsh Comets.", form, (3, 2), True),
    ]
    for text, fact, score, finished in right:
        assert check_claims(text, fact, score, clubs, season, finished) == [], text



def test_injured_players_share_no_surname_with_a_live_player() -> None:
    lg = load_league()
    on_sheets = {p["name"].split()[-1] for match_id in lg.data["live"] for side in ("home", "away")
                 for p in _sheet(match_id)[side]["players"]}
    injured = [lg.players[i["player"]]["name"].split()[-1] for i in lg.data["injuries"]]
    assert len(set(injured)) == len(injured) and not set(injured) & on_sheets


def test_the_two_seasons_have_their_own_seeds_and_calendars() -> None:
    lg = load_league()
    this, last = lg.results, lg.data["last_season_results"]
    assert not {r["seed"] for r in this} & {r["seed"] for r in last}
    rounds = lambda results, md: {(r["home"], r["away"]) for r in results if r["matchday"] == md}  # noqa: E731
    assert all(rounds(this, md) != rounds(last, md) for md in range(1, 10))
    meetings = lg.head_to_head("EMB", "SMC")
    assert len({(m["season"], m["matchday"]) for m in meetings}) == len(meetings)


def test_no_season_xg_point_for_a_player_with_nothing_to_show() -> None:
    lg = load_league()
    quiet = next(pid for pid in lg.players if lg.player_season(pid)["apps"] and not lg.player_season(pid)["goals"]
                 and lg.player_season(pid)["xg"] < 1 and lg.players[pid]["club"] == "EMB")
    card = {"moment_id": "m", "minute": 81, "type": "big_chance", "team": "EMB", "facts": {"player": quiet}}
    assert all(f["kind"] != "player_xg" for f in lg.talking_facts(card, "EMB", "SMC"))
    card["facts"]["player"] = "EMB-9"                                  # 12 goals: worth saying
    assert lg.talking_facts(card, "EMB", "SMC")[0]["kind"] == "player_xg"


def test_talking_points_name_players_in_full() -> None:
    facts = [{"kind": "scorer_season", "name": "Ciro Oakenfold"}]
    assert check_full_names("A pesar del gol de Oakenfold, Emberfield sigue primero.", facts)
    assert check_full_names("Oakenfold's 13th goal of the season.", facts)
    assert check_full_names("Ciro Oakenfold has scored 13 this season.", facts) == []
