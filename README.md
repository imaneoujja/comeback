# COMEBACK

[![CI](https://github.com/imaneoujja/comeback/actions/workflows/ci.yml/badge.svg)](https://github.com/imaneoujja/comeback/actions/workflows/ci.yml)
[![Live demo](https://img.shields.io/badge/live%20demo-Azure%20Container%20Apps-0078D4)](https://comeback.lemonforest-f9ddbdf8.switzerlandnorth.azurecontainerapps.io)
[![Open in GitHub Codespaces](https://img.shields.io/badge/open%20in-Codespaces-24292f?logo=github)](https://codespaces.new/imaneoujja/comeback)
![Microsoft Agent Framework](https://img.shields.io/badge/Microsoft%20Agent%20Framework-1.22-0078D4)
![Microsoft Foundry](https://img.shields.io/badge/Microsoft%20Foundry-gpt--4.1--mini-0078D4)
![Python 3.12](https://img.shields.io/badge/python-3.12-3776AB)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

**An AI match insights engine for studio and streaming that personalizes on what each fan
saw, or missed.**

![COMEBACK in 20 seconds: a fan sets up their match, steps away, gets called back before the goal with the reason, comes back to a replay and a spoken catch-up, then the studio's control room](docs/comeback.gif)

### You left the match. COMEBACK didn't.

Today fans check the score every five minutes and are present nowhere: not at their
kid's match, not in front of the game. COMEBACK reads every event of the match live,
explains why moments matter, and personalizes them for each fan (language, side, level,
favourite player, one metric). Step away, and it calls you back **before** the big
moment, with the reason; come back, and it replays what you missed and tells you what
changed. **Put your phone away. COMEBACK will tell you when it matters.**

- **54% of goals announced in advance**, 1.6× better than the same number of random
  alerts, on 50 unseen matches, with a **median warning of 60 s**. We announce big
  moments; we do not claim to predict goals.
- **Verified text**: every number and name is checked before a fan sees it. A single
  LLM agent doing everything delivers a factual problem in 12% of its texts; COMEBACK in 0,
  and Microsoft Foundry's evaluators score the 46 texts fans see 5.0/5 on groundedness.
- **One brain for every fan**: serving **200,000** simulated fans takes about
  **1,830** LLM calls instead of more than 630,000 (≈ $0.60 instead of ≈ $812).

> *The future of football isn't more screens. It's a match that fits your life.*

### Try it in 60 seconds

1. Open the **[live demo](https://comeback.lemonforest-f9ddbdf8.switzerlandnorth.azurecontainerapps.io)** on a computer, choose **A fan**, your side and language, and press **START**: the default *Step away 63'–70'* runs the whole loop in about 90 s.
2. Or **[open it in GitHub Codespaces](https://codespaces.new/imaneoujja/comeback)**: it starts by itself on port 8000.
3. Or locally: `pip install -r requirements.txt && python -m comeback` → http://localhost:8000

No account, no key: it runs offline (see *What runs live, what is cached?* in the FAQ).

> Built for *Inside the Game: Developer Hackathon* (Microsoft × Premier League), challenge
> "Synthetic Match Insights Engine". All data is **synthetic**; all clubs and players are
> **fictional**.

---

## What it does

| | What happens | In the demo match |
|---|---|---|
| **1. You leave** | A Watcher agent keeps watching for you, under your own rules (goal threats, equaliser or winner only, any big moment; night mode). It knows your side, favourite player, level and language. | An Emberfield fan (French, analyst) steps away at 63', 0–2 down. |
| **2. It's heating up** | It calls you back **before** the moment, and says why. Your phone takes over the screen, rings, and reads the reason aloud. | 65' and 69': *"Reviens — Emberfield est entré 3 fois dans la surface en 2 minutes et a tenté 1 tir."* |
| **3. You return** | Spoiler-free: if a goal happened, your phone only said "something big happened"; the score waits for your replay. The TV rewinds: the moments you missed are replayed in 3D from behind the goal while a neural voice reads your "Previously on…" catch-up of what **changed**, sized to your absence. A live goal cuts the replay short. | 70': a catch-up in French, then the 71' goal, seen live. The phone confirms: *"COMEBACK l'avait senti : alerte à la 69e, but à la 71e."* |
| **4. Full-time** | Your own front page: the match told from your side. | A Comets fan gets *"Heartbreak as Saltmarsh Comets lose late after red card"*. |

![The fan view: back at 70', the TV shows the French catch-up of what changed, with SHOW ENGLISH and LISTEN; next to the match, the phone pairing panel and the two call-backs sent before the goal](docs/screenshot.png)

The first screen asks **who is watching**. A **fan** gets the TV (a 3D program feed with
broadcast graphics: player tags, pass difficulty, shot speed, speed and distance tags,
danger index) and a panel to pair their phone. A **studio** gets the broadcaster's
control room: the agents at work, the Watcher's decisions for the whole audience, the same
call-back as three audience segments get it, a simulated audience of 10,000 fans, and
**timed, machine-readable overlay cues** a broadcast graphics renderer could consume.

## Why not just stream it on your phone?

Because a stream, or a commentary turned up loud, asks for 90 minutes of attention, and
COMEBACK is built for the moments when you have none to give: on the touchline at your
kid's match (our main case), on a work call, putting the kids to bed, or asleep through a
4 a.m. kick-off in another time zone (night mode: "wake me only if…"). Your phone is in
your pocket, face down. It is not COMEBACK's competitor; it is its channel: one buzz, one
sentence with the reason, at the right time, at most twice per absence, opt-in and under
your rules. And when you are back, the stream does not tell you what changed. COMEBACK
does, in your language and from your side.

**For broadcasters and the official app (B2B2C):** COMEBACK is a layer they integrate, not
one more app. It does not pull viewers away from the live feed; it brings back fans who
had already left, before the peak moment, instead of sending a spoiler after it. In the
simulation, 882 of 10,000 fans were back in time for the 71' goal (assumption: 65% of
called fans return; a real figure needs an A/B test in production).

## Try it (zero configuration, no API key)

**Online:** open the [live demo](https://comeback.lemonforest-f9ddbdf8.switzerlandnorth.azurecontainerapps.io) in a desktop browser. As a fan, scan the
**Pair your phone** QR code next to the match: your phone becomes your device, from anywhere.
The app scales to zero when nobody uses it, so the first request wakes it up.

**GitHub Codespaces:** click the Codespaces badge at the top. The server starts by itself; open
the forwarded port **8000**.

**Locally** (Python ≥ 3.10):

```bash
git clone https://github.com/imaneoujja/comeback.git && cd comeback
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m comeback                                   # → http://localhost:8000
```

It runs **offline by default**, and what you see is live: on every visit the match
engine, the danger index, the Watchers, the Verifier and the simulated audience run
for real. Only the agents' texts for the two playable matches are cached
(`data/llm_cache.jsonl`, written once by Foundry), so you see real model output
without any key; a window we did not precompute gets a verified template instead.
The first screen also offers an **unscripted match**, replayed with the same engine,
Watchers and Verifier.

### What to try

The first screen asks who is watching.

1. **A fan.** Pick a side (home club, away club, or follow a player), a language
   (English, French, Spanish), a style (casual or analyst), your one number, and when
   you watch:
   - **Step away 63'–70'** (the default): the match starts at 59'; you leave at 63',
     COMEBACK calls you back at 65' and 69' with the reason, and at 70' the TV replays
     what you missed while a neural voice reads your "Previously on…". Then the 71' goal,
     live.
   - **Join late at 60'**: you missed the first hour, you get the story so far.
   - **From kick-off**: leave whenever you like (switch browser tab or press I'M AWAY).

   Next to the match, **Pair your phone** shows a QR code: scan it and the call-backs
   ring and speak on your own phone. **CALL ME BACK FOR** sets your rules. **CHANGE**
   (top bar) switches language, side or style without restarting the match.
2. **A studio.** The broadcaster's control room, from 60': the program feed, the agents
   at work (drafts, Verifier rejections, revisions), the Watcher's decision for the whole
   audience (**DECISIONS**), the same call-back as three audience segments get it
   (**PERSONALIZE**), 10,000 simulated fans and the cost curve, the timed overlay cues
   (**CUES**), and **⚡ CUT THE LLM** to watch the show go on without it.
3. Let a fan's match run to full-time: they get their own front page.

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
| **Watcher** (one per fan) | The live danger index, the fan's presence and profile | "Come back" decision + reason, goal notifications, a "called it" receipt when a goal follows its call-back | No: instant and free per fan |
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
- **Failure drill, live.** In the STUDIO view, **⚡ CUT THE LLM** simulates an outage
  for your session only (`POST /api/session/{id}/outage`): every agent call fails
  as a real outage would, cards and catch-ups keep arriving as verified templates
  (amber badge), the stream never stops, and **RESTORE** brings the writers back.
- **Fact-checks on screen.** When the Verifier rejects a draft, the studio's AGENTS
  monitor shows it: the wrong words struck through, the Verifier's reason, then the
  version that went on air. In the demo, at 81' the Analyst gave the ten men "their
  numerical advantage"; the Verifier caught it and only the corrected card aired.

![Fact-check in the AGENTS monitor: the Analyst's draft with "numerical advantage" struck through, the Verifier's reason, and the corrected card that went on air](docs/factcheck.png)

The studio view shows the whole crew at work: the agents' live log, the Watcher's
decisions, the personalization of one call-back for three audience segments, the
10,000-fan audience, the overlay cues, engine data and the rundown of verified cards.

![Studio view: program feed, agents log, Watcher decision chain, one call-back for three segments, simulated audience, overlay cues, match data and rundown](docs/studio.png)

Every call-back comes with its decision chain, time-stamped (studio **DECISIONS**
monitor): the events observed with their ids, the danger state and its trend, the insight
(sustained pressure, not a prediction), and the decision with every condition checked and
who was called: the away fans of both sides, counted per side.

![Decision chain of the 69' call-back: events with their ids, danger state and trend, the insight without a goal promise, the conditions checked and how many away fans of each side were called](docs/decision.png)

## One match brain for every fan

The AUDIENCE monitor simulates 10,000 fans with random absences and late joins,
all served by the same engine and agents. Alert decisions are computed **once per
team**; a catch-up needs a new LLM story only when its (moments, language, level,
club, length) combination has never been written.

LLM calls needed to serve the whole demo match, by audience size (`/api/scale`):

| Fans | COMEBACK | One LLM call per catch-up |
|---|---|---|
| 1,000 | 659 | 3,077 |
| 10,000 | 1,191 | 31,591 |
| 50,000 | 1,515 | 158,631 |
| 200,000 | **1,830** | **633,938** |

These are cost figures on the scripted demo match. They say nothing about how
accurate the alerts are: that is measured separately, below. The audience is
simulated once per match and shared by every viewer of that match (not once per
visitor). "Fans back in time for the goal" (882 for the 71' goal) rests on a
**simulation assumption**: 65% of called fans return within two minutes. A real
figure needs an A/B test in production.

## Does "come back" actually predict anything?

**COMEBACK announces big moments; it does not predict goals.** We measure how often
its call-backs come true, with a fixed protocol (`scripts/evaluate_alerts.py`):

- **Matches:** unscripted synthetic matches only (random fixtures, no story beats). The
  scripted demo match is never used for these numbers; the script refuses it.
- **Tuning vs test:** the threshold was tuned on seeds 1001–1050 (to announce at least
  half of the goals) and is reported on **50 other, held-out matches** (seeds 2001–2050).
- **Precision:** an alert "comes true" if the same team has a shot with xG ≥ 0.1 within
  **90 s**. **Recall:** a goal is "announced" if an alert for the scoring team came in the
  previous **5 minutes** (the anticipation window). Lead time = goal time − last alert.
- **Chance baseline:** the **same number** of alerts placed at random instants (same
  teams), averaged over 20 random draws, scored with the same definitions.

| Held-out unscripted matches (129 goals) | COMEBACK | Same number of random alerts |
|---|---|---|
| Recall: goals announced within 5 min | **54%** (70/129) | 34% (**1.6×**) |
| Precision: alerts followed by a chance (xG ≥ 0.1) within 90 s | **21%** | 8% (**2.8×**) |
| False alerts per match (both teams) | 11.6 | 13.5 |
| Alerts per team per match | 7.3 | same |
| **Call-backs one fan actually receives per match** (simulated absences, max 2 per absence) | **1.9** | |
| Median warning before an announced goal | **60 s** | |
| Median time from an alert to the chance that follows | 16 s | |
| Decision latency (event → alert decision, compute) | p50 0.02 ms · p95 0.04 ms | |

Stricter or looser, at a glance (same held-out matches):

![Precision vs recall for alert thresholds 30 to 65; 44 is the chosen balance](docs/alert_curve.svg)

| Threshold | Recall | Precision | Alerts / team / match |
|---|---|---|---|
| 36 | 70% | 19% | 10.8 |
| **44 (default)** | **54%** | **21%** | **7.3** |
| 55 (night mode) | 32% | 23% | 3.2 |
| 65 | 9% | 30% | 0.8 |

Honest reading: most goals in our simulator come from short attacks, so many goals
are not preceded by sustained pressure, and most alerts are not followed by a goal.
That is why a fan receives at most two calls per absence, sets their own rules
(goal threats, equaliser or winner only, any big moment; night mode raises the bar
to 55 and calls once), and why every call states its reason instead of promising a
goal. Validated on synthetic data; real-data validation is future work. In the
scripted demo every goal is preceded by a call about the scoring team: that is a
design check of the story (a test), not a performance claim.

### The danger index, in the open

Every call-back cites the events that triggered it (the STUDIO **DECISIONS** monitor
shows the chain: events → state → insight → why this fan, why now).

| Ingredient (for the attacking team) | Weight |
|---|---|
| Pass or carry into the box | 8 |
| Shot | 10 + 40 × xG |
| Corner | 6 |
| Ball won in the opponent's half | 5 |
| Completed pass into the final third | 2 |
| Successful pressure | 2 |
| Completed pass in the opponent's half | 0.6 |

Each contribution decays exponentially (time constant 60 s; forgotten after 6 min), the
sum is squashed into 0–100 with `100 · tanh(sum / 55)` (`comeback/engine/danger.py`).
The alert rule (`comeback/engine/alerts.py`): danger ≥ 44 (night mode 55), rising by at
least 3 points over 30 s, not within 20 s of the team's own shot (that chance is over),
3-minute cooldown, at most 2 calls per absence (night mode 1).

### Latency and load

| Measured | Value |
|---|---|
| Danger → alert decision (engine update + rule, compute) | p50 0.02 ms · p95 0.04 ms |
| Alert decision → the fan's screen (server push over SSE, measured in the browser, localhost) | 10–13 ms |
| Alert → the chance it announced (median) / → the goal (median, when announced) | 16 s / 60 s |
| 10 simultaneous viewers, ×40 replay (`scripts/load_test.py`, local machine) | 0 errors · 13 events/s per viewer · API p50 5 ms, p95 9 ms |
| 10 simultaneous viewers on the **public demo** (Azure Container Apps, 0.5 vCPU, measured from Paris) | 0 errors · full event rate · API p50 0.53 s, p95 0.64 s, the same as with 1 viewer (network distance, not load) |

The engine, the Watchers and the Verifier run live for every viewer; the 10,000-fan
audience is simulated once per match and shared, so a new viewer costs one replay loop.

### Reproduce the numbers

```bash
python scripts/evaluate_alerts.py                     # held-out table above (seeds 2001-2050)
python scripts/evaluate_alerts.py --first-seed 1001   # the tuning matches
python scripts/evaluate_alerts.py --curve             # threshold sweep + docs/alert_curve.svg
python scripts/compare_single_agent.py                # multi-agent vs one agent (offline, cached replies)
python scripts/load_test.py --viewers 10 --seconds 30 # needs a running server
python scripts/evaluate_texts.py                      # Foundry evaluations (needs a Foundry key)
curl localhost:8000/api/scale/demo-comeback           # LLM calls by audience size
```

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
| "Larkhaven drew 2-2 *despite fewer chances*" | Larkhaven had 21 shots to 7. Our rules missed it; **Foundry's groundedness judge caught it** (2/5) | Comparative claims (fewer/more chances, shots, possession) must agree with the per-team stats |

The Verifier also rejects players who are not part of the moment, clubs outside
the match, insulting or mocking words about players, betting talk, and over-long
texts. And it was tuned against its own false positives: "Emberfield, playing against
ten men" is correct and now passes (the ten men are the opponents of the team named
before).

### One agent, or a team of agents?

The principle: **LLMs where language is needed, deterministic code where truth is needed.**
To check that the split pays off, `scripts/compare_single_agent.py` gives ONE LLM agent the
same engine facts and the same instructions about names and numbers, and asks it to write
every moment card and a fan's catch-up in one call (no verification), for 3 fans on the demo
match and 2 unscripted matches. It only sees what had happened when the fan came back. Every
text is then checked with the Verifier's rules.

| | One LLM agent does everything | COMEBACK (Analyst → Verifier → Storyteller, shared brain) |
|---|---|---|
| Texts with a factual problem delivered to fans | **7 / 57 (12%)** | **0 / 57** (1 template fallback) |
| Key moments left without a card | 47 of 95 | 0: a template card at once, the verified text when ready |
| What went wrong / what was caught | player or club not in the facts 5, invented or wrong number 4, result announced before full time 2 | caught before air: numerical advantage on the wrong team 5, wrong number 3, player not in the facts 3, early result 1 |
| LLM calls for 200,000 fans (demo match) | 633,921 (one per catch-up) | **1,830** (cards once, stories shared) |
| Cost for 200,000 fans (gpt-4.1-mini list price) | ≈ $812 | **≈ $0.60** |
| Latency | ≈ 3.9 s per fan, only after the absence | template card instantly; verified card ≈ 1.7 s (median call) |

Replies are cached in `data/experiments/compare_cache.jsonl`, so the table replays offline.
The single agent is not a strawman: same model, same facts, same rules in its
instructions; it simply has nobody to check it and no shared memory across fans.

### Foundry evaluations, before and after the Verifier

`python scripts/evaluate_texts.py` replays both playable matches, recovers the exact facts
behind every draft, and scores it with Microsoft Foundry's AI-assisted evaluators
(`azure-ai-evaluation`, judge: our `gpt-4.1-mini` deployment, 1–5). *Before* = the first
draft of every text (what a pipeline without the Verifier would show); *after* = the texts
fans actually see.

| Texts (demo + unscripted match) | n | Groundedness | Coherence | Fluency | Groundedness < 4 |
|---|---|---|---|---|---|
| Before the Verifier: first drafts | 46 | 4.93 | 4.39 | 4.00 | 1 |
| … of which the Verifier sent back | 5 | 4.40 | 4.60 | 4.00 | 1 |
| **After the Verifier: texts shown to fans** | **46** | **5.00** | 4.37 | 3.98 | **0** |
| Control: 3 cards deliberately corrupted (teams swapped, invented stat) | 3 | **2.00** | 3.67 | 3.33 | 3 |

What we learned: the LLM judge and the rule-based Verifier catch **different** errors. The
judge scored most drafts the Verifier rejected 5/5 (a numerical advantage given to the wrong
team, an invented number); the Verifier missed one qualitative claim the judge flagged
("despite fewer chances" with 21 shots to 7), which we turned into a rule. The Verifier can
be too strict as well: it once rejected every Comets fan's full-time story for "leaving
**you** with 10 men" (true for that fan) and Spanish texts for *el empate* (the equaliser,
not a final draw); both rules now read the fan's point of view and the language. The
control row shows the judge is not lenient on gross errors. Details per text:
[`docs/evaluation.json`](docs/evaluation.json).

## Responsible AI

- **No betting, no odds, no prediction market.** COMEBACK announces pressure and big
  moments with the reason; it never states a probability that a goal will happen, and the
  Verifier rejects betting talk (odds, bets, wagers, in three languages).
- **Respect for people.** Players are real people in real products: the Verifier rejects
  insulting or mocking words about a player or a club, in English, French and Spanish
  (`check_respect` in `comeback/agents/verifier.py`).
- **Facts before fluency.** Every number and every name must exist in the engine's facts;
  numerical-advantage claims must name the right team; no final result before full time;
  nothing outside the match (season, career). What fails is rewritten or replaced by a
  template built from verified facts, and the text says which (`AI-generated · fact-checked`).
- **The fan is in control.** Opt-in alerts, the fan's own rules, at most two calls per
  absence, spoiler-free by default, night mode. No camera, no microphone: presence comes
  from the fan's own signals (see Presence signals).
- **Honest numbers.** Alert metrics on unscripted matches only; the simulation assumption
  behind "fans back in time" is written where the number appears.

## Judging criteria → evidence in the code

| Criterion | Evidence |
|---|---|
| Technological implementation | Pure-Python streaming engine ([`comeback/engine/`](comeback/engine/)), synthetic generator with realism tests ([`comeback/synth/`](comeback/synth/), [`tests/test_synth.py`](tests/test_synth.py)), 60+ tests and ruff in CI ([`.github/workflows/ci.yml`](.github/workflows/ci.yml)), container on Azure Container Apps ([`Dockerfile`](Dockerfile)) |
| Agentic design | Agent Framework workflow Writer → Verifier → retry → fallback ([`comeback/agents/workflow.py`](comeback/agents/workflow.py)); one Watcher per fan with a visible decision chain ([`comeback/agents/watcher.py`](comeback/agents/watcher.py), [`web/js/decision.js`](web/js/decision.js)); shared match brain ([`comeback/agents/brain.py`](comeback/agents/brain.py)); failure drill ([`comeback/agents/llm.py`](comeback/agents/llm.py) `SwitchableGateway`); MCP server ([`comeback/mcp_server.py`](comeback/mcp_server.py)) |
| Multi-agent vs one agent | [`scripts/compare_single_agent.py`](scripts/compare_single_agent.py) → [`docs/single_agent_comparison.json`](docs/single_agent_comparison.json) |
| Real-world impact | Alert protocol and numbers ([`scripts/evaluate_alerts.py`](scripts/evaluate_alerts.py) → [`docs/alerts_eval.json`](docs/alerts_eval.json)), cost at scale ([`comeback/fans/crowd.py`](comeback/fans/crowd.py), `/api/scale`), load test ([`scripts/load_test.py`](scripts/load_test.py)), overlay cues for renderers (`/api/overlays`, `/docs`) |
| UX and presentation | A first screen that sets up the experience (fan or studio, side, language, style, metric, when you watch: [`web/js/setup.js`](web/js/setup.js)); a TV-only fan view with a phone pairing panel; a studio control room; spoiler-free return; the fan's own alert rules ([`comeback/fans/session.py`](comeback/fans/session.py)) |
| Category fit (multi-agent) | Distinct roles, shared state, handoffs, recovery, and an outcome one agent does not reach: the table above |

## Challenge requirement → where in COMEBACK

| Requirement | Where |
|---|---|
| (i-a) **Ingest** events as they happen | `comeback/synth` generates the events; `api/replay.py` streams them; `engine/match.py` processes them one at a time, with no look-ahead |
| (i-b) **Interpret** into stats, patterns, context | `engine/state.py`: possession (overall and rolling), pass accuracy and difficulty, xG, speeds, distance with the ball, control vs chaos; `engine/danger.py`, `engine/moments.py` |
| (i-c) **Explain** why a moment matters | Analyst's "why it matters"; storylines (redemption, the substitute's impact, comeback, numerical advantage); delta-based catch-ups |
| (i-d) **Render** on screen, machine-readable | 3D program feed with broadcast graphics; `GET /api/overlays/{match}`: timed JSON cues per layer and audience, streamed live in the STUDIO **CUES** monitor; OpenAPI at `/docs` |
| (i-e) **Personalize** | What the fan saw or missed (away, back, late join, spoiler-free return); the fan's own alert rules (goal threats, equaliser or winner, any big moment, night mode); club point of view; player mode (the followed player tagged all match); casual vs analyst live (words vs numbers on the danger and control graphics, different overlays and stories); language; one focus metric on screen. The studio's PERSONALIZE monitor shows each call-back as three audience segments get it |
| (ii) Player identification | Lower-third name tags; the followed player is labelled in 3D all match |
| (ii) Speed and distance on thresholds | Speed tag at ≥ 32 km/h sprints; distance tag every 100 m a player covers with the ball |
| (ii) Pass quality | Distance, accuracy and a 0–100 difficulty rating, with ball speed |
| (ii) Ball and shot speed | Pass ball speed; shot speed tag on every shot |
| (ii) Auto-eventing from video | **Not implemented.** COMEBACK works on event streams (synthetic here) |
| (iii) Narratives, player context, milestones, recaps | Moment cards; milestones (fastest shot, top speed, 50 completed passes); catch-ups; per-fan full-time recap |
| (iv) Control vs chaos, pressure, rhythm | Live "control vs chaos" graphic (rolling possession × accuracy; duels + turnovers per minute); danger index and its trend; momentum swings; momentum timeline; every call-back's decision chain (events → state → insight → decision) |
| (v) Synthetic data innovation | Possession simulator with spells of dominance, transparent scripted beats, realism tests, a 10,000-fan audience simulation |
| (vi) Multi-language storytelling | Catch-ups, alerts and recaps in English, French and Spanish, neural voice per language, and a checked **Show English** translation under every non-English catch-up |

## Microsoft technologies

| Technology | Where |
|---|---|
| **Microsoft Agent Framework** (Python) | The LLM agents (Analyst, Storyteller) are `agent_framework.Agent`s. The verified-writing workflow is an Agent Framework `WorkflowBuilder` graph: writer, Verifier and fallback executors, conditional edges, a retry loop, and a live trace of every step (`comeback/agents/workflow.py`, `llm.py`). |
| **Microsoft Foundry** | LLM inference for the Analyst, the Storyteller and the Translator ("Show English"): Azure OpenAI `gpt-4.1-mini`, Global Standard deployment, through Foundry's OpenAI-compatible v1 endpoint. A 30k TPM cap and a daily call budget protect the credit. |
| **Microsoft Foundry evaluations** (`azure-ai-evaluation`) | Groundedness, coherence and fluency of the agents' texts, before and after the Verifier, with a corrupted control set (`scripts/evaluate_texts.py`, results in `docs/evaluation.json`). |
| **Azure AI Speech** (through the same Foundry resource) | Neural voices read each fan's catch-up and full-time recap in their language (`en-GB-RyanNeural`, `fr-FR-HenriNeural`, `es-ES-AlvaroNeural`) while the program feed replays the missed moments (`comeback/agents/speech.py`). The demo's audio is committed, so offline mode still speaks. |
| **Azure Container Apps** | The public demo: the CI image from `ghcr.io`, Consumption plan, 0.5 vCPU, 1 GiB, offline mode; one replica kept warm during judging (27 Oct–10 Nov), scale to zero otherwise. |
| **GitHub Codespaces** | One-click, zero-config environment for judges (`.devcontainer/`). |
| **GitHub Actions + GitHub Container Registry** | CI on every push and pull request (ruff, 64 tests); the container image is built and published to `ghcr.io` from `main` (`.github/workflows/ci.yml`, `Dockerfile`). |
| **Model Context Protocol** | `comeback/mcp_server.py`: any agent, including GitHub Copilot in VS Code, can query the live match. |
| GitHub / GitHub Copilot | Development workflow. |

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

Every endpoint is documented live by FastAPI at **`/docs`** (OpenAPI), on the
[public demo](https://comeback.lemonforest-f9ddbdf8.switzerlandnorth.azurecontainerapps.io/docs) or locally at
http://localhost:8000/docs. The STUDIO view's **CUES** monitor shows the same cues streaming as the match is
rendered. `GET /api/overlays/demo-comeback?profile=omar` returns timed, renderer-agnostic cues:

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

## Ask an agent about the live match (MCP)

`comeback/mcp_server.py` is a Model Context Protocol server that reads a running
COMEBACK (local or deployed) and exposes tools: `live_sessions`, `match_state`,
`danger_now`, `key_moments(since_minute)`, `player_stats(player)`. To use it from
GitHub Copilot (agent mode) in VS Code, install the extras and add `.vscode/mcp.json`:

```json
{ "servers": { "comeback": { "type": "stdio", "command": "python",
  "args": ["-m", "comeback.mcp_server"], "env": { "COMEBACK_URL": "http://localhost:8000" } } } }
```

Then ask Copilot: *"Using comeback, who is dangerous right now and why?"*

## From demo to production

The demo runs as one container. At broadcast scale the same parts map onto Azure services:

```mermaid
flowchart LR
  feed[Live event feed] --> eh[Azure Event Hubs]
  eh --> engine[Match engine, one per match<br/>Container Apps or AKS]
  engine --> brain[(Shared match brain<br/>Azure Cache for Redis)]
  engine --> agents[Analyst · Verifier · Storyteller<br/>Microsoft Foundry]
  agents --> store[(Moment store, fan rules<br/>Azure Cosmos DB)]
  brain --> watchers[Watchers, stateless workers<br/>one decision per team, fanned out]
  watchers --> push[Azure Notification Hubs<br/>to fans' phones]
  store --> api[API and SSE<br/>broadcaster apps, official app, overlay renderer]
  agents --> speech[Azure AI Speech]
  agents -.-> evals[Foundry evaluations and tracing<br/>Application Insights]
```

**Business model (B2B2C).** COMEBACK is a layer that broadcasters, streaming platforms and
the official app integrate, not one more app for fans: an SDK and API for presence-aware
call-backs, catch-ups and overlay cues, priced per match or per active viewer. Its value
for the integrator is live minutes and ad inventory: fans who had left come back before
the peak moment.

**Cost per match at 200,000 fans** (demo match, list prices): about **1,830 LLM calls ≈ $0.60**
(cards written once, stories shared by fans with the same moments, language, level, side
and length), plus ≈ $16 of neural voice if every distinct story is spoken: about
**$0.0001 per fan**. One LLM call per fan would cost ≈ $812 for the text alone.

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

## Limits, synthetic data and what's next

- **Synthetic data only.** The simulator is calibrated on match-level averages (passes,
  accuracy, shots, xG, goals); it has no tracking data, no off-ball movement, no fatigue,
  and its goals come mostly from short attacks. The alert numbers are honest on that data
  and must be validated on real event data; "fans back in time" needs an A/B test in
  production.
- **Offline mode** serves the agents' cached texts for the precomputed windows of the two
  playable matches; other windows get verified templates unless `LLM_MODE=live`.
- **Not implemented:** auto-eventing from video; real push notifications (the paired phone
  receives server-sent events instead).
- **Next:** validation on real event feeds; Notification Hubs push; Foundry tracing of the
  agents; a producer "approve before air" mode in STUDIO; more languages, including
  right-to-left.

## FAQ for judges

**Why not just stream the match on my phone?** Because you cannot always watch or listen:
a kid's match, a call, the night. COMEBACK asks for no attention until it matters, then
buzzes once with the reason. See *Why not just stream it on your phone?*

**Do you predict goals?** No. We announce big moments: 54% of goals were preceded by a call
(1.6× random alerts) on 50 unseen matches, with 60 s of warning; most calls are not
followed by a goal, which is why a call states its reason, not a promise.

**Isn't the demo match scripted?** Yes, its storyline is, and the UI says so. Alert metrics
are measured only on unscripted matches; *Try another match* replays an unscripted fixture
with the same engine, Watchers and Verifier.

**What runs live, what is cached?** On every visit the engine, the danger index, the
Watchers, the Verifier and the 10,000-fan audience run for real. Only the agents' texts of
the two playable matches are cached, so the demo needs no key.

**Is a rule-based Verifier or Watcher really an agent?** They are agents with distinct
roles and their own decisions; we keep LLMs where language is needed and deterministic
code where truth is needed. The comparison table shows what one LLM agent alone delivers.

**What if the LLM fails?** Every text has a verified template fallback. Press **⚡ CUT THE
LLM** in STUDIO: the show goes on.

**Won't fans get spammed or spoiled?** At most two calls per absence (1.9 per match on
average in our simulation), the fan's own rules, night mode, and spoiler-free by default.

**How do you detect that I left?** In the demo: switching browser tab or a button. In
production: opt-in signals the fan already gives (the app in background, the TV off, a
calendar slot), never a camera or a microphone.

**Does it scale?** One brain per match, one decision per team, stories shared across fans:
200,000 fans ≈ 1,830 LLM calls. Ten simultaneous viewers on one small container: no errors.

**Real clubs, players or data?** None. All clubs, players and matches are fictional and
synthetic.

## Run with your own Foundry deployment (optional)

```bash
cp .env.example .env    # set FOUNDRY_ENDPOINT, FOUNDRY_API_KEY, FOUNDRY_MODEL
LLM_MODE=live python -m comeback                 # any absence gets a freshly written story
LLM_MODE=record python scripts/precompute.py     # re-record the cache: 18 fan set-ups × 2 matches
```

## Development

```bash
pytest                        # 68 tests: realism, engine, verifier, workflows, watchers, called-it, crowd, API, setup, drill, concurrency
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
web/        setup screen, fan view, studio control room (ES modules, no build step; Three.js from a CDN) + phone page
scripts/    precompute.py, evaluate_alerts.py, evaluate_texts.py, scale_cache.py, hello_agent.py
data/       demo match, profiles, committed LLM cache
```

## License

MIT. See [LICENSE](LICENSE). No real clubs, players, leagues, logos or
broadcasters are used or implied.
