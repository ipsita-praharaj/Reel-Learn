"""
extract_screenshots.py — pulls the actual screenshots a video-watcher session
looked at (ObservationEvent.image, per observation) and saves them as local
files, then enriches a plan.json/plan_local.json in place by attaching the
best-matching local screenshot path to each distilled step.

This is the missing link between "the plan describes 8 steps in text" and
"here's what the agent actually saw when it wrote each one" — useful both for
a human sanity-checking the plan, and for re-injecting real pixels (not just
a path) into a downstream agent call, which plan_to_messages() below does.

Usage:
  python extract_screenshots.py plan.json
  python extract_screenshots.py plan_local.json
"""

import base64
import json
import os
import re
import sys
from pathlib import Path

import httpx

from hai_agents import Client
from hai_agents.types import UserMessageEvent

STOPWORDS = {
    "the", "a", "an", "to", "in", "on", "of", "and", "or", "is", "this", "that",
    "with", "for", "at", "click", "then", "you", "your", "it", "be", "as",
}


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]+", text.lower()) if w not in STOPWORDS and len(w) > 2}


client = Client()


def extract(session_id: str, out_dir: Path) -> list[dict]:
    """Save every screenshot in the session to out_dir, in order, paired with
    the reasoning text immediately before/after it for later correlation."""
    out_dir.mkdir(parents=True, exist_ok=True)
    changes = client.sessions.get_session_changes(session_id, from_index=0)

    shots = []
    last_reasoning = ""
    idx = 0
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
                    raw = img.source.split(",")[-1]  # strip a data: prefix if present
                    fname.write_bytes(base64.b64decode(raw))
                else:  # "url" — presigned/redirecting URLs, must follow
                    resp = httpx.get(
                        img.source,
                        headers={"Authorization": f"Bearer {os.environ['HAI_API_KEY']}"},
                        follow_redirects=True,
                    )
                    resp.raise_for_status()
                    fname.write_bytes(resp.content)
            except Exception as exc:
                print(f"  skip obs_{idx:03d}: {exc}")
                continue
            shots.append({
                "index": idx,
                "path": str(fname),
                "timestamp": e.timestamp.isoformat(),
                "context_text": last_reasoning,
            })
    return shots


def correlate(plan: dict, shots: list[dict]) -> None:
    """Attach the best-matching screenshot(s) to each plan step by keyword
    overlap between the step's milestone/instruction and each shot's nearby
    reasoning text; falls back to even chronological spread if nothing matches."""
    steps = plan["steps"]
    step_words = [_words(s["milestone"] + " " + s["instruction"]) for s in steps]

    for s in steps:
        s["screenshots"] = []

    matched_any = False
    for shot in shots:
        shot_words = _words(shot["context_text"])
        scores = [len(sw & shot_words) for sw in step_words]
        best = max(range(len(steps)), key=lambda i: scores[i]) if scores else None
        if best is not None and scores[best] > 0:
            steps[best]["screenshots"].append(shot["path"])
            matched_any = True

    if not matched_any:  # fallback: spread screenshots evenly across steps in order
        for i, shot in enumerate(shots):
            steps[i * len(steps) // max(len(shots), 1)]["screenshots"].append(shot["path"])

    for s in steps:
        s["screenshot"] = s["screenshots"][0] if s["screenshots"] else None


def plan_to_messages(plan: dict, text: str) -> UserMessageEvent:
    """Build a real multimodal message for a downstream run_session() call:
    the plan's text plus the actual screenshot bytes (as base64 data URIs),
    not just dangling file paths the next model can't open."""
    images = []
    for s in plan["steps"]:
        for p in s.get("screenshots", []):
            path = Path(p)
            if not path.exists():
                continue
            mime = "image/png" if path.suffix == ".png" else "image/jpeg"
            b64 = base64.b64encode(path.read_bytes()).decode()
            images.append(f"data:{mime};base64,{b64}")
    return UserMessageEvent(message=text, images=images or None)


def main() -> None:
    plan_path = Path(sys.argv[1])
    plan = json.loads(plan_path.read_text())
    session_id = plan["session_id"]
    out_dir = Path("screenshots") / session_id

    print(f"Pulling screenshots from session {session_id}...")
    shots = extract(session_id, out_dir)
    print(f"Saved {len(shots)} screenshots to {out_dir}/")

    correlate(plan, shots)
    plan_path.write_text(json.dumps(plan, indent=2))
    print(f"Enriched {plan_path} with per-step screenshot paths")


if __name__ == "__main__":
    main()
