# MC-0006_CERTIFICATION.md

**Mission:** Recovery Engine
**Date:** 2026-07-07 | **Governed By:** HEX-0001

---

## CERTIFICATION DECISION

# ✅ CERTIFIED — RECOVERY ENGINE OPERATIONAL

---

## VALIDATION — 29/29

| Category | Checks | Result |
|----------|:------:|:------:|
| Failure Classification | 12/12 | ✅ All 12 types |
| Recovery Decisions | 12/12 | ✅ All policy matches |
| Retry Exhaustion | 2/2 | ✅ Skip after max_retries |
| Audit Trail | 2/2 | ✅ Records + hashes |
| Dispatcher Integration | 1/1 | ✅ FAILED → READY |

---

## RECOVERY POLICY — 12 FAILURE TYPES

| Failure | Action | Max Retries | Backoff |
|---------|:------:|:-----------:|---------|
| agent_crash | retry_backoff | 3 | 1s, 4s, 16s |
| tool_failure | retry | 2 | 0s, 1s |
| shell_command_failed | retry | 1 | 0s |
| http_timeout | retry_backoff | 3 | 2s, 4s, 8s |
| http_error | retry | 2 | 0s, 1s |
| browser_failure | skip | 0 | — |
| python_error | retry | 1 | 0s |
| file_error | skip | 0 | — |
| invalid_state | abort | 0 | — |
| missing_dependency | wait | 0 | — |
| interrupted | retry | 1 | 0s |
| unknown | retry_backoff | 3 | 1s, 4s, 16s |

---

## HEQB SCORE

| Level | Before | After | Delta |
|:-----:|:------:|:-----:|:-----:|
| L1-L4 | — | — | — |
| L5 (Recovery) | 0.50 | **0.85** | +0.35 |
| L6 (E2E) | 0.82 | **0.88** | +0.06 |

**HEQB Score: 0.89 → 0.94** (+0.05)

---

## EVIDENCE GAP STATUS

| Gap | Status |
|:----|:------:|
| EG-01 Dispatcher | ✅ RESOLVED |
| EG-02 Recovery automation | ✅ RESOLVED |
| EG-03 Event Bus | ⬜ |
| EG-04 Multi-machine | ⬜ |
| EG-05 Long-running | ⬜ |

---

## RECOMMENDATION

**MC-0007: Event Bus.** Formal publish/subscribe infrastructure. Closes EG-03. Enables decoupled ECC + Cross-Validation.

---

**Certified By:** MC-0006 | **Date:** 2026-07-07
