"""
Demo: use hai-agents (computer-use web agent) and gradium (text-to-speech)
together.

Flow:
  1. hai-agents drives your actual local browser (not a cloud sandbox) via an
     inline agent + local bridge, does the research task, and returns a text
     answer. Watch your screen while it runs.
  2. gradium turns that answer into a spoken .wav file.

Requires:
  - HAI_API_KEY      (set via `hai login`, already stored in ~/.config/hai/.env)
  - GRADIUM_API_KEY  (from https://platform.gradium.ai, export it yourself)
  - hai-agents[browser] extra (`pip install 'hai-agents[browser]'`) for local
    browser control — same requirement local desktop control has for [desktop]
"""

import asyncio
import os

import gradium
from hai_agents import AsyncClient
from hai_agents.types import Agent, Environment_Web
from hai_agents_local import ensure_bridges
from hai_agents_local.routing import localize_agent


async def research(question: str) -> str:
    """Run a computer-use agent, driving your actual local browser, and return its final text answer."""
    agent_spec = Agent(
        name="local-web-surfer",
        description="Local counterpart to h/web-surfer-flash, drives the user's own browser.",
        environments=[Environment_Web(id="local-browser", host="user_device")],
        model="holo3-1-35b-a3b",
    )
    localized_agent, bridges = localize_agent(agent_spec, api_key=os.environ["HAI_API_KEY"])
    ensure_bridges(bridges)  # starts the local browser bridge in this process

    hai = AsyncClient()  # reads HAI_API_KEY from the environment
    result = await hai.run_session(
        agent=localized_agent,
        messages=question,
    )
    return result.final_changes.answer


async def speak(text: str, out_path: str = "answer.wav") -> None:
    """Turn text into speech and save it as a .wav file."""
    tts = gradium.client.GradiumClient()  # reads GRADIUM_API_KEY from the environment
    result = await tts.tts(
        setup={"voice_id": "YTpq7expH9539ERJ", "output_format": "wav"},
        text=text,
    )
    with open(out_path, "wb") as f:
        f.write(result.raw_data)


async def main() -> None:
    question = (
        "On Google Flights, find the cheapest direct flight from Paris (CDG) "
        "to Tokyo (NRT) this Saturday. Return the airline and the price."
    )
    answer = await research(question)
    print("Agent answer:", answer)

    await speak(answer)
    print("Saved spoken answer to answer.wav")


if __name__ == "__main__":
    asyncio.run(main())
