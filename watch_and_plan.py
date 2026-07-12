"""
Distill a tutorial video into a checkpoint plan by actually WATCHING it:
a cloud browser agent opens the video, scrubs through it, and describes
the on-screen UI actions it observes at each point — no captions, no
transcript API involved at all.

Usage:
  python watch_and_plan.py <video_url> "<goal to eventually replicate>"
"""

import json
import sys

from hai_agents import Client
from hai_agents.core.api_error import ApiError

PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "steps": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "milestone": {"type": "string"},
                    "instruction": {"type": "string"},
                    "verify": {"type": "string"},
                    "irreversible": {"type": "boolean"},
                },
                "required": ["id", "milestone", "instruction", "verify", "irreversible"],
            },
        }
    },
    "required": ["steps"],
}

WATCH_INSTRUCTIONS = (
    "You distill software tutorials into checkpoint plans by WATCHING them, never by "
    "reading captions, subtitles, or a transcript. Open the given video, then scrub through "
    "it (drag the seek bar or use skip-forward) and pause every so often to look at the frame: "
    "what's the cursor doing, what menu or dialog is open, what got clicked or typed. Skip "
    "intro chatter, sponsor reads, and talking-head segments with no on-screen software use. "
    "From what you visually observed, output an ordered list of atomic UI steps (one "
    "click/menu/typing action each), each with the milestone name, the instruction, what must "
    "be visible on screen to confirm it succeeded, and whether it's irreversible (shares, "
    "publishes, deletes, sends). Sampling roughly 8-12 points across the video's timeline is "
    "enough — you do not need to watch every second."
)

client = Client()  # reads HAI_API_KEY


def ensure_agent() -> None:
    try:
        client.agents.create_agent(
            name="video-watcher-agent",
            description=(
                "Distills a software tutorial video into a checkpoint plan by watching it "
                "(scrubbing + screenshots), never by reading captions or a transcript."
            ),
            environments=["h/browser"],
            model="holo3-1-35b-a3b",
            instructions=WATCH_INSTRUCTIONS,
            answer_format=PLAN_SCHEMA,
        )
        print("Created agent: video-watcher-agent")
    except ApiError as e:
        if e.status_code == 409:
            print("Agent already exists, reusing: video-watcher-agent")
        else:
            raise


def watch_and_plan(video_url: str, goal: str) -> dict:
    task = (
        f"Watch this tutorial video by actually looking at it (never read captions/transcript): "
        f"{video_url}\n\nGoal I eventually want to replicate myself: {goal}\n\n"
        "Scrub/skip through the video, pause at points where the demonstrator does something "
        "in the software, and compile what you saw into the checkpoint plan."
    )
    result = client.run_session(
        agent="video-watcher-agent",
        messages=task,
        max_time_s=300,
    )
    plan = result.answer if isinstance(result.answer, dict) else json.loads(result.answer)
    plan["action"] = goal
    plan["source_video"] = {"url": video_url}
    plan["distilled_by"] = "watching (screenshots), not transcript"
    plan["session_id"] = result.id
    return plan


def main() -> None:
    video_url, goal = sys.argv[1], sys.argv[2]
    ensure_agent()
    plan = watch_and_plan(video_url, goal)
    with open("plan.json", "w") as f:
        json.dump(plan, f, indent=2)
    print(f"Distilled {len(plan['steps'])} steps by watching {video_url}")
    print(f"Session: https://platform.hcompany.ai/agents/sessions/{plan['session_id']}")
    print("Wrote plan.json")


if __name__ == "__main__":
    main()
