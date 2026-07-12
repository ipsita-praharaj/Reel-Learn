"""
score_hardness.py — turns raw session telemetry into a hardness number.

Reads ONLY local CSVs (the ones export_session_csv.py already writes).
Makes no API calls, starts no agent sessions, costs nothing to run.

This is the actual logic behind "how do we decide a task is hard,"
not a description of it — every function here is what will run against
the 14-task pilot once it's approved to execute.

Usage:
  python score_hardness.py <summary_csv> <events_csv> [session_id ...]
  (if no session_ids given, scores every session in the summary CSV)
"""

import ast
import csv
import sys


def load_summary(summary_csv: str) -> list[dict]:
    with open(summary_csv, newline="") as f:
        return list(csv.DictReader(f))


def load_events(events_csv: str, session_id: str) -> list[dict]:
    with open(events_csv, newline="") as f:
        rows = [r for r in csv.DictReader(f) if r["session_id"] == session_id]
    return [r for r in rows if r["tool_name"]]  # drop observation_event rows, keep policy_events


def repeat_action_rate(action_rows: list[dict], coord_tolerance: float = 0.02) -> float:
    """
    Fraction of consecutive same-tool actions whose click coordinates land
    within `coord_tolerance` (as a fraction of screen width/height) of the
    previous one.

    This is a direct, literal encoding of Finding 1 in findings.md: the
    d000f506 session spent ~40 actions clicking inside a box roughly
    3% wide x 1.5% tall on "Rename..." without ever varying strategy.
    A rate near 0 = the agent kept trying genuinely different things.
    A rate near 1 = the agent got stuck nudging pixels.
    """
    if len(action_rows) < 2:
        return 0.0
    repeats = 0
    pairs = 0
    for prev, cur in zip(action_rows, action_rows[1:]):
        if prev["tool_name"] != cur["tool_name"]:
            continue
        try:
            pa = ast.literal_eval(prev["tool_args"])
            ca = ast.literal_eval(cur["tool_args"])
            px, py = pa.get("x"), pa.get("y")
            cx, cy = ca.get("x"), ca.get("y")
            if None in (px, py, cx, cy):
                continue
        except (ValueError, SyntaxError):
            continue
        pairs += 1
        if abs(px - cx) <= coord_tolerance and abs(py - cy) <= coord_tolerance:
            repeats += 1
    return repeats / pairs if pairs else 0.0


def percentile_rank(value: float, population: list[float]) -> float:
    """Fraction of the population strictly below `value`. 1.0 = worst in the pool."""
    if len(population) <= 1:
        return 0.0
    below = sum(1 for v in population if v < value)
    return below / (len(population) - 1)


def gate(flash_row: dict, pro_row: dict | None) -> bool:
    """
    Hard-not-impossible gate: a task only counts as a genuine hard
    trajectory (not a broken/impossible one) if the baseline (flash)
    failed or was interrupted, AND the stronger sibling model (pro)
    completed it. If pro also fails, the task might just be broken —
    that's a data quality problem, not a baseline weakness.
    """
    flash_failed = flash_row["status"] != "completed" or flash_row["outcome"] in (
        "", "partial", "blocked",
    )
    pro_succeeded = pro_row is not None and pro_row["status"] == "completed" and pro_row["outcome"] not in (
        "", "partial", "blocked",
    )
    return flash_failed and pro_succeeded


def severity(session_id: str, summary_rows: list[dict], events_csv: str) -> dict:
    row = next(r for r in summary_rows if r["session_id"] == session_id)
    action_rows = load_events(events_csv, session_id)
    rar = repeat_action_rate(action_rows)

    steps_pop = [float(r["total_steps"]) for r in summary_rows]
    tokens_pop = [float(r["input_tokens"]) for r in summary_rows]
    elapsed_pop = [float(r["elapsed_seconds"] or 0) for r in summary_rows]

    steps_pct = percentile_rank(float(row["total_steps"]), steps_pop)
    tokens_pct = percentile_rank(float(row["input_tokens"]), tokens_pop)
    elapsed_pct = percentile_rank(float(row["elapsed_seconds"] or 0), elapsed_pop)

    return {
        "session_id": session_id,
        "status": row["status"],
        "outcome": row["outcome"] or "(none)",
        "total_steps": row["total_steps"],
        "repeat_action_rate": round(rar, 3),
        "steps_percentile": round(steps_pct, 3),
        "tokens_percentile": round(tokens_pct, 3),
        "elapsed_percentile": round(elapsed_pct, 3),
        "severity_score": round((steps_pct + tokens_pct + elapsed_pct + rar) / 4, 3),
    }


def main() -> None:
    summary_csv, events_csv = sys.argv[1], sys.argv[2]
    summary_rows = load_summary(summary_csv)
    session_ids = sys.argv[3:] or [r["session_id"] for r in summary_rows]

    print(f"{'session_id':<38} {'status':<12} {'outcome':<10} {'steps':>6} "
          f"{'repeat%':>8} {'severity':>9}")
    for sid in session_ids:
        s = severity(sid, summary_rows, events_csv)
        print(f"{s['session_id']:<38} {s['status']:<12} {s['outcome']:<10} "
              f"{s['total_steps']:>6} {s['repeat_action_rate']*100:>7.1f}% "
              f"{s['severity_score']:>9.3f}")


if __name__ == "__main__":
    main()
