import asyncio
import logging
import os
import time
from dotenv import load_dotenv
from openai import AsyncOpenAI

load_dotenv(".env.local")

from livekit import agents
from livekit.agents import AgentSession, Agent, JobContext, function_tool, RunContext
from livekit.plugins import deepgram, openai, rime

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

REPAIR_MANUAL = {
    "torque_spec": "forty-five Newton meters for main bolts.",
    "reset_procedure": "Hold reset button for five seconds until green light flashes.",
}


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
        stt=deepgram.STT(model="nova-3", interim_results=True),
        llm=openai.LLM(
            client=openrouter_client,
            model="openrouter/auto",
            # extra_body={"provider": {"sort": "latency"}},
        ),
        tts=rime.TTS(
            model="arcana",
            speaker="celeste",
            reduce_latency=True,
            use_websocket=True,
        ),
    )

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
            print(f"⏱️ [Listening → Speaking Latency]: {latency:.2f}s")
            timestamps["agent_speech_start"] = now
        elif ev.new_state != "speaking" and timestamps["agent_speech_start"] > 0:
            duration = now - timestamps["agent_speech_start"]
            print(f"⏱️ [Speaking Duration]: {duration:.2f}s\n")
            timestamps["agent_speech_start"] = 0.0

    @session.on("conversation_item_added")
    def _on_item_added(ev):
        item = getattr(ev, "item", None)
        if item and getattr(item, "role", None) == "assistant" and item.text_content:
            print(f"🤖 EchoAssist: {item.text_content}")

    await session.start(room=ctx.room, agent=Assistant())
    await session.generate_reply(instructions="Say hello briefly.")


if __name__ == "__main__":
    agents.cli.run_app(agents.WorkerOptions(entrypoint_fnc=entrypoint))