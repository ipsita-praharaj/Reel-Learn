# Handoff — hai-agents / H Company computer-use investigation

Context dump for a fresh thread. Everything referenced here is a real file or a real session on the account, not a plan — check timestamps/session IDs if anything looks stale.

## What's set up

- **Venv**: `.venv` in this folder. Has `hai-agents[cli]`, `gradium`, `yt-dlp`, `youtube-transcript-api`, `openai`.
- **Auth**: `HAI_API_KEY` lives in `~/.config/hai/.env` (global, written by `hai login`) — NOT in this project's `.env`. `GRADIUM_API_KEY` is in this project's `.env`. Both must be sourced before running any script here: `set -a && source ~/.config/hai/.env && source .env && set +a`.
- **Browser auth**: a dummy Google account (`ipsita.praharaj12@gmail.com`) is logged into Google + Sheets + YouTube, saved as the account's **default chromium browser profile** (`54e9ba48-30a6-461f-8072-10f09bcc301c`, promoted via `set_default_browser_profile`). Any environment with `use_default_browser_profile: true` inherits this. **Caveat**: Google re-challenges with password/2FA fairly often from the cloud IP — treat this as flaky, not solid, especially for Sheets specifically. YouTube playback has stayed reliably authenticated.

## Agents that exist on the account right now

| name | purpose | notes |
|---|---|---|
| `video-watcher-agent` | Watches a tutorial video (scrub + screenshot, no captions) and distills it into a JSON step plan (`answer_format` enforced) | Environment: `use_default_browser_profile: true`. Works well — validated on both Vimeo (no auth) and YouTube (with the dummy login). |
| `tutorial-informed-agent` | Generic web agent meant to use a distilled plan as *guidance* | **This is the one that misbehaved** — see Key Finding below. User wants to rewrite this concept from scratch rather than patch it. |

Baseline used throughout: H's prebuilt `h/web-surfer-flash` (unmodified, no custom agent needed for baseline).

Other prebuilt agents available on the account (not yet used): `h/web-surfer-pro`, `h/web-scraper-pro`, `h/web-scraper-flash`, `h/deep-search-pro`.

Available skills on the platform (all `public`, none custom yet): `h/visual-browser`, `h/textual-browser`, `h/swarm`, `h/company`, `h/planning`, `h/answering`, `h/user-collaboration`, `h/h-identity`.

## Scripts in this folder

- `demo.py` — minimal example: `hai-agents` session + Gradium TTS speaking the answer.
- `watch_and_plan.py <video_url> "<goal>"` — runs `video-watcher-agent`, writes `plan.json`.
- `video_agent_app.py {search|plan|run} ...` — fuller pipeline: `yt-dlp` search → transcript-based distill (superseded by watching) → run comparison. Some of this predates the watch-based approach; **may be worth deleting rather than fixing** per user's "rewrite from scratch" call.
- `compare_agents.py` — early version of the plan-vs-baseline comparison, superseded by `video_agent_app.py run`.
- `export_session_csv.py <session_id> [...]` — **the logging tool**. Pulls every event off `sessions.get_session_changes()` and writes `sessions_events.csv` (per-action: tool, args, thought excerpt, timestamp) + `sessions_summary.csv` (per-session: steps, clicks, types, waits, navigations, screenshots, elapsed seconds, input tokens, outcome). This is the answer to "how do I log clicks/screens/time" — no extra instrumentation needed, it's all in the event stream already.

## Key finding (the one worth keeping)

