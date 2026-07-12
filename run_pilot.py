"""
run_pilot.py — executes the hard-trajectory pilot pool (hard_trajectory_pool.json)
and logs every session, so the "hard trajectory" set gets picked by measured
numbers instead of guesswork.

Reuses, does not reimplement:
  - export_session_csv.export_session()      logs every session's events + summary
  - score_hardness.{gate, severity, load_summary}   the hard-not-impossible gate
                                                       and severity ranking
  - the ensure_agent() 409-catch-and-reuse pattern from watch_and_plan.py

Every session_id this writes comes from a real client.run_session() call —
nothing here fabricates or simulates a trajectory.

Usage:
  python run_pilot.py probe-desktop   # single validation task, desktop env
  python run_pilot.py web             # all web-pool tasks on the baseline (flash)
  python run_pilot.py desktop         # all desktop-pool tasks on flash, one at a
                                       # time, each gated on your confirmation
  python run_pilot.py readonly-desktop  # read-only desktop tasks (no file edits/saves),
                                       # same one-at-a-time flow
  python run_pilot.py pro-followup    # re-runs only the flash failures on pro,
                                       # to separate "hard" from "impossible"
  python run_pilot.py score           # applies the gate + severity ranking,
                                       # writes hard_trajectory_results.json
"""

import csv
import json
import os
import sys
from pathlib import Path

from hai_agents import Client
from hai_agents.types import Agent, Environment_Desktop
from hai_agents_local import ensure_bridges
from hai_agents_local.routing import localize_agent

from export_session_csv import EVENTS_HEADER, SUMMARY_HEADER, export_session
from score_hardness import gate, load_summary, severity

POOL_PATH = Path("hard_trajectory_pool.json")
MANIFEST_PATH = Path("pilot_manifest.csv")
EVENTS_PATH = Path("pilot_events.csv")
SUMMARY_PATH = Path("pilot_summary.csv")
RESULTS_PATH = Path("hard_trajectory_results.json")

MANIFEST_HEADER = ["task_id", "session_id", "agent", "environment", "phase"]

FLASH_WEB_AGENT = "h/web-surfer-flash"
PRO_WEB_AGENT = "h/web-surfer-pro"
DESKTOP_ENV_ID = "hard-traj-desktop"
FLASH_DESKTOP_AGENT = "hard-traj-desktop-flash"
PRO_DESKTOP_AGENT = "hard-traj-desktop-pro"

# Server-side per-session budget (max_time_s) and client polling ceiling
# (timeout_seconds, kept a little above max_time_s so the client doesn't
# give up before the server-side budget naturally ends the session). The
# original d000f506 stuck-loop session had neither set explicitly and was
# cut off by an unrelated client default — this pins both deliberately.
MAX_TIME_S = 300
TIMEOUT_S = 360

client = Client()


def load_pool() -> dict:
    return json.loads(POOL_PATH.read_text())


def ensure_csv_headers() -> None:
    if not MANIFEST_PATH.exists():
        with MANIFEST_PATH.open("w", newline="") as f:
            csv.writer(f).writerow(MANIFEST_HEADER)
    if not EVENTS_PATH.exists():
        with EVENTS_PATH.open("w", newline="") as f:
            csv.writer(f).writerow(EVENTS_HEADER)
    if not SUMMARY_PATH.exists():
        with SUMMARY_PATH.open("w", newline="") as f:
            csv.writer(f).writerow(SUMMARY_HEADER)


def append_manifest(task_id: str, session_id: str, agent: str, environment: str, phase: str) -> None:
    with MANIFEST_PATH.open("a", newline="") as f:
        csv.writer(f).writerow([task_id, session_id, agent, environment, phase])


def log_session(session_id: str) -> None:
    with EVENTS_PATH.open("a", newline="") as ef, SUMMARY_PATH.open("a", newline="") as sf:
        export_session(session_id, csv.writer(ef), csv.writer(sf))


def run_task(task_id: str, instruction: str, agent, agent_label: str, environment: str, phase: str) -> None:
    """agent: a catalog agent name (str) for web tasks, or an already-localized
    inline Agent object for desktop tasks (see run_desktop_task)."""
    print(f"\n--- {task_id} ({phase} / {agent_label}) ---")
    print(instruction)
    result = client.run_session(
        agent=agent, messages=instruction, max_time_s=MAX_TIME_S, timeout_seconds=TIMEOUT_S,
    )
    print(f"session: {result.id}  status={result.status}  outcome={result.outcome}")
    append_manifest(task_id, result.id, agent_label, environment, phase)
    log_session(result.id)


def run_desktop_task(task_id: str, instruction: str, agent_name: str, description: str, model: str, phase: str) -> None:
    """
    Desktop tasks use an INLINE Agent (not a catalog name) so the SDK's own
    localize_agent()/ensure_bridges() spin up the pyautogui bridge in this
    process. A catalog agent referenced by name (client.agents.create_agent +
    agent="name") is explicitly excluded from this auto-localization per
    hai_agents_local/routing.py — that was the bug in the first two live
    attempts: a named agent + a manually-run 'hai local desktop' in another
    terminal have no way to find each other's session id.
    """
    agent_spec = Agent(
        name=agent_name,
        description=description,
        environments=[Environment_Desktop(id=DESKTOP_ENV_ID, host="user_device")],
        model=model,
    )
    input(
        f"\nAbout to run '{task_id}': {instruction}\n"
        "This starts a local bridge in this same process and hands it your actual "
        "mouse/keyboard/screen for the duration of the task — no separate terminal needed. "
        "Press Enter when you're ready to watch your screen..."
    )
    localized_agent, bridges = localize_agent(agent_spec, api_key=os.environ["HAI_API_KEY"])
    print("Starting local desktop bridge...")
    ensure_bridges(bridges)
    print("Bridge ready.")
    run_task(task_id, instruction, localized_agent, agent_name, "desktop", phase)


