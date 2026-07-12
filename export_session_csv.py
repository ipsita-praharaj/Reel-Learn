"""
Export a session's full trajectory to CSV: every action the agent took,
plus a summary row (steps, clicks, waits, types, screenshots, elapsed time,
outcome) appended to a master summary CSV.

This is the logging mechanism for measuring agent behavior: everything
here comes straight off the sessions.get_session_changes() event stream,
no extra instrumentation needed on the agent side.

Usage:
  python export_session_csv.py <session_id> [<session_id> ...]
"""

import csv
import sys

from hai_agents import Client

client = Client()  # reads HAI_API_KEY

EVENTS_HEADER = [
    "session_id", "step_index", "timestamp", "event_kind",
    "tool_name", "tool_args", "thought_excerpt",
]
SUMMARY_HEADER = [
    "session_id", "status", "outcome", "total_steps", "num_clicks",
    "num_types", "num_waits", "num_navigations", "num_screenshots",
    "elapsed_seconds", "input_tokens", "final_answer_excerpt",
]

CLICK_TOOLS = {"click_web", "click"}
TYPE_TOOLS = {"write", "type"}
WAIT_TOOLS = {"wait_web", "wait_website", "wait"}
NAV_TOOLS = {"go_to_web", "navigate"}


def export_session(session_id: str, events_writer, summary_writer) -> None:
    changes = client.sessions.get_session_changes(session_id, from_index=0)
    session = client.sessions.get_session(session_id)
    status = client.sessions.get_session_status(session_id)

    num_clicks = num_types = num_waits = num_navs = num_screens = 0
    step_index = 0

    for e in changes.new_events:
        d = e.data
        kind = getattr(d, "kind", None)
        ts = e.timestamp.isoformat()

        if kind == "observation_event":
            num_screens += 1
            events_writer.writerow([session_id, step_index, ts, kind, "", "", ""])

        elif kind == "policy_event":
            step_index += 1
            tr = d.tool_reqs[0] if d.tool_reqs else None
            tool_name = tr.tool_name if tr else ""
            tool_args = str(tr.args) if tr else ""
            thought = (d.reasoning_content or "")[:200].replace("\n", " ")

            if tool_name in CLICK_TOOLS:
                num_clicks += 1
            elif tool_name in TYPE_TOOLS:
                num_types += 1
            elif tool_name in WAIT_TOOLS:
                num_waits += 1
            elif tool_name in NAV_TOOLS:
                num_navs += 1

            events_writer.writerow([session_id, step_index, ts, kind, tool_name, tool_args, thought])

    input_tokens = 0
    if status.usage_per_model:
        input_tokens = sum(u.input_tokens or 0 for u in status.usage_per_model)

    elapsed = None
    if session.started_at and session.finished_at:
        elapsed = (session.finished_at - session.started_at).total_seconds()

    answer = ""
    if changes.answer is not None:
        answer = str(changes.answer)[:200].replace("\n", " ")

    summary_writer.writerow([
        session_id, status.status, status.outcome, status.steps,
        num_clicks, num_types, num_waits, num_navs, num_screens,
        elapsed, input_tokens, answer,
    ])
    print(f"{session_id}: {status.steps} steps, {num_clicks} clicks, {num_screens} screenshots, "
          f"{elapsed}s, status={status.status}")


def main() -> None:
    session_ids = sys.argv[1:]
    with open("sessions_events.csv", "w", newline="") as ef, \
         open("sessions_summary.csv", "w", newline="") as sf:
        events_writer = csv.writer(ef)
        summary_writer = csv.writer(sf)
        events_writer.writerow(EVENTS_HEADER)
        summary_writer.writerow(SUMMARY_HEADER)
        for sid in session_ids:
            export_session(sid, events_writer, summary_writer)
    print("\nWrote sessions_events.csv and sessions_summary.csv")


if __name__ == "__main__":
    main()
