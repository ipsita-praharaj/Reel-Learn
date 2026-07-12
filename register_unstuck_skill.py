"""
register_unstuck_skill.py — creates (or updates) the `no-progress-guard` skill
and attaches it to hard-traj-desktop-flash, so the stuck-loop pattern found in
findings.md (session d000f506: ~40 near-identical clicks on "Rename...", never
self-detected) has a concrete, reusable countermeasure instead of living only
as a writeup.

Idempotent: reuses the create-or-update-on-409 pattern from watch_and_plan.py.

Usage:
  python register_unstuck_skill.py [agent_name]   # default: hard-traj-desktop-flash
"""

import sys

from hai_agents import Client
from hai_agents.core.api_error import ApiError

SKILL_NAME = "no-progress-guard"
SKILL_DESCRIPTION = (
    "Detects an interaction-level stuck loop (same gesture, unchanged screen) and forces a "
    "strategy switch or an honest 'blocked' instead of repeating it."
)

SKILL_BODY = """\
Repeated action on an unchanged screen is a stronger signal than any instruction's wording, \
and treating it that way is the whole point of this skill. Track the last four actions in the \
trajectory: if they share the same tool, their targets (coordinates or the described element) \
land within roughly 2% of screen width/height of each other, and the observation that followed \
each one is materially indistinguishable from the one before it, the guard fires — regardless \
of how confident the reasoning was that this attempt would be different. That 2% tolerance and \
four-action window is not arbitrary: it is the literal measurement (repeat_action_rate) that \
found the session where an agent clicked inside a 3%x1.5% box ~40 times trying to open a Rename \
dialog that never opened, without ever varying its strategy. A rate near 1 over that window means \
the same gesture is being restated, not retried. A rate near 0, even across many actions on the \
same element — a calculator's digit buttons, a slider nudged in small steps — means each attempt \
is producing a genuinely different, visible outcome, and is not stuck.

A textual match between an instruction and the visible UI ("click Rename in the Document \
submenu") is a hint about where to look, not a guarantee the click will register. It is not \
stronger evidence than twenty consecutive failures of that exact action. Once the guard fires, \
repeated failure outweighs the instruction's own wording: the instructed path has already shown, \
empirically, that it does not work here, however well it matches the description. Anchoring on \
phrasing after the evidence has turned against it is the specific failure this skill exists to \
stop.

Once fired, never issue the same gesture a fifth time. Switch to a structurally different \
interaction: keyboard navigation instead of a mouse click, a double-click instead of a single \
one, scrolling before clicking, hovering to reveal a different hit target, or re-locating the \
element from the latest screenshot rather than a remembered position — coordinates do not \
survive a reflow or re-render, so re-find the target by its visible text and neighbors, not by \
replaying the same x/y with a small jitter. If a checkpoint plan is attached to the task (an \
ordered list of milestone/instruction/verify/irreversible steps distilled by watching a tutorial \
video), re-anchor on that milestone's verify condition, not its instruction text: the instruction \
describes one demonstrated path to the outcome, not the only path, and the demonstration's exact \
menu wording, coordinates, or app version may not match this build or window size. If two \
structurally different attempts both fail to satisfy the verify condition, stop and self-report \
"blocked" honestly — the same way an environment-level wall (a login screen, a bot check) is \
already reported cleanly within 2-3 steps. An unacknowledged interaction-level stall is worse \
than an honest one: it keeps resending the accumulating screenshot and reasoning history every \
step, so cost grows with every additional wasted retry.

The loop guard never authorizes an irreversible action (marked irreversible: true in a plan, or \
anything that saves, sends, publishes, or deletes) as one of its "structurally different \
attempts" — a fresh approach still has to be one that is safe to undo if it also fails.
"""

client = Client()


def ensure_skill() -> None:
    try:
        client.skills.create_skill(
            name=SKILL_NAME, description=SKILL_DESCRIPTION, body=SKILL_BODY,
        )
        print(f"Created skill: {SKILL_NAME}")
    except ApiError as e:
        if e.status_code == 409:
            client.skills.update_skill(
                SKILL_NAME, name=SKILL_NAME, description=SKILL_DESCRIPTION, body=SKILL_BODY,
            )
            print(f"Updated existing skill: {SKILL_NAME}")
        else:
            raise


def attach_to_agent(agent_name: str) -> None:
    agent = client.agents.get_agent(agent_name)
    existing = list(agent.skills or [])
    existing_names = {s if isinstance(s, str) else s.name for s in existing}
    if SKILL_NAME in existing_names:
        print(f"{agent_name} already has {SKILL_NAME}; nothing to patch.")
        return
    new_skills = existing + [SKILL_NAME]
    client.agents.patch_agent(agent_name, skills=new_skills)
    print(f"Patched {agent_name}: skills={new_skills}")


def main() -> None:
    agent_name = sys.argv[1] if len(sys.argv) > 1 else "hard-traj-desktop-flash"
    ensure_skill()
    attach_to_agent(agent_name)


if __name__ == "__main__":
    main()
