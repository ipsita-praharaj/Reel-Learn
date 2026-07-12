"""
diagnose_session.py — for any session that failed, got interrupted, or that
you manually stopped mid-run: pull its real screenshots and full reasoning
trace in one shot, so it's fast to fold what actually went wrong into
plan_local.json as a new documented failure-mode step (the way steps 6 and 7
were added), instead of re-diagnosing from scratch each time.

Note on alignment: a screenshot's paired context_text is the reasoning that
led to the action producing THAT screenshot — i.e. it describes the state
before the click, not what the click caused. When a policy_event's reasoning
describes something going wrong (a dialog, a wrong app in focus), the
screenshot showing that problem is usually the PRECEDING one in the printed
list, not the one printed alongside that reasoning text.

Usage:
  python diagnose_session.py <session_id> ["<keyword filter>"]

Example:
  python diagnose_session.py 4c39d50c-1d10-4f8f-9d2f-51f6895d390f "no audio selected"
"""

import sys
from pathlib import Path

from extract_screenshots import extract


def main() -> None:
    session_id = sys.argv[1]
    keyword = sys.argv[2].lower() if len(sys.argv) > 2 else None

    out_dir = Path("screenshots") / session_id
    print(f"Pulling screenshots for session {session_id}...")
    shots = extract(session_id, out_dir)
    print(f"Saved {len(shots)} screenshots to {out_dir}/\n")

    for i, s in enumerate(shots):
        if keyword and keyword not in s["context_text"].lower():
            continue
        prior_path = shots[i - 1]["path"] if i > 0 else None
        print(f"[{s['index']}] {s['timestamp']}")
        print(f"  screenshot (state before this reasoning, likely the real frame): {prior_path}")
        print(f"  screenshot (as printed, state after):                            {s['path']}")
        print(f"  reasoning: {s['context_text'][:200]}")
        print()

    if keyword:
        print(f"(filtered to reasoning containing: {keyword!r})")


if __name__ == "__main__":
    main()