Full writeup: `findings.md` (rendered at https://claude.ai/code/artifact/3532229b-5450-4a9d-aa71-37ee9113bb64).

**Watching a video and distilling a plan works fine.** The problem is downstream: an agent given that plan as literal instructions (`tutorial-informed-agent`, instructed to treat steps as "guidance not script") still got anchored on one instructed step — "click Rename in the Document submenu" — and repeated near-identical clicks (~40 times, coordinates jittering by <2% of screen) for the rest of a 76-step session, never self-detecting the loop. Session: `d000f506-c039-4d31-9529-805ee6553552`.

Contrast: the same underlying model/architecture handles a *different* failure class — environment blockers (login walls, YouTube's bot check) — cleanly, self-reporting "blocked" within 2-3 steps every time (sessions `545707eb`, `0857e2e2`, `34209bfc`). So this isn't "the model can't detect failure" broadly — it detects environment-level blockers fine, but has no equivalent for interaction-level ones (a click that silently does nothing).

**User's read on this**: baseline (`h/web-surfer-flash`) is already good — don't blame the baseline or the video-watching step. The thing to fix/rebuild is whatever sits between "here's a distilled plan" and "here's an agent executing it," since that's where the anchoring/stuck-loop happened.

## What the user wants next (starting fresh)

1. **Don't reuse `tutorial-informed-agent` or its current design** — rewrite from scratch. Before writing new agents/skills, first figure out what needs improving.
2. **Find "hard trajectories"**: deliberately screenshot-heavy, genuinely difficult tasks (browser *or* general computer-use, not necessarily web) where the baseline predictably struggles — a benchmark set, run and logged *before* any new agent/skill is built, so later improvement has a real before/after.
3. **Log everything** on those runs using the `export_session_csv.py` pattern (steps, clicks, types, waits, screenshots, elapsed time, tokens, outcome) — already built, just point it at new session IDs.
4. **Then** design a new preset Agent + Skill (H's platform has first-class Skills — reusable instruction fragments an agent loads on demand, see `platform.hcompany.ai/skills`) informed by where the hard trajectories actually broke, rather than guessing upfront.

Open question the user still wants a plan for: **how to systematically source/construct "hard trajectory" test cases** (methodology, not just picking one task ad hoc) — this was explicitly deferred to the new thread, not solved here.

## Loose ends / things to sanity-check in the new thread

- `video_agent_app.py` and `compare_agents.py` overlap significantly — pick one lineage or rewrite clean.
- The default browser profile's reliability for Google Sheets specifically is unproven long-term; don't assume it'll stay signed in.
- `plan.json`, `candidates.json`, `comparison.json` in this folder are scratch state from the last run, not durable artifacts — fine to overwrite/delete.

## Update — read-only desktop pilot in progress (started this session, 2026-07-12)

**What's new:** `hard_trajectory_pool.json` now has a `readonly_desktop_pool` section (4 tasks: `ro-calc-chain`, `ro-settings-toggle-revert`, `ro-activity-monitor-drill`, `ro-preview-zoom-measure`) — local macOS desktop tasks that are hard (many clicks, nested menus, ambiguous targets, dynamic UI) but deliberately non-destructive: none of them edit, save, or delete real files. `run_pilot.py` got a matching `cmd_readonly_desktop`, registered as `readonly-desktop`, plus an optional task-id filter (`main()` now allows `len(sys.argv) >= 2`, and `cmd_readonly_desktop` reads `sys.argv[2:]` as an id filter) so a single task can be run at a time:

```bash
cd "/Users/ipsitapraharaj/Desktop/hcomp hack"
source .venv/bin/activate && set -a && source ~/.config/hai/.env && source .env && set +a
printf '\n' | python run_pilot.py readonly-desktop <task_id>
```

(`printf '\n' |` satisfies the script's `input()` confirmation gate non-interactively — needed when running this from an agent/tool rather than a human typing at a real terminal.)

**macOS permissions**: Screen Recording and Accessibility are now granted to both **Claude** and **Visual Studio Code** in System Settings → Privacy & Security (this was the actual blocker on the first attempt — `screencapture` failed silently in a retry loop until granted). Should still be good in the new thread unless the user reinstalls/updates either app.

**Progress so far:**
- ✅ `ro-calc-chain` — completed, outcome `success`, 32 steps, ~309s. Session `86078137-8722-4729-8708-77d9c717e76d`. Logged in `pilot_manifest.csv`/`pilot_events.csv`/`pilot_summary.csv` alongside the earlier web pool rows.
- ⏳ `ro-settings-toggle-revert` — not yet run (user interrupted right before this one to switch threads).
- ⏳ `ro-activity-monitor-drill` — not yet run.
- ⏳ `ro-preview-zoom-measure` — not yet run.
- ⏳ After all 4: score with `python score_hardness.py pilot_summary.csv pilot_events.csv <session_id ...>` (or reuse `cmd_score` in `run_pilot.py`, though that's currently wired to the `hard_trajectory_pool.json` top-level `pool`, not `readonly_desktop_pool` — may need a small extension to score the readonly set specifically).

**User's explicit ask that shaped this pool**: hard-for-a-human-too tasks (lots of clicks/steps, nested menus, ambiguous targets) that ground in the same taxonomy as `findings.md`/OSWorld, but must not touch real files — and every run must happen in the foreground, attended, not backgrounded, so the user can watch it take over their mouse/keyboard live.

**Next in the new thread:** run the remaining 3 tasks one at a time (foreground, same command pattern above), then score hardness across all 4 read-only sessions the same way the web pool was scored.
