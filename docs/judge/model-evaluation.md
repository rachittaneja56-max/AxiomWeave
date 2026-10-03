# Final model evaluation registry

This table records the implementation defaults from the server-owned resolver. It does not select a winner. Candidate comparison, blind human scoring, and promotion are pending the final release evaluation.

| Task | Current default | Candidates | Final promoted | Evidence |
|---|---|---|---|---|
| Artifact generation | `gpt-6-luna` | `gpt-6-luna`, `gpt-5-nano` | PENDING FINAL EVALUATION | Not evaluated |
| Lineage analysis | `gpt-6-luna` | `gpt-6-luna`, `gpt-5-nano` | PENDING FINAL EVALUATION | Not evaluated |
| Evidence analysis | `gpt-6-luna` | `gpt-6-luna`, `gpt-5-nano` | PENDING FINAL EVALUATION | Not evaluated |
| Consistency analysis | `gpt-6-luna` | `gpt-6-luna`, `gpt-5-nano` | PENDING FINAL EVALUATION | Not evaluated |
| Action planning | `gpt-6-luna` | `gpt-6-luna`, `gpt-5-nano` | PENDING FINAL EVALUATION | Not evaluated |
| Document OCR | `gpt-5-nano` | `gpt-5-nano`, `gpt-6-luna` | PENDING FINAL EVALUATION | Not evaluated |
| Vision extraction | NOT_CONFIGURED | Not configured | PENDING FINAL EVALUATION | Not evaluated |
| ASR | NOT_CONFIGURED | Not configured | PENDING FINAL EVALUATION | Not evaluated |
| TTS | NOT_CONFIGURED | Not configured | PENDING FINAL EVALUATION | Not evaluated |
| Image generation | NOT_CONFIGURED | Not configured | PENDING FINAL EVALUATION | Not evaluated |
| Video generation | NOT_CONFIGURED | Not configured | PENDING FINAL EVALUATION | Not evaluated |

Profiles and candidate labels are also listed in [`backend/evals/release/model_profiles.json`](../../backend/evals/release/model_profiles.json). The run harness creates unique folders and uses candidate labels A/B/C in human packets. It leaves model names out of the reviewer packet.

All Responses API requests set `store=False`. This setting disables Responses API storage; provider retention remains governed by applicable provider terms. No zero-retention claim is made.
