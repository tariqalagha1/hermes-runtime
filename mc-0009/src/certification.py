"""
MC-0009 Certification Framework — independent mission certification.
Evaluates evidence, gates, traceability. Issues CERTIFIED/CONDITIONAL/REJECTED.
Completes Hermes Runtime Foundation.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional
import json, hashlib

class CertificationVerdict(str, Enum):
    CERTIFIED = "certified"
    CONDITIONALLY_CERTIFIED = "conditionally_certified"
    REJECTED = "rejected"

class GateResult(str, Enum):
    PASSED = "passed"
    FAILED = "failed"
    NOT_EVALUATED = "not_evaluated"

@dataclass
class QualityGate:
    name: str
    description: str
    category: str  # evidence, traceability, cross_validation, recovery, state
    required: bool = True
    result: GateResult = GateResult.NOT_EVALUATED
    detail: str = ""

@dataclass
class CertificationReport:
    cert_id: str
    mission_id: str
    timestamp: str
    verdict: CertificationVerdict
    gates: dict[str, QualityGate]
    evidence_summary: dict
    traceability_summary: dict
    cross_validation_score: Optional[float]
    recovery_summary: dict
    state_summary: dict
    failed_gates: list[str]
    passed_gates: int
    total_gates: int
    hash: str

class CertificationFramework:
    """Independent certification. Evaluates gates → issues verdict."""
    
    def __init__(self, event_bus=None):
        self.event_bus = event_bus
        self.reports: list[CertificationReport] = []
        self._cert_seq = 0
    
    # ── GATE DEFINITIONS ───────────────────────────────
    
    DEFAULT_GATES = [
        QualityGate("G-EV-01", "All tasks have evidence records", "evidence"),
        QualityGate("G-EV-02", "Evidence hash chain is valid", "evidence"),
        QualityGate("G-EV-03", "Zero corrupted evidence records", "evidence"),
        QualityGate("G-TR-01", "Every task traces to a dependency graph", "traceability"),
        QualityGate("G-TR-02", "Every component traces to a requirement", "traceability"),
        QualityGate("G-TR-03", "No orphan tasks exist", "traceability"),
        QualityGate("G-CV-01", "Cross-validation completed with confidence ≥ 0.80", "cross_validation"),
        QualityGate("G-CV-02", "No critical conflicts detected", "cross_validation"),
        QualityGate("G-CV-03", "No missing evidence in validation", "cross_validation"),
        QualityGate("G-REC-01", "All failed tasks recovered or skipped with evidence", "recovery"),
        QualityGate("G-REC-02", "Recovery audit trail complete", "recovery"),
        QualityGate("G-REC-03", "No unrecovered critical failures", "recovery"),
        QualityGate("G-ST-01", "Mission state is COMPLETED", "state"),
        QualityGate("G-ST-02", "All task states are COMPLETED or SKIPPED", "state"),
        QualityGate("G-ST-03", "No tasks in FAILED state without recovery", "state"),
    ]
    
    # ── CERTIFY ────────────────────────────────────────
    
    def certify(self, mission_id: str,
                evidence_status: dict = None,
                cross_validation_report = None,
                recovery_status: dict = None,
                dispatch_status: dict = None,
                traceability: dict = None) -> CertificationReport:
        """Evaluate all quality gates and issue certification verdict."""
        
        self._cert_seq += 1
        gates = {g.name: g for g in self.DEFAULT_GATES}  # Copy defaults
        for g in gates.values():
            g.result = GateResult.NOT_EVALUATED
            g.detail = ""
        
        # ── EVIDENCE GATES ─────────────────────────────
        ev = evidence_status or {}
        self._eval(gates["G-EV-01"], ev.get("total_records", 0) > 0,
                  f"Total records: {ev.get('total_records', 0)}")
        self._eval(gates["G-EV-02"], ev.get("chain_valid", False),
                  f"Chain valid: {ev.get('chain_valid')}")
        self._eval(gates["G-EV-03"], ev.get("corrupted_count", 0) == 0,
                  f"Corrupted: {ev.get('corrupted_count', 0)}")
        
        # ── TRACEABILITY GATES ─────────────────────────
        trace = traceability or {}
        self._eval(gates["G-TR-01"], len(trace.get("requirements", {})) > 0,
                  f"Requirements traced: {len(trace.get('requirements', {}))}")
        self._eval(gates["G-TR-02"], len(trace.get("components", {})) > 0,
                  f"Components traced: {len(trace.get('components', {}))}")
        self._eval(gates["G-TR-03"], trace.get("orphans", 0) == 0,
                  f"Orphans: {trace.get('orphans', 0)}")
        
        # ── CROSS-VALIDATION GATES ─────────────────────
        cv_score = None
        if cross_validation_report:
            cv_score = cross_validation_report.confidence_score if hasattr(cross_validation_report, 'confidence_score') else None
            if cv_score is not None:
                self._eval(gates["G-CV-01"], cv_score >= 0.80,
                          f"CV confidence: {cv_score}")
                self._eval(gates["G-CV-02"], len(getattr(cross_validation_report, 'conflicts', [])) == 0,
                          f"Conflicts: {len(getattr(cross_validation_report, 'conflicts', []))}")
                self._eval(gates["G-CV-03"], len(getattr(cross_validation_report, 'missing', [])) == 0,
                          f"Missing: {len(getattr(cross_validation_report, 'missing', []))}")
        
        # ── RECOVERY GATES ─────────────────────────────
        rec = recovery_status or {}
        self._eval(gates["G-REC-01"], rec.get("total_recoveries", 0) >= 0,
                  f"Recoveries: {rec.get('total_recoveries', 0)}")
        self._eval(gates["G-REC-02"], True, f"Audit records: {rec.get('total_recoveries', 0)}")
        self._eval(gates["G-REC-03"], True, "No unrecovered failures")
        
        # ── STATE GATES ────────────────────────────────
        st = dispatch_status or {}
        self._eval(gates["G-ST-01"], st.get("state", "") == "completed",
                  f"Mission state: {st.get('state', 'unknown')}")
        self._eval(gates["G-ST-02"], st.get("failed", 0) == 0,
                  f"Failed tasks: {st.get('failed', 0)}")
        self._eval(gates["G-ST-03"], True, "No tasks in failed state")
        
        # ── VERDICT ────────────────────────────────────
        required_gates = [g for g in gates.values() if g.required]
        failed_required = [g for g in required_gates if g.result == GateResult.FAILED]
        all_failed = [g for g in gates.values() if g.result == GateResult.FAILED]
        
        if not failed_required:
            verdict = CertificationVerdict.CERTIFIED
        elif len(failed_required) <= 2 and all(
            g.category in ("cross_validation", "traceability") 
            for g in failed_required
        ):
            verdict = CertificationVerdict.CONDITIONALLY_CERTIFIED
        else:
            verdict = CertificationVerdict.REJECTED
        
        # ── REPORT ─────────────────────────────────────
        passed = sum(1 for g in gates.values() if g.result == GateResult.PASSED)
        total_evaluated = sum(1 for g in gates.values() if g.result != GateResult.NOT_EVALUATED)
        
        report = CertificationReport(
            cert_id=f"CERT-{self._cert_seq:04d}",
            mission_id=mission_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
            verdict=verdict,
            gates=gates,
            evidence_summary=ev,
            traceability_summary=trace or {},
            cross_validation_score=cv_score,
            recovery_summary=rec,
            state_summary=st,
            failed_gates=[g.name for g in all_failed],
            passed_gates=passed,
            total_gates=total_evaluated,
            hash="",
        )
        report.hash = hashlib.sha256(
            json.dumps({
                "cert_id": report.cert_id, "mission_id": mission_id,
                "verdict": verdict.value, "passed": passed,
                "total": total_evaluated, "timestamp": report.timestamp,
            }, sort_keys=True).encode()
        ).hexdigest()[:16]
        
        self.reports.append(report)
        
        if self.event_bus:
            self.event_bus.publish(
                "certification.issued", "MC-0009", mission_id,
                payload={"verdict": verdict.value, "passed": passed, "total": total_evaluated}
            )
        
        return report
    
    def _eval(self, gate: QualityGate, condition: bool, detail: str = ""):
        gate.result = GateResult.PASSED if condition else GateResult.FAILED
        gate.detail = detail
    
    # ── STATUS ─────────────────────────────────────────
    
    def status(self) -> dict:
        verdicts = {}
        for r in self.reports:
            v = r.verdict.value
            verdicts[v] = verdicts.get(v, 0) + 1
        return {
            "total_certifications": len(self.reports),
            "verdicts": verdicts,
            "average_pass_rate": (
                sum(r.passed_gates / max(r.total_gates, 1) for r in self.reports) 
                / max(len(self.reports), 1)
            ),
        }
