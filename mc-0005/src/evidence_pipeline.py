"""
MC-0005 Evidence Pipeline — captures, normalizes, stores, hashes, exposes
execution evidence. Integrates with Agent Runtime + Dispatcher.
"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Optional
import json, hashlib, os

# ═══════════════════════════════════════════════════════
# EVIDENCE SCHEMA
# ═══════════════════════════════════════════════════════

class EvidenceType:
    TASK = "task"
    AGENT = "agent"
    TOOL = "tool"
    STATE = "state_transition"
    FILE = "file"
    HTTP = "http"
    SHELL = "shell"
    BROWSER = "browser"
    ERROR = "error"
    TIMING = "timing"

@dataclass
class EvidenceRecord:
    evidence_id: str
    type: str
    mission_id: str
    task_id: str
    agent_id: Optional[str]
    source: str  # component that produced it
    timestamp: str
    data: dict
    hash: str
    previous_hash: Optional[str]  # chain link
    sequence: int
    
    def to_dict(self) -> dict:
        return asdict(self)

@dataclass
class EvidenceManifest:
    mission_id: str
    total_records: int
    records_by_type: dict[str, int]
    records_by_task: dict[str, int]
    chain_head_hash: str
    chain_valid: bool
    verified_count: int
    corrupted_count: int

# ═══════════════════════════════════════════════════════
# EVIDENCE PIPELINE
# ═══════════════════════════════════════════════════════

class EvidencePipeline:
    """Immutable evidence chain. Integrates with Agent Runtime."""
    
    def __init__(self, storage_dir: str = None):
        self.storage_dir = storage_dir or os.path.join(
            os.path.dirname(__file__), "..", "evidence_store"
        )
        os.makedirs(self.storage_dir, exist_ok=True)
        self.chains: dict[str, list[EvidenceRecord]] = {}  # mission_id → chain
        self._sequence = 0
    
    # ── INGEST ────────────────────────────────────────
    
    def ingest_agent_evidence(self, mission_id: str, agent_evidence) -> EvidenceRecord:
        """Accept evidence from Agent Runtime."""
        return self._record(
            mission_id=mission_id,
            task_id=agent_evidence.task_id,
            agent_id=agent_evidence.agent_id,
            evidence_type=EvidenceType.AGENT,
            source="MC-0004",
            data={
                "goal": agent_evidence.goal,
                "tools_used": agent_evidence.tools_used,
                "duration_ms": agent_evidence.duration_ms,
                "result": agent_evidence.result,
                "errors": agent_evidence.errors,
                "evidence_hash": agent_evidence.evidence_hash,
            }
        )
    
    def ingest_task_state(self, mission_id: str, task_id: str, 
                          old_state: str, new_state: str, 
                          source: str = "MC-0003") -> EvidenceRecord:
        """Record state transitions from Dispatcher."""
        return self._record(
            mission_id=mission_id,
            task_id=task_id,
            agent_id=None,
            evidence_type=EvidenceType.STATE,
            source=source,
            data={"old_state": old_state, "new_state": new_state}
        )
    
    def ingest_tool_result(self, mission_id: str, task_id: str, agent_id: str,
                           tool_name: str, result: dict) -> EvidenceRecord:
        """Record tool execution result."""
        return self._record(
            mission_id=mission_id,
            task_id=task_id,
            agent_id=agent_id,
            evidence_type=EvidenceType.TOOL,
            source="MC-0004",
            data={"tool": tool_name, "result": result}
        )
    
    def ingest_error(self, mission_id: str, task_id: str, agent_id: str,
                     error: str, source: str) -> EvidenceRecord:
        """Record execution error."""
        return self._record(
            mission_id=mission_id,
            task_id=task_id,
            agent_id=agent_id,
            evidence_type=EvidenceType.ERROR,
            source=source,
            data={"error": error}
        )
    
    # ── CORE ──────────────────────────────────────────
    
    def _record(self, mission_id: str, task_id: str, agent_id: Optional[str],
                evidence_type: str, source: str, data: dict) -> EvidenceRecord:
        """Create immutable evidence record with hash chain."""
        self._sequence += 1
        chain = self.chains.setdefault(mission_id, [])
        
        previous_hash = chain[-1].hash if chain else None
        
        timestamp = datetime.now(timezone.utc).isoformat()
        
        record = EvidenceRecord(
            evidence_id=f"EV-{self._sequence:06d}",
            type=evidence_type,
            mission_id=mission_id,
            task_id=task_id,
            agent_id=agent_id,
            source=source,
            timestamp=timestamp,
            data=data,
            hash="",
            previous_hash=previous_hash,
            sequence=self._sequence,
        )
        
        # Compute hash
        record.hash = self._hash_record(record)
        chain.append(record)
        
        return record
    
    # ── RETRIEVE ──────────────────────────────────────
    
    def by_mission(self, mission_id: str) -> list[EvidenceRecord]:
        return self.chains.get(mission_id, [])
    
    def by_task(self, mission_id: str, task_id: str) -> list[EvidenceRecord]:
        return [r for r in self.by_mission(mission_id) if r.task_id == task_id]
    
    def by_agent(self, mission_id: str, agent_id: str) -> list[EvidenceRecord]:
        return [r for r in self.by_mission(mission_id) if r.agent_id == agent_id]
    
    def by_type(self, mission_id: str, evidence_type: str) -> list[EvidenceRecord]:
        return [r for r in self.by_mission(mission_id) if r.type == evidence_type]
    
    def latest(self, mission_id: str) -> Optional[EvidenceRecord]:
        chain = self.chains.get(mission_id, [])
        return chain[-1] if chain else None
    
    # ── MANIFEST ──────────────────────────────────────
    
    def manifest(self, mission_id: str) -> EvidenceManifest:
        chain = self.chains.get(mission_id, [])
        
        # Count by type
        by_type = {}
        for r in chain:
            by_type[r.type] = by_type.get(r.type, 0) + 1
        
        # Count by task
        by_task = {}
        for r in chain:
            by_task[r.task_id] = by_task.get(r.task_id, 0) + 1
        
        # Verify chain integrity
        verified = 0
        corrupted = 0
        for i, r in enumerate(chain):
            expected = self._hash_record(r)
            if expected == r.hash:
                verified += 1
            else:
                corrupted += 1
        
        chain_valid = corrupted == 0 and (
            len(chain) == 0 or all(
                chain[i].previous_hash == (chain[i-1].hash if i > 0 else None)
                for i in range(len(chain))
            )
        )
        
        return EvidenceManifest(
            mission_id=mission_id,
            total_records=len(chain),
            records_by_type=by_type,
            records_by_task=by_task,
            chain_head_hash=chain[-1].hash if chain else "",
            chain_valid=chain_valid,
            verified_count=verified,
            corrupted_count=corrupted,
        )
    
    # ── HELPERS ───────────────────────────────────────
    
    def _hash_record(self, record: EvidenceRecord) -> str:
        """Deterministic SHA-256 hash of record content."""
        content = json.dumps({
            "evidence_id": record.evidence_id,
            "type": record.type,
            "mission_id": record.mission_id,
            "task_id": record.task_id,
            "agent_id": record.agent_id,
            "source": record.source,
            "timestamp": record.timestamp,
            "data": record.data,
            "previous_hash": record.previous_hash,
            "sequence": record.sequence,
        }, sort_keys=True, default=str)
        return hashlib.sha256(content.encode()).hexdigest()[:16]
    
    def status(self) -> dict:
        total = sum(len(c) for c in self.chains.values())
        return {
            "missions": len(self.chains),
            "total_records": total,
            "sequence": self._sequence,
            "missions_list": list(self.chains.keys()),
        }
