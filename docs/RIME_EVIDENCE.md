# RIME_EVIDENCE.md

## Hard Voice Claim

**Problem chosen: Interruption and recovery.**

When a technician interrupts EchoAssist mid-lookup or mid-speech to ask something new, the assistant stops its **Rime-generated speech** within one turn, cancels the stale in-flight tool call, and its next spoken response — also delivered by Rime — reflects only the technician's latest request. The old, abandoned answer is never spoken, queued, or blended into a later reply.

Rime is not incidental here: it is the primary and only spoken output channel. There is no play button, no pre-recorded audio, and no fallback TTS provider — every word the user hears, including the corrected response after an interruption, is synthesized live by Rime (`model="arcana"`, `speaker="celeste"`) and streamed over a WebSocket via `livekit-plugins-rime`. Removing Rime removes the product's only output entirely.

## Acceptance Test

Defined before demoing (matches `docs/testing/Test_Plan.txt`'s "Interrupt during a lookup" scenario):

> Ask a question that triggers a tool call (`lookup_repair_spec`, which holds for a fixed 5-second simulated manual lookup before Rime would speak the result). While the tool call is still pending, interrupt with a different, unrelated question.
>
> **Pass criteria:**
> 1. Any Rime audio currently queued or playing stops promptly on interruption.
> 2. The stale tool call is cancelled/fenced — its result is never sent to Rime for synthesis, at any point, including after it "finishes" in the background.
> 3. The next Rime-spoken response answers only the new question.
> 4. `session.history` reflects what the user actually heard — the interrupted, unspoken answer is purged, not retained as if it were said.
> 5. No crash; the session remains usable for further turns.

## Procedure

1. Start the agent: `uv run python src/agent.py console` (or `dev` mode against the LiveKit room via the web client).
2. Ask a torque or reset-procedure question (e.g., *"What's the torque spec for the lug nuts?"*) — this routes to `lookup_repair_spec`, which sleeps 5 seconds before a result would be spoken.
3. Before the 5 seconds elapse, interrupt with a different question (e.g., *"Never mind — how do I reset the tire pressure sensor?"*).
4. Observe the console output. The `TurnTracker` engine in `src/agent.py` logs the fencing event directly:
   ```
   [Turn N] Task stale due to interruption! Fencing result.
   ```
5. Confirm via the technical log (`web/voice-agent.html` → "Show technical log", or the console) that the assistant's next Rime-synthesized reply answers only the second question.
6. Repeat for the full set of interruption scenarios in `docs/testing/Test_Plan.txt` for broader coverage.

This is fully repeatable — no special fixture is needed beyond the two spoken turns above; the 5-second window in `lookup_repair_spec` is a deliberate, fixed delay that makes the race condition reproducible on demand rather than relying on network timing luck.

## Result

From `docs/testing/Interruption_Results.txt`, `Baseline_Results.txt`, and `Final_Proof.txt`:

| Check | Result |
| :--- | :--- |
| Rime audio stops on barge-in | **PASS** — minimum observed stop latency 0.20s |
| Stale tool result never spoken | **PASS** — confirmed via `Task stale due to interruption! Fencing result.` across every interruption run recorded in `Interruption_Results.txt` and `Final_Proof.txt` |
| New question answered, not the old one | **PASS** — e.g. Turn 6 (torque) interrupted by Turn 7 (reset); Turn 7 was answered, Turn 6's result never appeared |
| Conversation memory matches what was heard | **PARTIAL** — see Limitations |
| No crash during/after interruption | **PASS** across all interruption test cases run |
| Normal (non-interrupted) response latency | 0.60s – 3.20s (typically 1.1s–2.4s) |
| Lookup-based response latency | ~6.73s (5.0s simulated DB delay + pipeline overhead) |

## Limitations

- **Conversation memory under interruption — only partially verified:** `Interruption_Results.txt`'s conversation-memory test result is recorded as PARTIAL — the assistant correctly followed a short follow-up ("Bike") after a clarifying question, but full memory-accuracy testing (confirming the assistant never references what an interrupted, unspoken answer *would* have said) wasn't exhaustively exercised.
- **Speech recognition (STT), not interruption logic:** Deepgram occasionally misheard phrases under real conditions (e.g., "reset procedure" transcribed as "reset processor" — `BUG-001`). This affects which question gets asked, not whether Rime correctly stops/resumes.
- **TTS output formatting:** one observed case of briefly garbled characters preceding a clean Rime-spoken result (`BUG-002`) — the correct spoken content still followed.
- **Speech fragmentation:** natural pauses in continuous speech were occasionally treated as separate turns, causing an unintended interruption event (`BUG-003`).
- **Multi-turn lookup flow:** interrupting a spec query with a reset-procedure request sometimes required the assistant to ask a clarifying follow-up (e.g., "which vehicle?") before Rime could speak the final procedure — the interruption handling itself still passed, but the full lookup-to-answer flow took an extra turn.
- **Repair manual lookup accuracy (found and fixed during hardening):** `lookup_repair_spec` originally referenced two dictionary keys that didn't exist in `REPAIR_MANUAL`, causing an unhandled `KeyError` on the exact queries this test relies on (torque/reset). This has been fixed by matching against the manual's real per-part keys; see `README.md` → Known Limitations #1 for the before/after.
- **Rime configuration specificity:** `language`, region/`endpoint`, and explicit audio format are not currently set in `src/agent.py` (Rime's defaults apply). Per the submission requirements, these should be pinned explicitly and documented in `README.md` before final submission.
- **Test ID numbering:** `docs/testing/Test_Plan.txt` and `docs/testing/Interruption_Results.txt` use overlapping `INT-01`–`INT-08` labels for different test cases (and `Interruption_Results.txt` has two separate entries both labeled `INT-04`). This evidence file references test cases by description rather than ID to avoid ambiguity — worth reconciling the numbering across those two files before submission.
- **Not yet run:** a dedicated benchmark comparing Rime against alternative TTS providers — this project does not claim to be a benchmark submission, so that section of the challenge brief doesn't apply.
