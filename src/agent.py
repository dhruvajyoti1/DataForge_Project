import logging
import os
import re
import time
import asyncio
from dotenv import load_dotenv
from openai import AsyncOpenAI

load_dotenv(".env.local")

from livekit import agents
from livekit.agents import AgentSession, Agent, JobContext, function_tool, RunContext
from livekit.plugins import deepgram, openai, rime

# Suppress background logging clutter
os.environ["LIVEKIT_LOG_LEVEL"] = "warn"
for logger_name in ["livekit", "livekit.agents", "asyncio", "openai", "httpcore", "httpx"]:
    logging.getLogger(logger_name).setLevel(logging.ERROR)


# ============================================================================
# TURN TRACKER — your Day 3 fencing logic (kept, this part was already good)
# ============================================================================
class TurnTracker:
    def __init__(self):
        self.current_turn_id = 0

    def new_turn(self) -> int:
        self.current_turn_id += 1
        return self.current_turn_id

    def is_stale(self, turn_id: int) -> bool:
        return turn_id != self.current_turn_id


turn_tracker = TurnTracker()

# Mock database entry strictly for official manual spec lookups
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

BLOCK_TAG_PATTERN = re.compile(r"<([a-zA-Z_][a-zA-Z0-9_]*)>.*?</\1>", re.DOTALL)
ORPHAN_TAG_PATTERN = re.compile(r"</?[a-zA-Z_][a-zA-Z0-9_]*\s*/?>")


# ============================================================================
# AGENT — tool now lives directly on the Agent class (this is the fix)
# ============================================================================
class Assistant(Agent):
    def __init__(self) -> None:
        super().__init__(
            instructions=(
                "You are EchoAssist, a fast field technician voice assistant. "
                "CRITICAL RULES FOR SPEECH SYNTHESIS:\n"
                "1. Always spell out numbers in words (e.g. write 'forty-five' NOT '45').\n"
                "2. Keep answers direct, simple, and under fifteen words.\n"
                "3. Use tool calls whenever asked for repair specs or reset procedures."
            )
        )

    @function_tool(description="Look up repair specifications or reset procedures in the manual.")
    async def lookup_repair_spec(self, context: RunContext, query_key: str) -> str:
        active_turn = turn_tracker.current_turn_id
        print(f"🔍 [Turn {active_turn}] Tool called for: {query_key}")

        await asyncio.sleep(2.5)  # artificial delay window for barge-in testing

        if turn_tracker.is_stale(active_turn):
            print(f"⚠️ [Turn {active_turn}] Task stale due to interruption! Fencing result.")
            raise asyncio.CancelledError(f"Turn {active_turn} cancelled.")

        result = REPAIR_MANUAL.get(query_key, "Specification not found in manual.")
        print(f"✅ [Turn {active_turn}] Tool finished: {result}")
        return result


# ============================================================================
# ENTRYPOINT & SESSION ORCHESTRATION
# ============================================================================
async def entrypoint(ctx: JobContext):
    await ctx.connect()

    groq_key = os.getenv("GROQ_API_KEY")
    if not groq_key:
        raise ValueError("GROQ_API_KEY is missing from .env.local!")

    # REMOVE the separate groq_client = AsyncOpenAI(...) block entirely.
    
    session = AgentSession(
        stt=deepgram.STT(model="nova-3", interim_results=True),
        llm=openai.LLM(
            client=openrouter_client,
            model="openrouter/auto",
            # extra_body={"provider": {"sort": "latency"}},
        ),
        tts=rime.TTS(
            model="coda",
            speaker="celeste",
            reduce_latency=True,
            use_websocket=True,
        ),
        turn_handling=TurnHandlingOptions(
            interruption=InterruptionOptions(min_duration=0.2, min_words=0),
            endpointing=EndpointingOptions(mode="fixed", min_delay=0.5, max_delay=1.5   ),
            # --- THIS ENABLES REAL-TIME PREEMPTIVE STREAMING ---
            preemptive_generation={
                "enabled": True,
                "preemptive_tts": True,         # Starts audio generation before turn confirmation
                "max_speech_duration": 10.0,    # Skips preemptive triggering if utterance is too long
            }
        ),
    )
    
    # ... rest of your code remains exactly the same ...

    timestamps = {"user_speech_end": 0.0, "agent_speech_start": 0.0}

    @session.on("user_input_transcribed")
    def _on_user_speech(ev):
        if getattr(ev, "is_final", True) and ev.transcript:
            active_turn = turn_tracker.new_turn()
            timestamps["user_speech_end"] = time.time()
            print(f"\n🗣️ [Turn {active_turn}] You: {ev.transcript}")

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
            print(f"🤖 EchoAssist: {item.text_content}")

    await session.start(room=ctx.room, agent=Assistant())


if __name__ == "__main__":
    agents.cli.run_app(agents.WorkerOptions(entrypoint_fnc=entrypoint))