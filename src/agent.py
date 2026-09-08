import asyncio
import logging
import os
import re
import time
from dotenv import load_dotenv
from openai import AsyncOpenAI

load_dotenv(".env.local")

from livekit import agents
from livekit.agents import (
    AgentSession,
    Agent,
    JobContext,
    function_tool,
    RunContext,
    InterruptionOptions,
    TurnHandlingOptions,
    EndpointingOptions,
)
from livekit.plugins import deepgram, openai, rime

# Suppress background logging clutter
os.environ["LIVEKIT_LOG_LEVEL"] = "warn"
for logger_name in ["livekit", "livekit.agents", "asyncio", "openai", "httpcore", "httpx"]:
    logging.getLogger(logger_name).setLevel(logging.ERROR)


# ============================================================================
# TURN TRACKER ENGINE
# ============================================================================
class TurnTracker:
    def __init__(self):
        self.current_turn_id = 0
        self.fenced_turns = set()

    def new_turn(self) -> int:
        self.current_turn_id += 1
        return self.current_turn_id

    def is_stale(self, turn_id: int) -> bool:
        return turn_id != self.current_turn_id

    def fence_turn(self, turn_id: int):
        if turn_id == 0:
            return
        if turn_id not in self.fenced_turns:
            self.fenced_turns.add(turn_id)
            print(f" [Turn {turn_id}] Task stale due to interruption! Fencing result.")


