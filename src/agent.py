import logging
import os
import time
from dotenv import load_dotenv
from openai import AsyncOpenAI

load_dotenv(".env.local")

from livekit import agents
from livekit.agents import AgentSession, Agent, JobContext
from livekit.plugins import deepgram, openai, rime

os.environ["LIVEKIT_LOG_LEVEL"] = "warn"
for logger in ["livekit", "livekit.agents", "asyncio", "openai", "httpcore", "httpx"]:
    logging.getLogger(logger).setLevel(logging.ERROR)

class Assistant(Agent):
    def __init__(self) -> None:
        super().__init__(
            instructions=(
                "You are EchoAssist, a fast, concise voice assistant. "
                "Keep answers very short, direct, and conversational."
            )
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
            extra_body={
                "provider": {
                    "sort": "latency"
                }
            },
        ),
        tts=rime.TTS(
            model="coda",
            speaker="celeste",
            reduce_latency=True,
            use_websocket=True,
        ),
    )

    timestamps = {
        "user_speech_end": 0.0,
        "agent_speech_start": 0.0,
    }

    @session.on("user_input_transcribed")
    def _on_user_speech(ev):
        if getattr(ev, "is_final", True) and ev.transcript:
            timestamps["user_speech_end"] = time.time()
            print(f"\n🗣️ You: {ev.transcript}")

    @session.on("agent_state_changed")
    def _on_state_changed(ev):
        now = time.time()
        if ev.new_state == "speaking" and timestamps["user_speech_end"] > 0:
            latency = now - timestamps["user_speech_end"]
            print(f"⏱️ [Listening → Thinking → Speaking Delay]: {latency:.2f}s")
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