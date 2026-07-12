"""
fix_noisy_poem.py — uses the distilled plan.json plan AND the no-progress-guard
skill (already patched onto hard-traj-desktop-flash) to actually drive local
Audacity and remove background noise from noisy_poem.wav.

Non-destructive: exports the result as a NEW file, never overwrites the
original recording or saves a project file over it.

Passes the plan's real screenshots as attached image content (not just file
paths) so the executing agent has genuine visual reference frames, per
extract_screenshots.py's plan_to_messages() approach.

Usage:
  python fix_noisy_poem.py
"""

import base64
import io
import json
import os
import subprocess
import time
from pathlib import Path

from PIL import Image

from hai_agents import Client
from hai_agents.types import Agent, Environment_Desktop, UserMessageEvent
from hai_agents_local import ensure_bridges
from hai_agents_local.routing import localize_agent

DESKTOP_ENV_ID = "hard-traj-desktop"
SOURCE_WAV = Path("noisy_poem.wav").resolve()
OUTPUT_WAV = Path("noisy_poem_cleaned.wav").resolve()
PLAN_PATH = Path("plan_local.json")

client = Client()


def open_audacity_with_file() -> None:
    """Launch Audacity with the source file already loaded, via a direct OS
    call rather than having the agent hunt for the icon and navigate a File>
    Open dialog — that GUI navigation was the slow, wasted part."""
    subprocess.run(["osascript", "-e", 'tell application "Audacity" to quit'], check=False)
    time.sleep(2)
    subprocess.run(["open", "-a", "/Applications/Audacity.app", str(SOURCE_WAV)], check=True)
    time.sleep(5)
    subprocess.run(["osascript", "-e", 'tell application "Audacity" to activate'], check=True)
    subprocess.run(
        ["osascript", "-e",
         'tell application "System Events" to set visible of every process '
         'whose visible is true and name is not "Audacity" to false'],
        check=True,
    )
    time.sleep(1)


def plan_to_task_text(plan: dict) -> str:
    lines = [
        f"Audacity is ALREADY OPEN with {SOURCE_WAV} loaded in the track — do not try to open "
        "the app or the file again, do not use File > Open. Start directly from selecting a "
        "noise-only region of the waveform.",
        f"Remove background noise from the audio file at: {SOURCE_WAV}",
        f"Export the cleaned result as a NEW file at: {OUTPUT_WAV}",
        "Do not overwrite or modify the original file in any way, and do not save an Audacity "
        "project on top of it — only produce the new exported WAV.",
        "",
        "Reference checkpoint plan, distilled by watching a real Audacity noise-reduction "
        "tutorial (treat each step's verify condition as the goal, its instruction as one hint "
        "about how to get there, not a literal script — the real dialog/menu layout may differ "
        "slightly from what was demonstrated):",
        "",
    ]
    for s in plan["steps"]:
        lines.append(f"Step {s['id']} — {s['milestone']}")
        lines.append(f"  instruction: {s['instruction']}")
        lines.append(f"  verify: {s['verify']}")
    lines.append("")
    lines.append(
        "After capturing the noise profile and applying reduction, use File > Export > Export "
        "as WAV (handle any metadata-tags dialog that pops up by accepting defaults) to save "
        f"to {OUTPUT_WAV}. Confirm the new file exists before finishing."
    )
    return "\n".join(lines)


def downscale_jpeg(path: Path, max_width: int = 1024, quality: int = 70) -> str:
    """Requests are capped at 5MB total; full-res PNG screenshots (~1MB each,
    11 of them) blow past that. Shrink + re-encode as JPEG before attaching."""
    img = Image.open(path).convert("RGB")
    if img.width > max_width:
        img = img.resize((max_width, int(img.height * max_width / img.width)))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    return f"data:image/jpeg;base64,{base64.b64encode(buf.getvalue()).decode()}"


def collect_reference_images(plan: dict) -> list:
    """One representative screenshot per step (not every candidate) — keeps
    the payload small and avoids near-duplicate frames from the same pause."""
    images = []
    for s in plan["steps"]:
        p = s.get("screenshot")
        if p and Path(p).exists():
            images.append(downscale_jpeg(Path(p)))
    return images


def main() -> None:
    plan = json.loads(PLAN_PATH.read_text())
    task_text = plan_to_task_text(plan)
    images = collect_reference_images(plan)
    print(f"Attaching {len(images)} real reference screenshots from the checkpoint plan.")

    agent_spec = Agent(
        name="audacity-noise-fix",
        description="Removes background noise from a local audio file using Audacity, guided by a watched-tutorial checkpoint plan.",
        environments=[Environment_Desktop(id=DESKTOP_ENV_ID, host="user_device")],
        model="holo3-1-35b-a3b",
    )

    input(
        f"\nAbout to fix: {SOURCE_WAV.name}\n"
        "This opens Audacity with the file already loaded, then hands your actual mouse/"
        "keyboard/screen to the agent to apply noise reduction and export a cleaned copy. "
        "Original file is left untouched. Press Enter when ready to watch your screen..."
    )
    open_audacity_with_file()
    localized_agent, bridges = localize_agent(agent_spec, api_key=os.environ["HAI_API_KEY"])
    ensure_bridges(bridges)

    message = UserMessageEvent(message=task_text, images=images or None)
    session = client.sessions.create_session(
        agent=localized_agent, messages=message, max_time_s=400,
    )
    print(f"\nsession: {session.id}")
    print(f"Live view: https://platform.hcompany.ai/agents/sessions/{session.id}")
    print(
        f"While this is running, to pause it and point it somewhere else:\n"
        f'  python steer_session.py {session.id} "look at ... instead"\n'
    )

    terminal = {"completed", "failed", "timed_out", "interrupted", "idle"}
    status = client.sessions.get_session_status(session.id)
    while status.status not in terminal:
        time.sleep(8)
        status = client.sessions.get_session_status(session.id)
        print(f"  ...{status.status} ({status.steps or 0} steps so far)")

    print(f"\nsession: {session.id}  status={status.status}  outcome={status.outcome}")
    if OUTPUT_WAV.exists():
        print(f"Confirmed: {OUTPUT_WAV} exists ({OUTPUT_WAV.stat().st_size} bytes)")
    else:
        print(f"WARNING: {OUTPUT_WAV} not found on disk — check the session for what happened.")
    print(f"Session: https://platform.hcompany.ai/agents/sessions/{session.id}")


if __name__ == "__main__":
    main()
