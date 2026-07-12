"""
youtube_to_local_skill.py — self-contained, single-file pipeline:

  1. Opens a YouTube link in YOUR real, already-signed-in local Chrome (via the
     H Company desktop bridge) — no cloud login/bot-check needed, because it's
     driving the actual browser on your machine, not a sandboxed one.
  2. Watches the video by scrubbing + screenshotting it (never reads captions
     or a transcript) and distills an ordered checkpoint plan (JSON).
  3. Pulls the actual screenshots the watching agent looked at off the
     session and saves them locally, one per plan step.
  4. Registers a new Skill on your H Company account whose body is the
     distilled text steps, each pointing at its local screenshot file.

Requires only `hai_agents` + `hai_agents_local` (both already in this
project's .venv) and the env vars HAI_API_KEY (~/.config/hai/.env) set.

Usage:
  python youtube_to_local_skill.py <youtube_url> "<goal>" [skill_name]

Example:
  python youtube_to_local_skill.py \\
      "https://www.youtube.com/shorts/g3W3zy9ENCs" \\
      "Remove background noise from a podcast recording using Audacity's Noise Reduction effect" \\
      audacity-noise-reduction
"""

import base64
import json
import os
import re
import sys
from pathlib import Path

import httpx
from hai_agents import Client
from hai_agents.core.api_error import ApiError
from hai_agents.types import Agent, Environment_Desktop
from hai_agents_local import ensure_bridges
from hai_agents_local.routing import localize_agent

DESKTOP_ENV_ID = "hard-traj-desktop"

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
    "reading captions, subtitles, or a transcript. Use the Chrome browser already open on "
    "this machine — it is already signed into the user's real accounts, so never attempt to "
    "sign in or switch browsers. Open the given URL in a new tab, then scrub through it (drag "
    "the seek bar or use skip-forward) and pause every so often to look at the frame: what's "
    "the cursor doing, what menu or dialog is open, what got clicked or typed. Skip intro "
    "chatter, sponsor reads, and talking-head segments with no on-screen software use. From "
    "what you visually observed, output an ordered list of atomic UI steps (one click/menu/"
    "typing action each), each with the milestone name, the instruction, what must be visible "
    "on screen to confirm it succeeded, and whether it's irreversible (shares, publishes, "
    "deletes, sends). Sampling roughly 8-12 points across the video's timeline is enough."
)

STOPWORDS = {"the", "a", "an", "to", "in", "on", "of", "and", "or", "is", "this",
             "that", "with", "for", "at", "click", "then", "you", "your", "it", "be", "as"}


def _words(text: str) -> set:
    return {w for w in re.findall(r"[a-z]+", text.lower()) if w not in STOPWORDS and len(w) > 2}


client = Client()


def watch_locally(video_url: str, goal: str) -> dict:
    """Step 1+2: drive the user's real local Chrome to watch the video and
    distill a plan. Takes over the real mouse/keyboard/screen for the run."""
    agent_spec = Agent(
        name="video-watcher-local",
        description="Distills a tutorial video into a checkpoint plan by watching it in the user's real local Chrome.",
        environments=[Environment_Desktop(id=DESKTOP_ENV_ID, host="user_device")],
        model="holo3-1-35b-a3b",
        instructions=WATCH_INSTRUCTIONS,
        answer_format=PLAN_SCHEMA,
    )
    input(
        f"\nAbout to watch: {video_url}\n"
        "This hands your actual mouse/keyboard/screen to the agent for up to 5 minutes so it "
        "can open your real Chrome and scrub through the video there. Press Enter when ready..."
    )
    localized_agent, bridges = localize_agent(agent_spec, api_key=os.environ["HAI_API_KEY"])
    ensure_bridges(bridges)

    task = (
        f"Watch this tutorial video in your real local Chrome (never read captions/transcript): "
        f"{video_url}\n\nGoal to eventually replicate: {goal}\n\nScrub/skip through, pause where "
        "the demonstrator does something in the software, and compile a checkpoint plan."
    )
    result = client.run_session(agent=localized_agent, messages=task, max_time_s=300, timeout_seconds=360)
    plan = result.answer if isinstance(result.answer, dict) else json.loads(result.answer)
    plan["action"] = goal
    plan["source_video"] = {"url": video_url}
    plan["distilled_by"] = "watching (local Chrome, real account), not transcript"
    plan["session_id"] = result.id
    return plan