turn_tracker = TurnTracker()

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
# AGENT PERSONA & TOOL DEFINITION
# ============================================================================
class Assistant(Agent):
    def __init__(self) -> None:
        super().__init__(
            instructions=(
                "You are EchoAssist, an expert voice assistant for bikes, motorcycles, cars, and all types of vehicles.\n\n"
                "PRIMARY SCOPE & CAPABILITIES:\n"
                "- Answer ANY question related to bikes, motorcycles, cars, and general automobiles dynamically using your vast mechanics knowledge.\n"
                "- Cover repair procedures, troubleshooting, parts, specifications, models, brands, history, and maintenance.\n"
                "- Do NOT rely on pre-written responses; use your complete AI knowledge base for all user queries.\n\n"
                "CRITICAL VOICE & SPEECH SYNTHESIS RULES:\n"
                "- Output ONLY raw spoken dialogue. Never output XML/HTML tags, parameter blocks, or thinking text.\n"
                "- ALWAYS spell out all numbers in full words (e.g. write 'forty-five' NOT '45', 'five' NOT '5').\n"
                "- When a tool returns a spec or procedure, relay that exact wording verbatim -- do NOT paraphrase or reformat numbers.\n"
                "- Keep spoken answers clear, practical, direct, and under fifteen words.\n\n"
                "TOOL USAGE RULES:\n"
                "- Call `lookup_repair_spec` ONLY when asked for factory manual specs, main bolt torque, or factory reset procedures.\n"
                "- For all other questions about bikes, cars, or vehicles, answer directly using your knowledge base.\n\n"
                "INTERRUPTION RULE:\n"
                "- If the user interrupts you or says 'never mind' before you finish answering, treat that question as abandoned.\n"
                "- Answer ONLY the user's newest question. Do not circle back and answer an abandoned question later unless the user asks it again."
            )
        )

    @function_tool(description="Look up official factory repair specifications or reset procedures in the manual database.")
    async def lookup_repair_spec(self, context: RunContext, query_key: str) -> str:
        active_turn = turn_tracker.current_turn_id

        if active_turn == 0:
            raise asyncio.CancelledError("Rejected pre-turn-0 tool call.")

        print(f"🔍 [Turn {active_turn}] Tool called for: '{query_key}'")

        try:
            await asyncio.sleep(5.0)
        except asyncio.CancelledError:
            turn_tracker.fence_turn(active_turn)
            raise

        if turn_tracker.is_stale(active_turn):
            turn_tracker.fence_turn(active_turn)
            raise asyncio.CancelledError(f"Turn {active_turn} cancelled due to user barge-in.")

        key_lower = query_key.lower().replace("_", " ")
        if any(w in key_lower for w in ["reset", "procedure", "factory", "system"]):
            result = REPAIR_MANUAL["reset_procedure"]
        elif any(w in key_lower for w in ["torque", "bolt", "pole", "spec", "board"]):
            result = REPAIR_MANUAL["torque_spec"]
        else:
            result = "Specification entry not found in manual. Relying on general automotive knowledge."

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
    
    session = AgentSession(
        stt=deepgram.STT(
            model="nova-3",
            interim_results=True,
            smart_format=True,
            keyterm=[
                "bolts",
                "torque",
                "reset",
                "handlebar",
                "headlight",
                "brakes",
                "taillight",
                "procedure",
            ],
            endpointing_ms=500,
            utterance_end_ms=1000,
        ),
        llm=openai.LLM(
            model="openai/gpt-oss-120b", 
            api_key=groq_key,
            base_url="https://api.groq.com/openai/v1"
        ),
        tts=rime.TTS(
            model="arcana",
            speaker="celeste",
            reduce_latency=True,
            use_websocket=True,
        ),
        turn_handling=TurnHandlingOptions(
            interruption=InterruptionOptions(min_duration=0.2, min_words=0),
            endpointing=EndpointingOptions(mode="fixed", min_delay=0.5, max_delay=1.5   ),
            preemptive_generation={
                "enabled": True,
                "preemptive_tts": True,         
                "max_speech_duration": 10.0,    
            }
        ),
    )

    timestamps = {"user_speech_end": 0.0, "agent_speech_start": 0.0}

    @session.on("speech_created")
    def _on_speech_created(ev):
        def _on_speech_done(handle):
            turn_now = turn_tracker.current_turn_id
            was_interrupted = getattr(handle, "interrupted", False)

            if was_interrupted:
                if turn_now > 0:
                    turn_tracker.fence_turn(turn_now)

                for chat_item in handle.chat_items:
                    try:
                        session.history.remove(chat_item)
                    except Exception:
                        pass
                return

            for chat_item in handle.chat_items:
                if getattr(chat_item, "role", None) != "assistant":
                    continue
                text = getattr(chat_item, "text_content", None)
                if not text:
                    continue
                clean_text = BLOCK_TAG_PATTERN.sub("", text)
                clean_text = ORPHAN_TAG_PATTERN.sub("", clean_text).strip()
                if clean_text:
                    print(f" EchoAssist: {clean_text}")

        ev.speech_handle.add_done_callback(_on_speech_done)

    @session.on("agent_state_changed")
    def _on_state_changed(ev):
        now = time.time()
        if ev.new_state == "speaking" and timestamps["user_speech_end"] > 0:
            latency = now - timestamps["user_speech_end"]
            print(f" [Listening → Speaking Latency]: {latency:.2f}s")
            timestamps["agent_speech_start"] = now
        elif ev.new_state != "speaking" and timestamps["agent_speech_start"] > 0:
            duration = now - timestamps["agent_speech_start"]
            print(f" [Speaking Duration]: {duration:.2f}s\n")
            timestamps["agent_speech_start"] = 0.0

    @session.on("conversation_item_added")
    def _on_item_added(ev):
        item = getattr(ev, "item", None)
        text_content = getattr(item, "text_content", None) if item is not None else None
        if not text_content:
            return

        if getattr(item, "role", None) == "user":
            active_turn = turn_tracker.new_turn()
            timestamps["user_speech_end"] = time.time()
            print(f"\n [Turn {active_turn}] You: {text_content}")

    await session.start(room=ctx.room, agent=Assistant())


if __name__ == "__main__":
    agents.cli.run_app(agents.WorkerOptions(entrypoint_fnc=entrypoint))