def cmd_probe_desktop(pool: dict) -> None:
    probe = pool["desktop_probe_task"]
    run_desktop_task(
        probe["id"], probe["instruction"], FLASH_DESKTOP_AGENT,
        "Desktop counterpart to h/web-surfer-flash for the hard-trajectory pilot.",
        "holo3-1-35b-a3b", "flash",
    )


def cmd_web(pool: dict) -> None:
    web_tasks = [t for t in pool["pool"] if t["environment"] == "web"]
    print(f"Running {len(web_tasks)} web tasks on {FLASH_WEB_AGENT} (cloud-sandboxed, unattended-safe).")
    for t in web_tasks:
        run_task(t["id"], t["instruction"], FLASH_WEB_AGENT, FLASH_WEB_AGENT, "web", "flash")


def cmd_desktop(pool: dict) -> None:
    desktop_tasks = [t for t in pool["pool"] if t["environment"] == "desktop"]
    print(
        f"Running {len(desktop_tasks)} desktop tasks one at a time. Each one takes over your "
        "actual mouse/keyboard — watch the screen for each."
    )
    for t in desktop_tasks:
        run_desktop_task(
            t["id"], t["instruction"], FLASH_DESKTOP_AGENT,
            "Desktop counterpart to h/web-surfer-flash for the hard-trajectory pilot.",
            "holo3-1-35b-a3b", "flash",
        )


def cmd_readonly_desktop(pool: dict) -> None:
    tasks = pool["readonly_desktop_pool"]["tasks"]
    filter_ids = sys.argv[2:]
    if filter_ids:
        tasks = [t for t in tasks if t["id"] in filter_ids]
    print(
        f"Running {len(tasks)} read-only desktop tasks one at a time. Each takes over your "
        "actual mouse/keyboard — none of them edit, save, or delete anything; watch the screen "
        "for each."
    )
    for t in tasks:
        run_desktop_task(
            t["id"], t["instruction"], FLASH_DESKTOP_AGENT,
            "Desktop counterpart to h/web-surfer-flash for the read-only hard-trajectory pilot.",
            "holo3-1-35b-a3b", "flash",
        )


def cmd_pro_followup(pool: dict) -> None:
    if not SUMMARY_PATH.exists():
        print("No pilot_summary.csv yet — run 'web' and/or 'desktop' first.")
        return
    summary_rows = load_summary(str(SUMMARY_PATH))
    manifest_rows = list(csv.DictReader(MANIFEST_PATH.open())) if MANIFEST_PATH.exists() else []
    tasks_by_id = {t["id"]: t for t in pool["pool"]}

    followups = 0
    for m in manifest_rows:
        if m["phase"] != "flash":
            continue
        task = tasks_by_id.get(m["task_id"])
        if task is None:
            continue
        flash_row = next((r for r in summary_rows if r["session_id"] == m["session_id"]), None)
        if flash_row is None:
            continue
        flash_failed = flash_row["status"] != "completed" or flash_row["outcome"] in ("", "partial", "blocked")
        if not flash_failed:
            continue
        followups += 1
        if task["environment"] == "web":
            run_task(task["id"], task["instruction"], PRO_WEB_AGENT, PRO_WEB_AGENT, "web", "pro")
        else:
            run_desktop_task(
                task["id"], task["instruction"], PRO_DESKTOP_AGENT,
                "Desktop counterpart to h/web-surfer-pro, used only for pilot pro-followup.",
                "holo3-122b-a10b", "pro",
            )
    if followups == 0:
        print("No flash failures found in the manifest — nothing to follow up on.")


def cmd_score(pool: dict) -> None:
    summary_rows = load_summary(str(SUMMARY_PATH))
    manifest_rows = list(csv.DictReader(MANIFEST_PATH.open()))

    flash_session_ids = {m["session_id"] for m in manifest_rows if m["phase"] == "flash"}
    flash_summary_rows = [r for r in summary_rows if r["session_id"] in flash_session_ids]

    results = []
    for task in pool["pool"]:
        flash_m = next((m for m in manifest_rows if m["task_id"] == task["id"] and m["phase"] == "flash"), None)
        pro_m = next((m for m in manifest_rows if m["task_id"] == task["id"] and m["phase"] == "pro"), None)
        if flash_m is None:
            continue
        flash_row = next(r for r in summary_rows if r["session_id"] == flash_m["session_id"])
        pro_row = next((r for r in summary_rows if r["session_id"] == pro_m["session_id"]), None) if pro_m else None
        is_hard = gate(flash_row, pro_row)
        sev = severity(flash_m["session_id"], flash_summary_rows, str(EVENTS_PATH))
        results.append({
            "task_id": task["id"],
            "category": task["category"],
            "hard_not_impossible": is_hard,
            **sev,
        })
    results.sort(key=lambda r: r["severity_score"], reverse=True)
    RESULTS_PATH.write_text(json.dumps(results, indent=2))
    gated = sum(r["hard_not_impossible"] for r in results)
    print(f"Wrote {RESULTS_PATH} — {gated} of {len(results)} tasks gated as hard-not-impossible")


COMMANDS = {
    "probe-desktop": cmd_probe_desktop,
    "web": cmd_web,
    "desktop": cmd_desktop,
    "readonly-desktop": cmd_readonly_desktop,
    "pro-followup": cmd_pro_followup,
    "score": cmd_score,
}


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print(f"Usage: python run_pilot.py {{{'|'.join(COMMANDS)}}} [task_id ...]")
        sys.exit(1)
    ensure_csv_headers()
    pool = load_pool()
    COMMANDS[sys.argv[1]](pool)


if __name__ == "__main__":
    main()
