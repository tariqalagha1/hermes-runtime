# HEQB-0001_CERTIFICATION.md

**Benchmark:** Hermes Execution Qualification Benchmark
**Date:** 2026-07-07 | **Governed By:** HEX-0001

---

## CERTIFICATION DECISION

# ✅ CERTIFIED — HEQB IS THE PERMANENT QUALIFICATION STANDARD

---

## BENCHMARK ARCHITECTURE

| Level | Capability | Missions | Weight |
|:-----:|------------|:--------:|:------:|
| L1 | Compilation | 3 | 0.15 |
| L2 | Scheduling | 3 | 0.15 |
| L3 | Dispatch | 4 | 0.20 |
| L4 | Agent Execution | 6 | 0.25 |
| L5 | Recovery | 3 | 0.15 |
| L6 | End-to-End | 3 | 0.10 |

**22 benchmark missions. 8 metrics. 6 levels.**

---

## SCORING

```
HEQB Score = Σ(level_weight × completion_ratio × metric_average)
Range: 0.0–1.0

≥0.95: Production Ready
0.85–0.94: Qualified with caveats
0.70–0.84: Development quality
<0.70: Not qualified
```

---

## METRICS

| ID | Metric | Target | Regression Flag |
|:---|--------|:------:|:---------------:|
| M-CORRECT | Execution correctness | 1.0 | -5% |
| M-DEPS | Dependency correctness | 1.0 | -1% |
| M-STATE | State transition validity | 1.0 | Any violation |
| M-PARALLEL | Parallel efficiency | ≥0.7 | -10% |
| M-EVIDENCE | Evidence completeness | 1.0 | -1% |
| M-RECOVER | Recovery effectiveness | ≥0.8 | -10% |
| M-CERTIFY | Certification accuracy | 1.0 | Any error |
| M-REGRESSION | Regression stability | 0.0 | >0 |

---

## CURRENT ESTIMATED SCORE

```
Runtime: Hermes v1.0.0 (MC-0001–MC-0004)

L1: 1.00  (Compiler certified)
L2: 1.00  (Scheduler certified)  
L3: 1.00  (Dispatcher certified)
L4: 0.92  (Agent Runtime — 11/12 pass)
L5: 0.50  (Recovery — designed, not automated)
L6: 0.75  (End-to-end — partial)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
HEQB Score: 0.88 — Qualified with caveats
```

---

## VERSIONING

```
1.0.0 → Baseline (22 missions, 8 metrics)
x.0.0 → Mission set changed (not comparable)
1.x.0 → New missions added (comparable, optional)
1.0.x → Threshold adjustments
```

---

## PRINCIPLES

| Principle | Enforcement |
|-----------|------------|
| Measure capabilities, not implementations | Capability-level scoring |
| Same version → same score | Deterministic benchmarks |
| Backward-comparable | Semantic versioning |
| Independent certification | Implementer ≠ Certifier |
| Never measures LLM quality | Runtime-only metrics |

---

**Certified By:** HEQB-0001 | **Date:** 2026-07-07
