# EchoAssist — Interruption & Recovery for a Field Technician's Voice Assistant

**Track:** DataForge x Rime Hackathon — Hard voice problem: Interruption and recovery.

## The claim

> When a technician interrupts EchoAssist mid-lookup to ask something new, the assistant stops speaking within one turn, discards the stale in-flight lookup result, and its final spoken response reflects only the technician's latest request — never a blend of the old and new answers.

See `RIME_EVIDENCE.md` for the acceptance test, procedure, and results.

## Who this is for

A field technician who is mid-repair, hands busy with tools, and needs to ask quick questions out loud — torque specs, reset procedures, next steps — without stopping work to look at a screen. For this user, voice isn't a convenience, it's the only practical interface, and being unable to cleanly interrupt and redirect the assistant (e.g. "never mind, ask something else instead") is a real barrier to getting the job done safely and quickly.

## Architecture

- **Transport & Orchestration:** LiveKit Agents (`AgentSession`) — handles audio transport, VAD, turn detection, and built-in interruption triggers.
- **Speech Recognition (STT):** Deepgram — configured for low-latency streaming speech-to-text.
- **Reasoning & Intelligence (LLM):** OpenRouter — routed with punctuality-enforced prompting for sentence-by-sentence streaming responses.
- **Speech Synthesis (TTS):** Rime, via `livekit-plugins-rime`, streamed over WebSocket (`use_websocket=True`) for low latency and word-level timestamps. Model: `arcana`, speaker: `celeste`.
- **Interruption/Recovery Layer (`src/agent.py`):**
  - `SessionState` / `TurnLog`: Tags every tool call and reply with the turn ID it belongs to.
  - `is_stale()`: Checked before any tool result is returned/spoken; if the user has moved on to a new turn, the stale result is fenced (raised as `CancelledError`) instead of being spoken.
  - Event handlers on `user_state_changed` and `conversation_item_added` log exactly when an interruption happened and what was cut, generating the evidence trail used in `RIME_EVIDENCE.md`.

## What's live vs. simulated

- **Live:** The full LiveKit + Deepgram + OpenRouter + Rime voice pipeline, real interruption detection, and real-time TTS audio streaming.
- **Simulated:** `lookup_repair_spec` searches a small in-memory `REPAIR_MANUAL` dictionary with an artificial `asyncio.sleep()` standing in for a real database lookup. This creates a reliable timing window to demonstrate mid-lookup interruptions clearly.

## Setup & Running Locally

### Prerequisites
- [uv](https://github.com/astral-sh/uv) installed on your system.

### Installation

```bash
# Clone the repository
git clone https://github.com/dhruvajyoti1/DataForge_Project.git
cd DataForge_Project

# Sync dependencies using uv
uv sync

# Create your local environment configuration
cp .env.example .env.local
```

### Environment Variables

Fill in your API keys in `.env.local` (never commit this file):

```
LIVEKIT_URL=wss://your-project.livekit.cloud
LIVEKIT_API_KEY=your_livekit_api_key
LIVEKIT_API_SECRET=your_livekit_api_secret
DEEPGRAM_API_KEY=your_deepgram_api_key
OPENROUTER_API_KEY=your_openrouter_api_key
RIME_API_KEY=your_rime_api_key
```

### Running the Agent

```bash
# Run locally in console mode
uv run python src/agent.py console

# Run in development mode
uv run python src/agent.py dev
```

### Running with Docker

Alternatively, build and run using Docker:

```bash
# Build the Docker image
docker build -t echo-assist .

# Run the container with your environment variables
docker run --rm --env-file .env.local echo-assist
```

## Known Limitations

See `RIME_EVIDENCE.md` for details on an upstream LiveKit Agents framework issue around tool-result handling during rapid interruptions, which we mitigate through our turn-fencing logic.

## AI Assistance Disclosure

Interruption/recovery logic in `src/agent.py`, `RIME_EVIDENCE.md`, and this README were developed with AI assistance, built upon LiveKit Agents' official documentation and GitHub issue tracker. All logic was verified and tested by the team.

## Credits & Licenses

- LiveKit Agents — Apache 2.0
- Deepgram — Speech-to-Text API
- OpenRouter — Unified LLM API Routing
- Rime TTS — via `livekit-plugins-rime`
