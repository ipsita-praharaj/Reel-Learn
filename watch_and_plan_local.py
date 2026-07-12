"""
watch_and_plan_local.py — same distillation as watch_and_plan.py (WATCH, don't
read captions/transcript), but drives the user's actual local Chrome via the
desktop bridge instead of a cloud-sandboxed h/browser environment. Point: the
real Chrome is already signed into the user's real YouTube account, so no
cloud-side login/bot-check dance is needed.

Takes over the real mouse/keyboard/screen for the duration of the run (same
mechanism as run_pilot.py's run_desktop_task) — must be run in the foreground,
attended, never backgrounded.

Usage:
  python watch_and_plan_local.py <video_url> "<goal to eventually replicate>"
"""

import json
import os
import sys

from hai_agents import Client
from hai_agents.core.api_error import ApiError
from hai_agents.types import Agent, Environment_Desktop
from hai_agents_local import ensure_bridges
from hai_agents_local.routing import localize_agent

from watch_and_plan import PLAN_SCHEMA, WATCH_INSTRUCTIONS

DESKTOP_ENV_ID = "hard-traj-desktop"  # same id run_pilot.py already validated permissions against
LOCAL_WATCH_INSTRUCTIONS = WATCH_INSTRUCTIONS + (
    "\n\nUse the Chrome browser already open on this machine — it is already signed into the "
    "user's real YouTube account, so do not attempt to sign in or use a different browser. If "
    "Chrome isn't already open, open it. Open the given URL in a new tab, then watch it there."
)

client = Client()


def watch_and_plan_local(video_url: str, goal: str) -> dict:
    agent_spec = Agent(
        name="video-watcher-local",
        description=(
            "Distills a software tutorial video into a checkpoint plan by watching it in the "
            "user's real, already-authenticated local Chrome, never by reading captions/transcript."
        ),
        environments=[Environment_Desktop(id=DESKTOP_ENV_ID, host="user_device")],
        model="holo3-1-35b-a3b",
        instructions=LOCAL_WATCH_INSTRUCTIONS,
        answer_format=PLAN_SCHEMA,
    )

    input(
        f"\nAbout to watch: {video_url}\n"
        "This hands your actual mouse/keyboard/screen to the agent for up to 5 minutes so it "
        "can open your real Chrome and scrub through the video there. Press Enter when you're "
        "ready to watch your screen..."
    )
    localized_agent, bridges = localize_agent(agent_spec, api_key=os.environ["HAI_API_KEY"])
    print("Starting local desktop bridge...")
    ensure_bridges(bridges)
    print("Bridge ready. Watching...")

    task = (
        f"Watch this tutorial video by actually looking at it in your real local Chrome (never "
        f"read captions/transcript): {video_url}\n\nGoal I eventually want to replicate myself: "
        f"{goal}\n\nOpen it in Chrome, scrub/skip through, pause at points where the demonstrator "
        "does something in the software, and compile what you saw into the checkpoint plan."
    )
    result = client.run_session(
        agent=localized_agent, messages=task, max_time_s=300, timeout_seconds=360,
    )
    plan = result.answer if isinstance(result.answer, dict) else json.loads(result.answer)
    plan["action"] = goal
    plan["source_video"] = {"url": video_url}
    plan["distilled_by"] = "watching (local Chrome, real account), not transcript"
    plan["session_id"] = result.id
    return plan


def main() -> None:
    video_url, goal = sys.argv[1], sys.argv[2]
    plan = watch_and_plan_local(video_url, goal)
    with open("plan_local.json", "w") as f:
        json.dump(plan, f, indent=2)
    print(f"Distilled {len(plan['steps'])} steps by watching {video_url} in local Chrome")
    print(f"Session: https://platform.hcompany.ai/agents/sessions/{plan['session_id']}")
    print("Wrote plan_local.json")


if __name__ == "__main__":
    main()
