# COMEBACK

### You left the match. COMEBACK didn't.

Nobody watches 90 minutes straight. You go to the kitchen, answer a message, join
at the 60th minute, and that is always when the goal comes. COMEBACK notices that
**you** left, keeps watching for you, **calls you back before the big moment** (and
tells you why), then tells you **what you missed**: in your language, from your
club's side, sized to how long you were gone.

And it does that for every fan at almost no extra cost: one shared match brain
writes each key moment once, so serving **200,000** simulated fans takes about
about **1,900** LLM calls instead of more than 600,000.

[![Open in GitHub Codespaces](https://github.com/codespaces/badge.svg)](https://codespaces.new/imaneoujja/comeback)

![COMEBACK control room: the fan is called back before the goal and gets a catch-up of what changed](docs/screenshot.png)

> Built for *Inside the Game: Developer Hackathon* (Microsoft × Premier League),
> challenge "Synthetic Match Insights Engine". All data is **synthetic**; all
> clubs and players are **fictional**.

---

## What it does

| | What happens | In the demo match |
|---|---|---|
| **1. You leave** | A Watcher agent keeps watching for you. It knows your club, favourite player, level and language. | Omar (Emberfield fan, analyst, French) leaves at 66'. |
| **2. It's heating up** | It calls you back **before** the moment, and says why. Your phone takes over the screen, rings, and reads the reason aloud. | 67': *"Reviens — Emberfield est entré 3 fois dans la surface en 2 minutes et a tenté 2 tirs."* |
| **3. You return** | A "Previously on…" catch-up of what **changed**, sized to your absence (one line, the key moments, or the full story). | 70': a catch-up in French, then the 71' goal. |
| **4. Full-time** | Your own front page: the match told from your side. | Sofia (Comets fan): *"Heartbreaking loss for Saltmarsh Comets after strong start"*. |

Around this loop sits a **broadcast control room**: a 3D program feed with
broadcast graphics (player tags, pass difficulty, shot speed, speed and distance
tags, danger index), an AGENTS monitor showing the agents at work, a simulated
audience of 10,000 fans, and **timed, machine-readable overlay cues** a broadcast
graphics renderer could consume.

## Try it (zero configuration, no API key)

**GitHub Codespaces:** click the badge above. The server starts by itself; open
the forwarded port **8000**.

**Locally** (Python ≥ 3.10):

```bash
git clone https://github.com/imaneoujja/comeback.git && cd comeback
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m comeback                                   # → http://localhost:8000
```

It runs **offline by default**. The demo match is precomputed, and its verified
LLM texts are committed in `data/llm_cache.jsonl`, so you see real model output
without any key.

### A 3-minute guided tour

1. Click the welcome screen to go live, then set the replay to **×20**. The
   auto-director puts one monitor ON AIR at a time (toggle **AUTO DIRECT**).
2. **Reda** (Spanish, follows striker Halen Merewood): pick his profile. His player
   carries a ★ label all match. Press **Join at 60'** for the story so far.
3. **Omar** (French, analyst, Emberfield fan): press **I'm away** at about 66' (or just
   switch browser tab). Around 67' his phone gets a "come back" alert. Press
   **I'm back** at about 70', read the catch-up, then watch the 71' goal.
4. Optional: **PAIR PHONE** shows a QR code. Scan it with your phone on the same
   Wi-Fi, and the alerts ring and speak on your real phone.
5. **Sofia** (English, casual, Saltmarsh Comets fan): away at about 76', back at
   about 86'. Same match, a completely different story.
6. Let it run to full-time: each fan gets their own front page.

## Related work

Others have already proved fans want this:

- **Prime Video Rapid Recap**: when you join an NBA or NFL game late, an AI recap
  of the key highlights you missed, before you rejoin the live action
  ([AWS](https://aws.amazon.com/solutions/amazon/one-amazon-lane/streaming)).
- **YouTube TV Key Plays**: catch up to live by jumping through a game's key plays
  ([Google support](https://support.google.com/youtubetv/answer/9119412?hl=en-GB)).
- **Turner Sports Excitement Alerts**: notifications when a game becomes close or
  turns into an upset ([Airship](https://www.airship.com/blog/turner-sports-ncaa-march-madness/)).

They show the need. But recaps wait for the fan to ask (or to join late), and
excitement alerts are about a whole game, for everyone. COMEBACK starts from the
fan's own attention: it notices that *you* left, calls *you* back *before* the
moment, from *your* club's side, and tells *you* what you missed. We don't claim
to be first; we combine these ideas around presence, at a cost that doesn't grow
with the audience.

## Presence signals

COMEBACK needs to know whether you are watching. All signals are opt-in, and it
uses no camera and no microphone.

| | Signals |
|---|---|
| **This demo** | Switching browser tab (Page Visibility API), the *I'm away / I'm back* buttons (on the screen or on the paired phone), joining a match in progress. |
| **In production** | The app going to the background, playback paused, inactivity on the player, and push notifications (APNs, FCM or Web Push) to bring the fan back. |

## How it works

```mermaid
flowchart LR
    G[Synthetic match generator<br/>scripted beats + spells of dominance] -->|events, streamed| E

    subgraph BRAIN["Shared match brain (one per match)"]
      E[Match engine — pure Python<br/>stats · pass difficulty · xG · speeds<br/>danger index · control vs chaos<br/>moment detection · overlay cues]
      S[(Moment Store<br/>verified cards)]
    end

    E -->|key moment + facts| A
    subgraph WF["Agent Framework workflow: verified writing"]
      A[Analyst agent] -->|draft| V{Verifier agent}
      V -->|rejected: precise feedback, ≤2 retries| A
      V -->|gave up / LLM down| T[Template fallback]
    end
    V -->|verified card| S
    T -->|flagged card| S

    E --> W[Watcher agents<br/>one per fan · rules, no LLM]
    S --> W
    W -->|fan returns / full-time| ST[Storyteller agent<br/>same verified-writing workflow]
    W -->|come-back & goal alerts| UI
    ST -->|catch-up · full-time recap| UI[FastAPI · Server-Sent Events<br/>control room + fan's phone]
    E -->|timed overlay cues| UI
```

### Agents, distinct roles, one shared state

| Agent | Input | Output | LLM? |
|---|---|---|---|
| **Analyst** | Compact computed facts of one key moment (never the raw event log), plus the match situation | Headline + "why it matters" (English, neutral), cited event ids | Yes |
| **Verifier** | A draft + the facts + the roster | Pass, or precise feedback for a retry | Rules (deterministic) |
| **Watcher** (one per fan) | The live danger index, the fan's presence and profile | "Come back" decision + reason, goal notifications | No: instant and free per fan |
| **Storyteller** | The verified cards of the away window, a "what changed" delta, the fan profile | Catch-up or full-time recap in the fan's language, level and point of view | Yes |

- **Orchestration.** Analyst → Verifier → retry → fallback is a **Microsoft Agent
  Framework workflow** (`comeback/agents/workflow.py`) with typed executors and
  conditional edges. The *same* workflow serves the Storyteller. Every step is
  traced live on the AGENTS monitor.
- **Shared state and handoffs.** The engine and the Moment Store are written once
  and read by every Watcher and by the Storyteller. A moment gets a template card
  instantly, so nobody waits for the LLM; it is upgraded when the verified card lands.
- **Recovery from failure.** Rate limit (429), timeout, network error, budget
  exhausted, invalid JSON, or three rejected drafts: each ends with a
  deterministic, fact-based template flagged `source: "template"`. Tests force
  every path.

## One match brain for every fan

The AUDIENCE monitor simulates 10,000 fans with random absences and late joins,
all served by the same engine and agents. Alert decisions are computed **once per
team**; a catch-up needs a new LLM story only when its (moments, language, level,
club, length) combination has never been written.

LLM calls needed to serve the whole demo match, by audience size (`/api/scale`):

| Fans | COMEBACK | One LLM call per catch-up |
|---|---|---|
| 1,000 | 699 | 3,058 |
| 10,000 | 1,260 | 31,317 |
| 50,000 | 1,578 | 157,433 |
| 200,000 | **1,854** | **628,386** |

These are cost figures on the scripted demo match. They say nothing about how
accurate the alerts are: that is measured separately, below.

## Does "come back" actually predict anything?

Measured with `python scripts/evaluate_alerts.py` **only on 50 unscripted
synthetic matches** (random fixtures, no story beats). The demo match is
scripted for storytelling and is **never** used for these numbers. Rule: danger
≥ 55, rising, not within 20 s of the team's own shot (that chance is already
over), 3-minute cooldown.

| Metric (unscripted matches only) | Value |
|---|---|
| Alerts per team per match | 3.1 |
| Alert followed by a shot with xG ≥ 0.1 within 60 s | **21%** (chance baseline: 5%, **×4.5**) |
| Goals preceded by an alert for the scoring team (5-min window) | 33% |
| Median lead time before those goals | 91 s |

These are honest numbers on synthetic data, and improving them is our main next
step. Validating them on real tracking data is future work. In the scripted demo,
every goal is preceded by an alert about the team that then scores, for each of
the three fans. That is a design check of the demo scenario (a test), not a
performance claim.

## The Verifier earns its place

These are real errors from our recordings with `gpt-4.1-mini` (plus one our
tests caught). Each one became a rule:

| The model wrote | Why it was wrong | Rule now enforced |
|---|---|---|
| "Emberfield equalise *despite being a man down*" | Saltmarsh Comets had the red card | A "ten men" claim must name the short-handed team |
| "*the fastest shot of the season*" | The facts only cover this match | No season, league, career or all-time claims |
| "*The striker almost extended the lead* for Emberfield" | Emberfield were trailing 1-2 (the bare score "1-2" was misread) | Every score handed to the agents is labelled with team names |
| "Emberfield *grabbed a well-earned draw*" (at 86') | The match was not over | No final result (win, draw, defeat) before full-time, in all three languages |
| "Emberfield won, *overcoming a numerical advantage for Saltmarsh Comets*" | Saltmarsh Comets had 10 players | Numerical advantage or disadvantage claims must attach to the right team, including "for X", "against ten-man X" and "overcoming…" |
| "The striker scores his *9th*" (test case) | Invented: the 9 came from the player id `EMB-9` | Every number must exist in the facts; ids are not statistics |

The Verifier also rejects players who are not part of the moment, clubs outside
the match, and over-long texts.

## Challenge requirement → where in COMEBACK

| Requirement | Where |
|---|---|
| (i-a) **Ingest** events as they happen | `comeback/synth` generates the events; `api/replay.py` streams them; `engine/match.py` processes them one at a time, with no look-ahead |
| (i-b) **Interpret** into stats, patterns, context | `engine/state.py`: possession (overall and rolling), pass accuracy and difficulty, xG, speeds, distance with the ball, control vs chaos; `engine/danger.py`, `engine/moments.py` |
| (i-c) **Explain** why a moment matters | Analyst's "why it matters"; storylines (redemption, the substitute's impact, comeback, numerical advantage); delta-based catch-ups |
| (i-d) **Render** on screen, machine-readable | 3D program feed with broadcast graphics; `GET /api/overlays/{match}`: timed JSON cues per layer and audience |
| (i-e) **Personalize** | Presence (away, back, late join); club point of view; favourite player tagged all match; casual vs analyst (different overlays and stories); language; the fan's focus metric on screen |
| (ii) Player identification | Lower-third name tags; the followed player is labelled in 3D all match |
| (ii) Speed and distance on thresholds | Speed tag at ≥ 32 km/h sprints; distance tag every 100 m a player covers with the ball |
| (ii) Pass quality | Distance, accuracy and a 0–100 difficulty rating, with ball speed |
| (ii) Ball and shot speed | Pass ball speed; shot speed tag on every shot |
| (ii) Auto-eventing from video | **Not implemented.** COMEBACK works on event streams (synthetic here) |
| (iii) Narratives, player context, milestones, recaps | Moment cards; milestones (fastest shot, top speed, 50 completed passes); catch-ups; per-fan full-time recap |
| (iv) Control vs chaos, pressure, rhythm | Control (rolling possession × accuracy) and chaos (duels + turnovers per minute); danger index; momentum swings; momentum timeline |
| (v) Synthetic data innovation | Possession simulator with spells of dominance, transparent scripted beats, realism tests, a 10,000-fan audience simulation |
| (vi) Multi-language storytelling | Catch-ups, alerts and recaps in English, French and Spanish; voices picked per language |

## Microsoft technologies

| Technology | Where |
|---|---|
| **Microsoft Agent Framework** (Python) | The LLM agents (Analyst, Storyteller) are `agent_framework.Agent`s. The verified-writing workflow is an Agent Framework `WorkflowBuilder` graph: writer, Verifier and fallback executors, conditional edges, a retry loop, and a live trace of every step (`comeback/agents/workflow.py`, `llm.py`). |
| **Microsoft Foundry** | LLM inference: Azure OpenAI `gpt-4.1-mini`, Global Standard deployment, through Foundry's OpenAI-compatible v1 endpoint. A 30k TPM cap and a daily call budget protect the credit. |
| **GitHub Codespaces** | One-click, zero-config environment for judges (`.devcontainer/`). |
| GitHub / GitHub Copilot | Development workflow. |

The whole demo match costs **34 LLM calls**: 17 moment cards, 8 personal stories
(catch-ups and full-time recaps) and 9 revisions requested by the Verifier.

## Data and match intelligence

**Synthetic data** (`comeback/synth/`) comes from a possession-based simulator:
passes with difficulty, carries, sprints, pressure, tackles, interceptions, fouls,
cards, penalties, shots with xG and speed, corners, throw-ins, goal kicks,
substitutions and stoppage time. It has six fictional clubs with distinct playing
styles and a latent "spells of dominance" process, because real matches come in
waves. Scripted scenarios inject story beats transparently: they are recorded in
the match metadata. Averages over 20 unscripted matches, checked by tests:

| Passes | Pass accuracy | Shots | xG | Goals | Possession range |
|---|---|---|---|---|---|
| 878 | 79% | 26.1 | 3.06 | 2.85 | 35–65% |

**Pass difficulty** (0–100): distance, pressure, forward ratio, final third and
long-ball terms; completion probability is a logistic of passing skill minus
difficulty. **xG**: logistic of distance and goal-mouth angle (headers penalised).
**Danger index** (0–100, last ~2 minutes): exponentially decayed sum of box
entries, final-third passes, passes into the opponent half, shots (10 + 40·xG),
corners, high regains and successful pressure, squashed with tanh.

## Broadcast overlay API

`GET /api/overlays/demo-comeback?profile=omar` returns timed, renderer-agnostic cues:

```json
{"cue_id": "c00352", "t_in": 4425.2, "t_out": 4430.2, "layer": "top_right",
 "template": "shot_speed", "priority": 70, "audience": "all",
 "data": {"team": "EMB", "player": "EMB-9", "player_name": "Ciro Oakenfold",
          "shot_speed_kmh": 96.0, "xg": 0.327, "outcome": "goal"}}
```

Templates: `player_tag`, `pass_quality`, `shot_speed`, `sprint` (speed),
`distance`, `danger`, `moment`. Each cue targets `all`, `analyst` or `casual` viewers.

Other endpoints: `GET /api/stream` (Server-Sent Events: events, snapshots, cues,
cards, agent steps, crowd, alerts, catch-ups, full-time recap),
`POST /api/session/{id}/away | back | join?minute=60 | speed | pause | profile`,
`GET /api/scale/{match}`, `GET /phone?session=` (paired phone),
`GET /api/match/{id}`, `GET /api/profiles`.

## Run with your own Foundry deployment (optional)

```bash
cp .env.example .env    # set FOUNDRY_ENDPOINT, FOUNDRY_API_KEY, FOUNDRY_MODEL
LLM_MODE=live python -m comeback                 # any absence gets a freshly written story
LLM_MODE=record python scripts/precompute.py     # re-record the demo cache
```

## Development

```bash
pytest                        # 47 tests: realism, engine, verifier, workflow paths, watchers, crowd, API
ruff check .
python -m comeback.synth.cli random --count 5    # more synthetic matches
python scripts/evaluate_alerts.py
```

```
comeback/
  synth/    teams, simulator, scenarios, CLI      (synthetic data)
  engine/   state, passes, xg, danger, moments, overlays, alerts, match
  agents/   llm (Foundry gateway), workflow, analyst, verifier, storyteller,
            watcher, templates, brain (shared state)
  fans/     profiles, session, catch-up selection, crowd (audience simulation)
  api/      FastAPI server, replay sessions (SSE)
web/        control room (ES modules, no build step; Three.js from a CDN) + phone page
scripts/    precompute.py, evaluate_alerts.py, hello_agent.py
data/       demo match, profiles, committed LLM cache
```

## Limits and next steps

- Synthetic data only; the alert must be improved (33% of goals announced on
  unscripted matches) and validated on real data.
- Offline mode serves cached stories for the demo's absences; other windows get
  the (verified) template text unless `LLM_MODE=live`.
- No auto-eventing from video.
- Next: a personalised replay of the missed moments with a neural voice, cloud
  hosting, Foundry evaluations, and an MCP server so any agent can query the live match.

## License

MIT. See [LICENSE](LICENSE). No real clubs, players, leagues, logos or
broadcasters are used or implied.
