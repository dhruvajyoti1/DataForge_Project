# EchoAssist — Interruption & Recovery for a Field Technician's Voice Assistant

**Track:** DataForge x Rime Hackathon — Hard voice problem: Interruption and
recovery.

## The claim

> When a technician interrupts EchoAssist mid-lookup to ask something new,
> the assistant stops speaking within one turn, discards the stale in-flight
> lookup result, and its final spoken response reflects only the
> technician's latest request — never a blend of the old and new answers.

See `RIME_EVIDENCE.md` for the acceptance test, procedure, and results.

## Who this is for

A field technician who is mid-repair, hands busy with tools, and needs to
ask quick questions out loud — torque specs, reset procedures, next steps —
without stopping work to look at a screen. For this user, voice isn't a
convenience, it's the only practical interface, and being unable to cleanly
interrupt and redirect the assistant (e.g. "never mind, ask something else
instead") is a real barrier to getting the job done safely and quickly.

## Architecture

- **Transport & orchestration:** LiveKit Agents (`AgentSession`) — handles
  audio transport, VAD, turn detection, and built-in interruption triggers.
- **Speech recognition & reasoning:** [TEAM TO FILL IN — STT/LLM provider]
- **Speech synthesis:** Rime, via `livekit-plugins-rime`, streamed over
  WebSocket (`use_websocket=True`) for lower latency and word-level
  timestamps. Model: `arcana`, speaker: `celeste` (confirm final choice
  against Rime's live catalog before submission).
- **Interruption/recovery layer (this repo's contribution, `agent.py`):**
  - `SessionState` / `TurnLog`: tags every tool call and reply with the
    turn ID it belongs to.
  - `is_stale()`: checked before any tool result is returned/spoken; if the
    user has moved on to a new turn, the stale result is fenced (raised as
    `CancelledError`) instead of being spoken.
  - Event handlers on `user_state_changed` and `conversation_item_added`
    log exactly when an interruption happened and what was cut, which is
    the evidence trail used in `RIME_EVIDENCE.md`.

## What's live vs. simulated

- **Live:** the full LiveKit + Rime voice pipeline, real interruption
  detection, real TTS audio.
- **Simulated:** `lookup_repair_spec` searches a small in-memory
  `REPAIR_MANUAL` dict with an artificial `asyncio.sleep()` standing in for
  a real repair-manual/database lookup — this is disclosed, not hidden, and
  exists only to create a reliable window for the interrupt demo. [TEAM TO
  FILL IN: once Person B's real 5-8 question test set is built, update this
  section and REPAIR_MANUAL with the real content.]

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env   # fill in your own keys, never commit real ones
python agent.py dev
```

Required environment variables (see `.env.example`):
```
LIVEKIT_URL=
LIVEKIT_API_KEY=
LIVEKIT_API_SECRET=
RIME_API_KEY=
OPENAI_API_KEY=        # or whichever STT/LLM provider the team finalizes
```

## Known limitations (disclosed)

See `RIME_EVIDENCE.md` — in particular, an upstream LiveKit Agents framework
issue around tool-result handling during interruption, which we mitigate
but do not claim to fully eliminate.

## AI assistance disclosure

Interruption/recovery logic in `agent.py`, `RIME_EVIDENCE.md`, and this
README were built with AI assistance (Claude), based on LiveKit Agents'
official documentation and GitHub issue tracker. All logic is understood
and was tested by the team; the base voice pipeline (STT/LLM wiring) is
[TEAM TO FILL IN who/how].

## Credits & licenses

- LiveKit Agents — [Apache 2.0](https://github.com/livekit/agents)
- Rime TTS — via `livekit-plugins-rime`, requires a Rime API key
- [TEAM TO FILL IN: any other reused components]
