# Reel-Learn

Improve computer-use agents using reels: watch a tutorial video the same way a
person would (scrub, look, no captions), distill what you saw into a
checkpoint plan, and use that plan to make a computer-use agent better at
replicating the task — while measuring, rather than guessing, where the
underlying agent actually breaks.

Built on [H Company's](https://hcompany.ai) `hai-agents` platform
(`h/web-surfer-flash`/`pro` baselines, `h/desktop` environments, custom
Agents and Skills).

## The core finding

A baseline agent given a tutorial-derived plan got anchored on one instructed
step ("click Rename in the Document submenu") and repeated a near-identical
click **~40 times** across a 76-step session — coordinates jittering by <2% of
screen — without ever self-detecting the loop. The same architecture handles
a *different* failure class (login walls, bot checks) cleanly, self-reporting
"blocked" within 2–3 steps every time. So this isn't "the model can't detect
failure" broadly — it detects environment-level blockers fine, but has no
equivalent for interaction-level ones (a click that silently does nothing).

Full write-up with quoted trajectory evidence: [`findings.html`](findings.html).
Narrative context and open threads: [`HANDOFF.md`](HANDOFF.md).

## Pipeline

```
watch_and_plan.py / watch_and_plan_local.py / youtube_to_local_skill.py
        │  (watch a tutorial video, distill a checkpoint plan — no transcript)
        ▼
   plan.json / plan_local.json
        │
        ▼
fix_noisy_poem.py, tutorial-informed agents
        │  (use the plan as guidance, not a script — this is where the
        │   stuck-loop failure was found and reproduced)
        ▼
hard_trajectory_pool.json  ──▶  run_pilot.py  ──▶  export_session_csv.py
   (curated hard tasks:            (executes the pool,      (logs every
    web + read-only desktop)        gated flash→pro)          click/type/wait)
        ▼
score_hardness.py  ──▶  hard_trajectory_results.json
   (repeat_action_rate, severity ranking, hard-not-impossible gate)
        ▼
register_unstuck_skill.py
   (ships the fix: a "no-progress-guard" Skill that forces a strategy
    switch or an honest "blocked" after N near-identical failed actions)
```

## What's in this repo

**Watching & planning**
- `watch_and_plan.py` — cloud browser agent watches a tutorial video (scrub +
  screenshot, no transcript) and distills an ordered checkpoint plan.
- `watch_and_plan_local.py` — same idea, against a locally-running bridge.
- `youtube_to_local_skill.py` — self-contained pipeline: watch a YouTube video
  in your real signed-in local Chrome, distill a plan, pull the real
  screenshots the agent looked at, and register the result as a reusable
  Skill on your account.
- `extract_screenshots.py` — turns a plan's per-step screenshots into
  attachable image messages for a downstream agent.

**Using a plan / the failure this project is about**
- `fix_noisy_poem.py` — drives local Audacity to remove background noise from
  an audio file, guided by a watched-tutorial checkpoint plan (non-destructive:
  always exports a new file, never overwrites the source).
- `steer_session.py` — pause a running session and redirect it mid-flight.
- `demo.py` — minimal `hai-agents` session + Gradium TTS example.

**Finding & measuring hard trajectories**
- `hard_trajectory_pool.json` — the benchmark pool: WebArena/Mind2Web-style
  web tasks plus a `readonly_desktop_pool` of local macOS desktop tasks
  (nested menus, ambiguous targets, dynamic UI) that are hard but
  deliberately non-destructive — none of them edit, save, or delete real
  files.
- `run_pilot.py` — executes the pool (`web`, `desktop`, `readonly-desktop`,
  `pro-followup`, `score`), gated flash→pro so "hard" is separated from
  "impossible."
- `export_session_csv.py` — pulls every event off a session
  (`sessions.get_session_changes()`) into `*_events.csv` (per-action: tool,
  args, thought excerpt, timestamp) and `*_summary.csv` (per-session: steps,
  clicks, types, waits, navigations, elapsed time, tokens, outcome).
- `score_hardness.py` — turns that raw telemetry into a hardness number:
  `repeat_action_rate` (the literal metric behind the stuck-loop finding),
  a severity ranking, and the hard-not-impossible gate. Local-only, no API
  calls.
- `diagnose_session.py` — quick one-off inspection of a single session id.

**The fix**
- `register_unstuck_skill.py` — creates/updates the `no-progress-guard` Skill
  and attaches it to an agent: if the last ~4 actions target the same element
  within ~2% coordinate tolerance with no visible change, force a
  structurally different interaction (keyboard nav, double-click, re-locate
  by text) or an honest "blocked" instead of repeating the click.

**Logged data from real runs**
- `pilot_manifest.csv`, `pilot_events.csv`, `pilot_summary.csv` — the
  read-only desktop pilot's session log.
- `sessions_events.csv`, `sessions_summary.csv`,
  `sessions_events_stuckloop_investigation.csv`,
  `sessions_summary_stuckloop_investigation.csv` — logs from the web pool and
  from the original stuck-loop investigation.
- `plan.json`, `plan_local.json` — example distilled checkpoint plans.

**Example**
- `example_noisy_music.wav` / `example_noisy_music_cleaned.wav` — before/after
  audio from the Audacity noise-removal pipeline (`fix_noisy_poem.py`),
  driven by a plan distilled purely from watching a tutorial.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Environment variables (see `hai-agents` docs for how to obtain these):
```bash
export HAI_API_KEY=...       # H Company platform key
export GRADIUM_API_KEY=...   # only needed for demo.py's TTS step
```

## Usage

```bash
# Watch a tutorial and distill a plan
python watch_and_plan.py "<video_url>" "<goal to replicate>"

# Run the read-only desktop hardness pool, one task at a time (foreground,
# attended — it takes over your real mouse/keyboard/screen)
python run_pilot.py readonly-desktop <task_id>

# Score hardness from the logged CSVs (no API calls)
python score_hardness.py pilot_summary.csv pilot_events.csv <session_id ...>

# Ship the fix onto an agent
python register_unstuck_skill.py <agent_name>
```

## Status

The read-only desktop pilot (4 tasks) and the web pool are logged; scoring
across the full set and locking a final stratified hard-trajectory benchmark
is in progress. See `HANDOFF.md` for the exact state of each task and the
open methodology question (how to *systematically* source/construct
"hard trajectory" test cases, not just pick one ad hoc).
