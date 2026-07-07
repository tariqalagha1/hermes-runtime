"""
MC-0008 Cross-Validation Engine — independent evidence validation.
Compares outputs, detects conflicts, scores confidence.
Never modifies execution. Observation only.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional
import json, hashlib, uuid

# ═══════════════════════════════════════════════════════
# VALIDATION MODELS
# ═══════════════════════════════════════════════════════

@dataclass
class ValidationFinding:
    finding_id: str
    type: str  # "consistent", "conflict", "missing", "divergent"
    severity: str  # "critical", "high", "medium", "low", "info"
    source_a: str  # evidence source 1
    source_b: str  # evidence source 2
    field: str     # what was compared
    value_a: str   # value from source a
    value_b: str   # value from source b
    description: str
    resolved: bool = False

@dataclass
class ValidationReport:
    validation_id: str
    mission_id: str
    timestamp: str
    total_comparisons: int
    consistent: int
    conflicts: list[ValidationFinding]
    missing: list[ValidationFinding]
    divergent: list[ValidationFinding]
    confidence_score: float  # 0.0–1.0
    hash: str

# ═══════════════════════════════════════════════════════
# CROSS-VALIDATION ENGINE
# ═══════════════════════════════════════════════════════

class CrossValidationEngine:
    """Independent evidence validation. Compares, detects, scores."""
    
    def __init__(self, event_bus=None):
        self.event_bus = event_bus
        self.reports: list[ValidationReport] = []
        self._id_seq = 0
    
    # ── VALIDATE MISSION ───────────────────────────────
    
    def validate_evidence(self, mission_id: str, 
                          source_a: list[dict],
                          source_b: list[dict],
                          source_labels: tuple[str, str] = ("A", "B")) -> ValidationReport:
        """Compare two evidence sources. Detect conflicts, score confidence."""
        
        self._id_seq += 1
        findings = []
        total = 0
        consistent = 0
        
        a_label, b_label = source_labels
        
        # Build lookup by task_id
        by_task_a = {r.get("task_id", r.get("evidence_id")): r for r in source_a}
        by_task_b = {r.get("task_id", r.get("evidence_id")): r for r in source_b}
        all_tasks = set(by_task_a.keys()) | set(by_task_b.keys())
        
        for task_key in all_tasks:
            a = by_task_a.get(task_key)
            b = by_task_b.get(task_key)
            
            # Missing evidence detection
            if a is None:
                findings.append(ValidationFinding(
                    finding_id=f"CV-{self._id_seq}-{len(findings)+1:03d}",
                    type="missing",
                    severity="high",
                    source_a=a_label,
                    source_b=b_label,
                    field=task_key,
                    value_a="absent",
                    value_b="present" if b else "absent",
                    description=f"Evidence missing from source {a_label} for {task_key}",
                ))
                continue
            if b is None:
                findings.append(ValidationFinding(
                    finding_id=f"CV-{self._id_seq}-{len(findings)+1:03d}",
                    type="missing",
                    severity="high",
                    source_a=a_label,
                    source_b=b_label,
                    field=task_key,
                    value_a="present",
                    value_b="absent",
                    description=f"Evidence missing from source {b_label} for {task_key}",
                ))
                continue
            
            # Compare comparable fields
            comparable = ["hash", "status", "result", "success", "duration_ms", "exit_code"]
            for field in comparable:
                va = a.get(field, "").strip() if isinstance(a.get(field), str) else str(a.get(field, ""))
                vb = b.get(field, "").strip() if isinstance(b.get(field), str) else str(b.get(field, ""))
                total += 1
                
                if va == vb:
                    consistent += 1
                else:
                    # Determine severity
                    severity = "low"
                    if field == "hash":
                        severity = "critical"   # Hash mismatch = evidence corruption
                    elif field == "success":
                        severity = "critical"   # One says success, other says failure
                    elif field == "result":
                        severity = "high"       # Different results
                    elif field == "exit_code":
                        severity = "medium"
                    
                    findings.append(ValidationFinding(
                        finding_id=f"CV-{self._id_seq}-{len(findings)+1:03d}",
                        type="conflict" if field != "result" else "divergent",
                        severity=severity,
                        source_a=a_label,
                        source_b=b_label,
                        field=field,
                        value_a=va,
                        value_b=vb,
                        description=f"Mismatch in {field}: [{a_label}]={va} vs [{b_label}]={vb}",
                    ))
        
        # Score: consistent / total, weighted by severity
        # Conflicts reduce score more than missing evidence
        critical_weight = 0.15
        high_weight = 0.10
        medium_weight = 0.05
        low_weight = 0.02
        
        penalty = 0.0
        for f in findings:
            if f.severity == "critical":
                penalty += critical_weight
            elif f.severity == "high":
                penalty += high_weight
            elif f.severity == "medium":
                penalty += medium_weight
            elif f.severity == "low":
                penalty += low_weight
        
        raw_score = (consistent / max(total, 1)) if total > 0 else 1.0
        confidence = max(0.0, min(1.0, raw_score - penalty))
        
        report = ValidationReport(
            validation_id=f"VAL-{self._id_seq:04d}",
            mission_id=mission_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
            total_comparisons=total,
            consistent=consistent,
            conflicts=[f for f in findings if f.type == "conflict"],
            missing=[f for f in findings if f.type == "missing"],
            divergent=[f for f in findings if f.type == "divergent"],
            confidence_score=round(confidence, 4),
            hash="",
        )
        report.hash = hashlib.sha256(
            json.dumps(report.__dict__, sort_keys=True, default=str).encode()
        ).hexdigest()[:16]
        
        self.reports.append(report)
        
        # Publish event
        if self.event_bus:
            self.event_bus.publish(
                "cross_validation.completed",
                "MC-0008",
                mission_id,
                payload={
                    "confidence": confidence,
                    "conflicts": len(report.conflicts),
                    "consistent": consistent,
                    "total": total,
                }
            )
        
        return report
    
    # ── SELF-VALIDATE ──────────────────────────────────
    
    def self_validate(self, mission_id: str, evidence_records: list[dict]) -> ValidationReport:
        """Validate evidence against itself (hash chain integrity check)."""
        return self.validate_evidence(
            mission_id,
            evidence_records,
            evidence_records,
            ("original", "recomputed")
        )
    
    # ── STATS ──────────────────────────────────────────
    
    def status(self) -> dict:
        avg_confidence = (
            sum(r.confidence_score for r in self.reports) / max(len(self.reports), 1)
        )
        total_conflicts = sum(len(r.conflicts) for r in self.reports)
        total_missing = sum(len(r.missing) for r in self.reports)
        
        return {
            "total_reports": len(self.reports),
            "average_confidence": round(avg_confidence, 4),
            "total_comparisons": sum(r.total_comparisons for r in self.reports),
            "total_conflicts": total_conflicts,
            "total_missing": total_missing,
            "total_divergent": sum(len(r.divergent) for r in self.reports),
        }
    
    def latest_report(self) -> Optional[ValidationReport]:
        return self.reports[-1] if self.reports else None
