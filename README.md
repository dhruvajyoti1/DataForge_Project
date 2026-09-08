# EchoAssist — Interruption & Recovery for a Field Technician's Voice Assistant

**Track:** DataForge x Rime Hackathon — Hard voice problem: Interruption and recovery.

> **The Core Claim:**
> When a technician interrupts EchoAssist mid-lookup or mid-speech to ask something new, the assistant stops speaking within one turn, discards the stale in-flight lookup result, and its final spoken response reflects only the technician's latest request — never a blend of the old and new answers.

All empirical testing records and test plan documentation are available in the [`docs/testing/`](docs/testing/) directory.

---

## Project Overview

**EchoAssist** is a voice assistant engineered for field technicians—mechanics, electricians, and equipment repair specialists—who work with hands on tools and grease on their fingers. When troubleshooting a vehicle or machine, voice is not just a convenience; it is the only viable interface.

In noisy, fast-paced field environments, technicians frequently change direction mid-sentence: they start asking for a bolt torque spec, notice a leaking gasket, and abruptly cut in with *"Wait, never mind that, how do I reset the pressure valve?"* EchoAssist tackles the hardest challenge in full-duplex voice AI: **instant interruption detection paired with deterministic state and task recovery**, ensuring background operations are cancelled and old answers never contaminate future turns.

---

## The Problem

Voice assistants in hands-busy professional environments fail in two catastrophic ways during interruptions:

1. **Acoustic / Spoken Overrun (Barge-In Lag):** The user begins speaking, but the assistant continues babbling its previous response for several seconds because voice activity detection (VAD) and audio pipeline cancellation are sluggish.
2. **Stale-Task State Bleed (Async Race Conditions):** When a user asks a complex question that triggers a tool call or slow database lookup, the request executes asynchronously in the background. If the user interrupts with a brand-new inquiry before that lookup completes, standard agent frameworks often allow the background task to complete, inject its stale result into the conversational context, and speak an incoherent hallucination blending both requests.

For a field technician following precise safety procedures or torque limits, receiving a stale or blended answer is dangerous.

---

## The Solution

EchoAssist solves interruption and recovery through a dual-layer strategy:

1. **Aggressive Low-Latency Transport:** Built on the LiveKit Agents framework with Deepgram Nova-3 streaming STT and Rime Arcana TTS streaming over low-latency WebSockets, cutting barge-in detection latency to ~0.20s.
2. **Explicit Turn-Fencing Architecture (`TurnTracker`):** A custom turn-lifecycle manager in `src/agent.py` assigns a monotonically increasing `turn_id` to every user input. In-flight tool calls check whether their assigned `turn_id` is still active; if the user barged in and started a new turn, the running tool is explicitly fenced, raising an `asyncio.CancelledError`. Interrupted assistant utterances are concurrently excised from conversation history (`session.history.remove(chat_item)`), preventing memory contamination.

---

## Key Features

- **Sub-Turn Barge-In Interruption:** Configured with `min_duration=0.2s` and `min_words=0` to immediately silence audio output the instant the technician speaks.
- **Deterministic Stale-Task Fencing:** Long-running tool executions actively monitor turn status and abort immediately if superseded, preventing stale database records from returning.
- **Context & History Sanitization:** When an interruption occurs, partial and aborted assistant chat items are purged from conversation history so the LLM never sees abandoned speech during subsequent turns.
- **Spoken Technical Clarity:** Prompt instructions mandate that numerical values are spelled out in words (e.g., "twenty newton meters" instead of "20 Nm") and technical manual specs are relayed verbatim for crisp TTS delivery.
- **Dual Interface:** Run headlessly in the terminal (`console` or `dev` mode) or connect via the included browser WebRTC interface (`web/index.html` and `web/token_server.py`).

---

## Why Interruption Recovery Matters

In consumer voice bots, an interruption failure is mildly annoying. In industrial and automotive maintenance, it can cause equipment damage or physical injury:

- **Torque & Pressure Specifications:** If a technician asks for lug nut torque (110 Nm), interrupts mid-lookup, and asks about a spark plug (20 Nm), a blended answer could cause overtightening and stripped engine threads.
- **Safety Procedures:** Resetting high-voltage systems or bleeding brake lines requires strict sequential accuracy; abandoned questions must stay abandoned.
- **Technician Trust:** If hands-free voice assistance requires listening to a 10-second preamble before accepting a correction, technicians will abandon the tool and revert to stopping work to check paper manuals.