def save_screenshots(session_id: str, out_dir: Path) -> list:
    """Step 3: pull every screenshot the session actually looked at."""
    out_dir.mkdir(parents=True, exist_ok=True)
    changes = client.sessions.get_session_changes(session_id, from_index=0)
    shots, last_reasoning, idx = [], "", 0
    for e in changes.new_events:
        d = e.data
        kind = getattr(d, "kind", None)
        if kind == "policy_event":
            last_reasoning = (d.reasoning_content or d.content or "")[:400]
        elif kind == "observation_event" and getattr(d, "image", None):
            idx += 1
            img = d.image
            ext = (img.media_type or "image/png").split("/")[-1]
            fname = out_dir / f"obs_{idx:03d}.{ext}"
            try:
                if img.type == "base64":
                    fname.write_bytes(base64.b64decode(img.source.split(",")[-1]))
                else:
                    resp = httpx.get(img.source, follow_redirects=True,
                                      headers={"Authorization": f"Bearer {os.environ['HAI_API_KEY']}"})
                    resp.raise_for_status()
                    fname.write_bytes(resp.content)
            except Exception as exc:
                print(f"  skip obs_{idx:03d}: {exc}")
                continue
            shots.append({"path": str(fname), "context_text": last_reasoning})
    return shots


def correlate(plan: dict, shots: list) -> None:
    """Attach each step's best-matching screenshot by keyword overlap."""
    steps = plan["steps"]
    step_words = [_words(s["milestone"] + " " + s["instruction"]) for s in steps]
    for s in steps:
        s["screenshots"] = []
    for shot in shots:
        scores = [len(sw & _words(shot["context_text"])) for sw in step_words]
        best = max(range(len(steps)), key=lambda i: scores[i]) if scores else None
        if best is not None and scores[best] > 0:
            steps[best]["screenshots"].append(shot["path"])
    for i, s in enumerate(steps):
        if not s["screenshots"] and shots:  # fallback: even spread
            s["screenshots"] = [shots[i * len(shots) // len(steps)]["path"]]
        s["screenshot"] = s["screenshots"][0] if s["screenshots"] else None


def build_skill_body(plan: dict) -> str:
    """Step 4: render the plan as skill prose. Skill bodies are text-only, so
    screenshots are referenced by local path, not embedded as pixels — attach
    the actual image bytes as message content (images=[...]) when a task
    that uses this skill actually runs, rather than expecting the skill text
    itself to carry them."""
    lines = [
        f"Goal: {plan['action']}",
        f"Distilled by watching {plan['source_video']['url']} ({plan['distilled_by']}).",
        "",
        "Each step below is a hint about one demonstrated way to reach its milestone, not a "
        "literal script — the verify condition is what actually matters; re-derive intent from "
        "it if the real UI doesn't match the instruction wording.",
        "",
    ]
    for s in plan["steps"]:
        flag = " [IRREVERSIBLE]" if s["irreversible"] else ""
        lines.append(f"Step {s['id']} — {s['milestone']}{flag}")
        lines.append(f"  instruction: {s['instruction']}")
        lines.append(f"  verify: {s['verify']}")
        if s.get("screenshot"):
            lines.append(f"  reference screenshot: {s['screenshot']}")
        lines.append("")
    return "\n".join(lines)


def register_skill(name: str, description: str, body: str) -> None:
    try:
        client.skills.create_skill(name=name, description=description, body=body)
        print(f"Created skill: {name}")
    except ApiError as e:
        if e.status_code == 409:
            client.skills.update_skill(name, name=name, description=description, body=body)
            print(f"Updated existing skill: {name}")
        else:
            raise


def slugify(text: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", text.lower())).strip("-")[:60]


def main() -> None:
    video_url, goal = sys.argv[1], sys.argv[2]
    skill_name = sys.argv[3] if len(sys.argv) > 3 else slugify(goal)

    plan = watch_locally(video_url, goal)
    plan_path = Path(f"plan_{skill_name}.json")

    shots_dir = Path("screenshots") / plan["session_id"]
    shots = save_screenshots(plan["session_id"], shots_dir)
    correlate(plan, shots)
    plan_path.write_text(json.dumps(plan, indent=2))

    body = build_skill_body(plan)
    register_skill(
        name=skill_name,
        description=f"Checkpoint plan (text + screenshots) for: {goal}",
        body=body,
    )

    print(f"\nPlan: {plan_path}")
    print(f"Screenshots: {shots_dir}/ ({len(shots)} files)")
    print(f"Skill: platform.hcompany.ai/agents/skills -> {skill_name}")


if __name__ == "__main__":
    main()
