import logging
import os
import time
import asyncio
from dotenv import load_dotenv
from openai import AsyncOpenAI

load_dotenv(".env.local")

from livekit import agents
from livekit.agents import AgentSession, Agent, JobContext, function_tool
from livekit.plugins import deepgram, openai, rime

os.environ["LIVEKIT_LOG_LEVEL"] = "warn"
for logger in ["livekit", "livekit.agents", "asyncio", "openai", "httpcore", "httpx"]:
    logging.getLogger(logger).setLevel(logging.ERROR)

REPAIR_MANUAL = {
    "spark plug": "Torque spec for the spark plug is 20 newton meters.",
    "check engine light": "To reset the check engine light, disconnect the battery for fifteen seconds, then reconnect it.",
    "oil drain plug": "Torque spec for the oil drain plug is 35 newton meters.",
    "brake bleed valve": "The brake bleed valve should be turned a quarter turn counter-clockwise to release it.",
    "lug nuts": "Torque spec for the wheel lug nuts is 110 newton meters.",
    "tire pressure sensor": (
        "To reset the tire pressure sensor: turn the ignition on with the "
        "engine off, press and hold the T P M S reset button until the "
        "light blinks three times, then start the engine."
    ),
}

_current_turn_id = 0


@function_tool()
async def lookup_repair_spec(ctx, item: str) -> str:
    """Look up a repair spec or reset procedure from the manual."""
    my_turn = _current_turn_id
    for _ in range(3):
        await asyncio.sleep(1.0)
        if my_turn != _current_turn_id:
            print(f"Fenced stale lookup for turn {my_turn}")
            raise asyncio.CancelledError("lookup fenced: turn superseded")

    key = item.lower().strip()
    result = REPAIR_MANUAL.get(key)
    if result is None:
        for k, v in REPAIR_MANUAL.items():
            if k in key or key in k:
                result = v
                break
    return result or f"I don\'t have a spec for {item}."


class Assistant(Agent):
    def __init__(self) -> None:
        super().__init__(
            instructions=(
                "You are EchoAssist, a voice assistant for a field technician "
                "mid-repair. Keep answers very short and direct. If the "
                "technician interrupts you, drop what you were saying and "
                "answer only their new question."
            ),
            tools=[lookup_repair_spec],
        )


async def entrypoint(ctx: JobContext):
    await ctx.connect()

    openrouter_key = os.getenv("OPENROUTER_API_KEY")
    if not openrouter_key:
        raise ValueError("OPENROUTER_API_KEY is missing from .env.local!")

    openrouter_client = AsyncOpenAI(
        api_key=openrouter_key,
        base_url="https://openrouter.ai/api/v1",
        default_headers={
            "HTTP-Referer": "https://echoassist.local",
            "X-Title": "EchoAssist",
        },
    )

    session = AgentSession(
        stt=deepgram.STT(model="nova-3"),
        llm=openai.LLM(
            client=openrouter_client,
            model="openrouter/auto",
            extra_body={"provider": {"sort": "latency"}},
        ),
        tts=rime.TTS(
            model="coda",
            speaker="celeste",
            reduce_latency=True,
            use_websocket=True,
        ),
    )

    timestamps = {"user_speech_end": 0.0, "agent_speech_start": 0.0}

    @session.on("user_input_transcribed")
    def _on_user_speech(ev):
        global _current_turn_id
        if getattr(ev, "is_final", True) and ev.transcript:
            _current_turn_id += 1
            timestamps["user_speech_end"] = time.time()
            print(f"You: {ev.transcript}")

    @session.on("agent_state_changed")
    def _on_state_changed(ev):
        now = time.time()
        if ev.new_state == "speaking" and timestamps["user_speech_end"] > 0:
            latency = now - timestamps["user_speech_end"]
            print(f"[Listening -> Thinking -> Speaking Delay]: {latency:.2f}s")
            timestamps["agent_speech_start"] = now
        elif ev.new_state != "speaking" and timestamps["agent_speech_start"] > 0:
            duration = now - timestamps["agent_speech_start"]
            print(f"[Speaking Duration]: {duration:.2f}s")
            timestamps["agent_speech_start"] = 0.0

    @session.on("conversation_item_added")
    def _on_item_added(ev):
        item = getattr(ev, "item", None)
        if item and getattr(item, "role", None) == "assistant" and item.text_content:
            print(f"EchoAssist: {item.text_content}")

    await session.start(room=ctx.room, agent=Assistant())
    await session.generate_reply(instructions="Say hello briefly.")


if __name__ == "__main__":
    agents.cli.run_app(agents.WorkerOptions(entrypoint_fnc=entrypoint))