---

## Architecture / Tech Stack

EchoAssist connects a low-latency WebRTC audio loop with high-speed LLM reasoning and expressive TTS:

- **Transport & WebRTC Orchestration:** [LiveKit Agents](https://docs.livekit.io/agents/) (`AgentSession`, `JobContext`) running on LiveKit Cloud. Manages full-duplex audio transport, client VAD, and event orchestration.
- **Speech-to-Text (STT):** [Deepgram](https://deepgram.com/) (`nova-3`), configured with streaming interim results, 500 ms endpointing, and automotive keyterm biasing (`bolts`, `torque`, `reset`, `handlebar`, `headlight`, `brakes`, `taillight`, `procedure`).
- **LLM Reasoning & Intelligence:** [Groq](https://groq.com/) via `livekit.plugins.openai.LLM` (`base_url="https://api.groq.com/openai/v1"`, `model="openai/gpt-oss-120b"`), authenticated with `GROQ_API_KEY`. Delivers high-speed token streaming.
- **Speech Synthesis (TTS):** [Rime](https://rime.ai/) via `livekit-plugins-rime` (`model="arcana"`, `speaker="celeste"`), streaming over direct WebSocket (`use_websocket=True`) with `reduce_latency=True`.
- **Interruption & Turn Management:** Custom `TurnTracker` engine in `src/agent.py`.

```
[ Technician Voice ]
        │
        ▼ (WebRTC Audio Stream)
[ LiveKit Agents Session ]
   ├── STT: Deepgram Nova-3 (Streaming, biased keyterms)
   ├── Turn Tracker: Monotonic turn IDs & stale-task fencing
   ├── LLM: Groq (openai/gpt-oss-120b via OpenAI-compatible endpoint)
   ├── Tools: lookup_repair_spec (5s simulated manual query with turn check)
   └── TTS: Rime Arcana / Celeste (Streaming WebSockets)
        │
        ▼ (Instant cut on barge-in)
[ Technician Ear / Speaker ]
```

---

## How Interruption and Stale-Task Fencing Works

The interruption logic in `src/agent.py` works across three coordinated event stages:

### 1. Monotonic Turn Generation
Every time the user speaks, LiveKit's `conversation_item_added` event detects `role == "user"`, advancing the turn counter:
```python
active_turn = turn_tracker.new_turn()
timestamps["user_speech_end"] = time.time()
```

### 2. Guarded Tool Execution (`is_stale`)
When a lookup begins in `lookup_repair_spec`, it locks to the turn under which it was invoked:
```python
active_turn = turn_tracker.current_turn_id
try:
    await asyncio.sleep(5.0)  # Simulated manual database retrieval
except asyncio.CancelledError:
    turn_tracker.fence_turn(active_turn)
    raise

if turn_tracker.is_stale(active_turn):
    turn_tracker.fence_turn(active_turn)
    raise asyncio.CancelledError(f"Turn {active_turn} cancelled due to user barge-in.")
```
If a user interrupts while the 5-second lookup is running, `turn_tracker.current_turn_id` increments. When the sleep finishes (or when cancellation propagates), the tool detects that `active_turn != current_turn_id`, fences the turn, and raises `CancelledError`, ensuring the result is never sent to the LLM.

### 3. Speech Interruption & History Cleanup
When user speech cuts off the assistant mid-utterance, LiveKit triggers the `speech_done` callback with `handle.interrupted == True`:
```python
if was_interrupted:
    if turn_now > 0:
        turn_tracker.fence_turn(turn_now)
    for chat_item in handle.chat_items:
        session.history.remove(chat_item)
    return
```
By explicitly removing the aborted message from `session.history`, subsequent turns are protected from conversational context hallucination.

---

## Live vs Simulated Components

- **Live Components:**
  - Full LiveKit WebRTC audio pipeline and session management.
  - Streaming speech recognition via Deepgram Nova-3.
  - LLM inference and streaming completions via Groq (`openai/gpt-oss-120b`).
  - Streaming voice synthesis via Rime Arcana (`celeste`) over WebSocket.
  - Real-time VAD, barge-in detection, and event handling.
  - Browser-based WebRTC client (`web/index.html`) and HTTP token server (`web/token_server.py`).

- **Simulated Components:**
  - **Database Latency:** In `lookup_repair_spec`, an artificial `await asyncio.sleep(5.0)` stands in for an external vehicle manual database. This deterministic 5-second window allows testers to reliably demonstrate mid-lookup barge-ins.
  - **Manual Data:** An in-memory dictionary (`REPAIR_MANUAL`) containing sample automotive repair specifications (spark plugs, check engine lights, oil drain plugs, brake valves, lug nuts, tire pressure sensors).

---

## Setup and Installation

### Prerequisites
- Python 3.10 to 3.14
- [uv](https://github.com/astral-sh/uv) (recommended) or standard Python virtual environment

### Installation Steps

```bash
# 1. Clone the repository
git clone https://github.com/dhruvajyoti1/DataForge_Project.git
cd DataForge_Project

# 2. Sync dependencies using uv
uv sync

# 3. Create your local environment configuration file
cp .env.example .env.local
```

---

## Environment Variables

Edit `.env.local` with your valid credentials:

```ini
LIVEKIT_URL=wss://your-project.livekit.cloud
LIVEKIT_API_KEY=your_livekit_api_key
LIVEKIT_API_SECRET=your_livekit_api_secret
DEEPGRAM_API_KEY=your_deepgram_api_key
RIME_API_KEY=your_rime_api_key
GROQ_API_KEY=your_groq_api_key
```

> [!NOTE]
> **API Key Note:** The current agent implementation (`src/agent.py`) uses **Groq** for high-speed LLM inference and validates `GROQ_API_KEY`. While the template `.env.example` historically referenced `OPENROUTER_API_KEY`, ensure you supply `GROQ_API_KEY` in `.env.local`.

---

## Running the Agent

### 1. Terminal Console Mode (Direct Audio Test)
Test the agent directly in your terminal using your local microphone and speakers:
```bash
uv run python src/agent.py console
```

### 2. Development Mode (LiveKit Cloud Dispatch)
Run the agent connected to your LiveKit Cloud room:
```bash
uv run python src/agent.py dev
```

### 3. Web Client Demonstration
To interact via the visual WebRTC browser client:

1. Start the agent worker in one terminal:
   ```bash
   uv run python src/agent.py dev
   ```
2. Start the lightweight token server in a second terminal:
   ```bash
   uv run python web/token_server.py
   ```
   *(Runs on port 8080 by default)*
3. Open `web/index.html` in your web browser, click the microphone button, and talk.

### 4. Docker Deployment
```bash
# Build Docker image
docker build -t echo-assist .

# Run container with environment configuration
docker run --rm --env-file .env.local echo-assist
```

---

## Testing

The project incorporates two testing layers: an automated test suite template in `tests/` and empirical manual testing protocols recorded under `docs/testing/`.

### Automated Test Suite (`tests/test_agent.py`)
The repository includes unit tests in `tests/test_agent.py` using `pytest` and LiveKit's LLM judge (`openai/gpt-4.1-mini`) to evaluate conversational persona, grounding, and harmful request refusal.

> [!IMPORTANT]
> **Test Suite Status:** Running `uv run pytest` currently fails with `RuntimeError: trying to generate reply without an LLM model` because the stock test harness instantiates `AgentSession()` without injecting the runtime LLM plugin configured in `src/agent.py`. The primary verification of interruption handling and system behavior is documented in the empirical test logs under `docs/testing/`.

---

## Testing Evidence

All test runs, latencies, edge-case observations, and bug logs are transparently documented under [`docs/testing/`](docs/testing/):

- [`Test_Plan.txt`](docs/testing/Test_Plan.txt): 8 technician test scenarios (INT-01 through INT-08) defining success criteria for speech stoppage, stale task cancellation, new question priority, and memory integrity.
- [`Baseline_Results.txt`](docs/testing/Baseline_Results.txt): Latency profiling across conversational and lookup turns.
- [`Interruption_Results.txt`](docs/testing/Interruption_Results.txt): Evaluation of barge-in detection, tool fencing, and conversation memory.
- [`Bug_Log.txt`](docs/testing/Bug_Log.txt): Detailed bug tracker recording open issues and repro steps.
- [`Final_Proof.txt`](docs/testing/Final_Proof.txt): End-to-end trace proving stale-task fencing during an active interruption.

### Summary of Empirical Results

| Test Dimension | Status | Evidence & Observations |
| :--- | :---: | :--- |
| **Interruption Detection** | **PASS** | Audio stops promptly when technician begins speaking. Minimum observed interruption latency: **0.20s**. |
| **Stale-Task Fencing** | **PASS** | Mid-lookup barge-ins trigger `TurnTracker.fence_turn()`. Console explicitly logs: `Task stale due to interruption! Fencing result.` |
| **New Request Priority** | **PASS** | When a request is interrupted (e.g. Turn 6 torque query followed by Turn 7 reset request), the agent processes the new request immediately without reverting to the old query. |
| **Lookup Protection** | **PASS** | Interrupted in-flight lookups are cancelled via `asyncio.CancelledError`; stale results are never spoken or mixed into subsequent replies. |
| **Conversational Latency** | **OBSERVED** | Standard dialogue responses initiate in **0.60s – 3.20s** (typically 1.1s – 2.4s). Lookups take **~6.73s** (5.0s simulated DB delay + pipeline overhead). |
| **Vehicle Lookup Flow** | **PARTIAL** | In multi-turn tests, interrupting a spec query with a reset request led the assistant to ask for vehicle clarification ("Bike"), requiring an extra turn before the procedure was provided. |
| **Speech Recognition (STT)** | **PARTIAL** | Documented under **BUG-001** and **BUG-003**: In noisy environments, phonetic misrecognitions occurred (e.g., "reset procedure" transcribed as "reset processor"), and natural speaking pauses occasionally fragmented a single sentence into separate turns. |
| **TTS / Output Formatting** | **PARTIAL** | Documented under **BUG-002**: During one reset procedure output, garbled formatting characters briefly appeared before the clean spoken string was generated. |

---

## Known Limitations

1. **Simulated Manual Dictionary Keys:** In `src/agent.py`, `lookup_repair_spec` matches query strings against hardcoded keys like `"reset_procedure"` and `"torque_spec"`. If the LLM generates a tool query key that does not match these conditions, the tool falls back to general automotive knowledge rather than deep dictionary lookup.
2. **Speech Endpointing on Natural Pauses (BUG-003):** Fast endpointing (`endpointing_ms=500`) occasionally fragments continuous technician speech if there is a hesitation or pause, causing a false turn increment.
3. **Automated Unit Test Fixture:** `tests/test_agent.py` requires updating the test harness to pass an explicit LLM mock or plugin into `AgentSession()` so `uv run pytest` can run without cloud inference dependency errors.

---

## Project Structure

```
DataForge_Project/
├── src/
│   └── agent.py              # Main entrypoint: Agent persona, TurnTracker, tools, and event handlers
├── web/
│   ├── index.html            # WebRTC browser client for audio testing
│   ├── token_server.py       # Local token generation server for LiveKit rooms
│   └── requirements.txt      # Web server requirements
├── tests/
│   └── test_agent.py         # Pytest test suite for agent behavior
├── docs/
│   └── testing/              # Empirical testing logs and evidence
│       ├── Test_Plan.txt     # Test procedures and acceptance criteria
│       ├── Baseline_Results.txt # Latency measurements across turns
│       ├── Interruption_Results.txt # Barge-in and recovery test cases
│       ├── Bug_Log.txt       # Bug tracker for STT and output formatting issues
│       └── Final_Proof.txt   # Step-by-step proof of stale-task fencing
├── Dockerfile                # Multi-stage production container build
├── pyproject.toml            # Project dependencies and tool configurations
├── .env.example              # Sample environment variable template
└── README.md                 # Project documentation and hackathon technical report
```

---

## AI Assistance Disclosure

EchoAssist's turn-fencing architecture, `src/agent.py` event integration, test procedures, and documentation were developed with AI assistance utilizing LiveKit Agents official documentation, LiveKit SDK issue discussions, and developer testing sessions. All code, test runs, and latency benchmarks were verified and validated on live hardware.

---

## Credits & Licenses

- **LiveKit Agents:** Apache-2.0 License — Real-time WebRTC audio framework.
- **Deepgram:** Streaming Speech-to-Text API (Nova-3).
- **Groq:** Fast LLM inference API (`openai/gpt-oss-120b`).
- **Rime:** Low-latency expressive neural TTS via WebSocket streaming (`arcana`/`celeste`).
