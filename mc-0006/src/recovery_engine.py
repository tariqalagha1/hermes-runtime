"""
MC-0006 Recovery Engine — automated failure classification and recovery.
Integrates with Dispatcher, Agent Runtime, Evidence Pipeline.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional
import json, hashlib, sys, os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../mc-0005/src'))
from evidence_pipeline import EvidencePipeline

# ═══════════════════════════════════════════════════════
# FAILURE CLASSIFICATION
# ═══════════════════════════════════════════════════════

class FailureType(str, Enum):
    AGENT_CRASH = "agent_crash"
    TOOL_FAILURE = "tool_failure"
    SHELL_COMMAND_FAILED = "shell_command_failed"
    HTTP_TIMEOUT = "http_timeout"
    HTTP_ERROR = "http_error"
    BROWSER_FAILURE = "browser_failure"
    PYTHON_ERROR = "python_error"
    FILE_ERROR = "file_error"
    INVALID_STATE = "invalid_state"
    MISSING_DEPENDENCY = "missing_dependency"
    INTERRUPTED = "interrupted"
    UNKNOWN = "unknown"

class RecoveryAction(str, Enum):
    RETRY = "retry"           # Retry same task
    RETRY_WITH_BACKOFF = "retry_backoff"  # Retry with delay
    SKIP = "skip"             # Skip task, continue mission
    ABORT_MISSION = "abort"   # Abort entire mission
    WAIT_DEPENDENCY = "wait"  # Wait for dependency
    NO_ACTION = "none"        # No recovery needed

# ═══════════════════════════════════════════════════════
# RECOVERY POLICY
# ═══════════════════════════════════════════════════════

RECOVERY_POLICY = {
    FailureType.AGENT_CRASH: {
        "action": RecoveryAction.RETRY_WITH_BACKOFF,
        "max_retries": 3,
        "backoff_seconds": [1, 4, 16],
        "preserve_evidence": True,
        "reason": "Agent crash — retry with exponential backoff"
    },
    FailureType.TOOL_FAILURE: {
        "action": RecoveryAction.RETRY,
        "max_retries": 2,
        "backoff_seconds": [0, 1],
        "preserve_evidence": True,
        "reason": "Tool failure — retry up to 2 times"
    },
    FailureType.SHELL_COMMAND_FAILED: {
        "action": RecoveryAction.RETRY,
        "max_retries": 1,
        "backoff_seconds": [0],
        "preserve_evidence": True,
        "reason": "Shell command failed — retry once"
    },
    FailureType.HTTP_TIMEOUT: {
        "action": RecoveryAction.RETRY_WITH_BACKOFF,
        "max_retries": 3,
        "backoff_seconds": [2, 4, 8],
        "preserve_evidence": True,
        "reason": "HTTP timeout — retry with backoff"
    },
    FailureType.HTTP_ERROR: {
        "action": RecoveryAction.RETRY,
        "max_retries": 2,
        "backoff_seconds": [0, 1],
        "preserve_evidence": True,
        "reason": "HTTP error — retry up to 2 times"
    },
    FailureType.BROWSER_FAILURE: {
        "action": RecoveryAction.SKIP,
        "max_retries": 0,
        "backoff_seconds": [],
        "preserve_evidence": True,
        "reason": "Browser failure — skip (environment-dependent)"
    },
    FailureType.PYTHON_ERROR: {
        "action": RecoveryAction.RETRY,
        "max_retries": 1,
        "backoff_seconds": [0],
        "preserve_evidence": True,
        "reason": "Python error — retry once"
    },
    FailureType.FILE_ERROR: {
        "action": RecoveryAction.SKIP,
        "max_retries": 0,
        "backoff_seconds": [],
        "preserve_evidence": True,
        "reason": "File error — skip (likely permission/path issue)"
    },
    FailureType.INVALID_STATE: {
        "action": RecoveryAction.ABORT_MISSION,
        "max_retries": 0,
        "backoff_seconds": [],
        "preserve_evidence": True,
        "reason": "Invalid state — abort mission (unrecoverable)"
    },
    FailureType.MISSING_DEPENDENCY: {
        "action": RecoveryAction.WAIT_DEPENDENCY,
        "max_retries": 0,
        "backoff_seconds": [],
        "preserve_evidence": True,
        "reason": "Missing dependency — wait for dependency completion"
    },
    FailureType.UNKNOWN: {
        "action": RecoveryAction.RETRY_WITH_BACKOFF,
        "max_retries": 3,
        "backoff_seconds": [1, 4, 16],
        "preserve_evidence": True,
        "reason": "Unknown failure — retry with backoff (conservative)"
    },
    FailureType.INTERRUPTED: {
        "action": RecoveryAction.RETRY,
        "max_retries": 1,
        "backoff_seconds": [0],
        "preserve_evidence": True,
        "reason": "Interrupted — retry once"
    },
}

# ═══════════════════════════════════════════════════════
# RECOVERY RECORD
# ═══════════════════════════════════════════════════════

@dataclass
class RecoveryRecord:
    recovery_id: str
    mission_id: str
    task_id: str
    failure_type: FailureType
    action: RecoveryAction
    attempt: int
    max_retries: int
    timestamp: str
    evidence_preserved: bool
    error: str
    result: str  # "success", "retry_exhausted", "aborted", "waiting"
    hash: str

# ═══════════════════════════════════════════════════════
# RECOVERY ENGINE
# ═══════════════════════════════════════════════════════

class RecoveryEngine:
    """Automated recovery: classify → decide → act → record."""
    
    def __init__(self, evidence_pipeline: EvidencePipeline = None):
        self.evidence = evidence_pipeline or EvidencePipeline()
        self.audit_trail: list[RecoveryRecord] = []
        self.retry_counts: dict[str, int] = {}  # task_id → attempts
        self._recovery_seq = 0
    
    # ── CLASSIFY ───────────────────────────────────────
    
    def classify(self, error: str) -> FailureType:
        """Classify failure from error message."""
        error_lower = error.lower()
        
        if "crash" in error_lower or "segfault" in error_lower:
            return FailureType.AGENT_CRASH
        if "timeout" in error_lower or "timed out" in error_lower:
            return FailureType.HTTP_TIMEOUT if "http" in error_lower else FailureType.UNKNOWN
        if "not recognized" in error_lower or "not found" in error_lower:
            return FailureType.SHELL_COMMAND_FAILED
        if "404" in error_lower or "500" in error_lower or "http error" in error_lower:
            return FailureType.HTTP_ERROR
        if "playwright" in error_lower or "browser" in error_lower:
            return FailureType.BROWSER_FAILURE
        if "python" in error_lower or "traceback" in error_lower or "syntaxerror" in error_lower:
            return FailureType.PYTHON_ERROR
        if "file" in error_lower or "permission" in error_lower or "no such file" in error_lower:
            return FailureType.FILE_ERROR
        if "state" in error_lower or "invalid" in error_lower:
            return FailureType.INVALID_STATE
        if "dependency" in error_lower or "missing" in error_lower:
            return FailureType.MISSING_DEPENDENCY
        if "interrupt" in error_lower:
            return FailureType.INTERRUPTED
        
        return FailureType.UNKNOWN
    
    # ── DECIDE ─────────────────────────────────────────
    
    def decide(self, failure_type: FailureType, task_id: str) -> RecoveryAction:
        """Determine recovery action from policy."""
        policy = RECOVERY_POLICY.get(failure_type, RECOVERY_POLICY[FailureType.UNKNOWN])
        
        # Only check retry exhaustion for retry-type actions
        if policy["action"] in (RecoveryAction.RETRY, RecoveryAction.RETRY_WITH_BACKOFF):
            attempts = self.retry_counts.get(task_id, 0)
            if attempts >= policy["max_retries"]:
                return RecoveryAction.SKIP
        
        return policy["action"]
    
    # ── EXECUTE ────────────────────────────────────────
    
    def recover(self, mission_id: str, task_id: str, error: str, 
                dispatcher=None) -> RecoveryRecord:
        """Full recovery cycle: classify → decide → act → record."""
        
        failure_type = self.classify(error)
        action = self.decide(failure_type, task_id)
        self.retry_counts[task_id] = self.retry_counts.get(task_id, 0) + 1
        
        self._recovery_seq += 1
        policy = RECOVERY_POLICY[failure_type]
        
        # Execute recovery action
        result = "success"
        if action == RecoveryAction.RETRY or action == RecoveryAction.RETRY_WITH_BACKOFF:
            # Reset task state to QUEUED → READY for retry
            if dispatcher and task_id in dispatcher.tasks:
                task = dispatcher.tasks[task_id]
                # Re-queue for retry
                if task.state.value in ("failed", "paused"):
                    # Use the task's own transition method
                    task.error = ""
                    # Move to queued then ready
                    from dispatch import TaskState
                    task.transition(TaskState.QUEUED)
                    task.transition(TaskState.READY)
            
            if self.retry_counts[task_id] > policy["max_retries"]:
                action = RecoveryAction.SKIP
                result = "retry_exhausted"
        
        elif action == RecoveryAction.SKIP:
            result = "skipped"
        elif action == RecoveryAction.ABORT_MISSION:
            result = "aborted"
        elif action == RecoveryAction.WAIT_DEPENDENCY:
            result = "waiting"
        
        # Record decision
        record = RecoveryRecord(
            recovery_id=f"REC-{self._recovery_seq:06d}",
            mission_id=mission_id,
            task_id=task_id,
            failure_type=failure_type,
            action=action if result != "retry_exhausted" else RecoveryAction.SKIP,
            attempt=self.retry_counts[task_id],
            max_retries=policy["max_retries"],
            timestamp=datetime.now(timezone.utc).isoformat(),
            evidence_preserved=policy["preserve_evidence"],
            error=error,
            result=result,
            hash="",
        )
        record.hash = self._hash_record(record)
        self.audit_trail.append(record)
        
        # Ingest into evidence pipeline
        self.evidence.ingest_error(mission_id, task_id, None, error, "MC-0006")
        
        return record
    
    # ── AUDIT ──────────────────────────────────────────
    
    def audit_log(self, mission_id: str = None) -> list[RecoveryRecord]:
        if mission_id:
            return [r for r in self.audit_trail if r.mission_id == mission_id]
        return self.audit_trail
    
    def status(self) -> dict:
        by_type = {}
        for r in self.audit_trail:
            key = r.failure_type.value
            by_type[key] = by_type.get(key, 0) + 1
        
        by_action = {}
        for r in self.audit_trail:
            key = r.action.value
            by_action[key] = by_action.get(key, 0) + 1
        
        return {
            "total_recoveries": len(self.audit_trail),
            "by_failure_type": by_type,
            "by_action": by_action,
            "retry_counts": self.retry_counts,
        }
    
    def _hash_record(self, record: RecoveryRecord) -> str:
        content = json.dumps({
            "recovery_id": record.recovery_id,
            "mission_id": record.mission_id,
            "task_id": record.task_id,
            "failure_type": record.failure_type.value,
            "action": record.action.value,
            "attempt": record.attempt,
            "error": record.error,
            "result": record.result,
        }, sort_keys=True)
        return hashlib.sha256(content.encode()).hexdigest()[:16]
