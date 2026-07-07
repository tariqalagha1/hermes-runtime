"""
MC-0002 Mission Scheduler — Schedule Schema
Consumes Mission IR from MC-0001, produces Mission Schedule.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
import json, hashlib
from datetime import datetime, timezone

class QueueType(str, Enum):
    READY = "ready"
    BLOCKED = "blocked"  
    WAITING = "waiting"
    COMPLETED = "completed"

class ResourceKind(str, Enum):
    CPU = "cpu"
    MEMORY = "memory"
    DISK = "disk"
    NETWORK = "network"

@dataclass
class ScheduledTask:
    task_id: str
    task_name: str
    wave: int
    batch: int
    queue: QueueType
    dependencies_remaining: list[str]
    estimated_start_min: int
    estimated_duration_min: int
    resources: dict[str, float]

@dataclass
class ParallelBatch:
    batch_id: str
    wave: int
    tasks: list[str]
    max_concurrency: int
    estimated_duration_min: int

@dataclass
class ExecutionWave:
    wave: int
    batches: list[ParallelBatch]
    total_tasks: int
    estimated_duration_min: int
    dependencies_released: list[str]

@dataclass
class ResourceEstimate:
    total_cpu_core_minutes: float
    total_memory_mb_minutes: float
    peak_concurrent_tasks: int
    peak_memory_mb_estimate: float

@dataclass
class MissionSchedule:
    mission_id: str
    version: str
    created_at: str
    ir_hash: str
    
    # Queues
    ready_queue: list[str]
    blocked_queue: list[str]
    waiting_queue: list[str]
    completed_queue: list[str]
    
    # Execution plan
    waves: list[ExecutionWave]
    batches: list[ParallelBatch]
    critical_path: list[str]
    critical_path_duration_min: int
    
    # Estimates
    total_tasks: int
    total_waves: int
    total_batches: int
    estimated_total_minutes: int
    resources: ResourceEstimate
    
    # Validation
    valid: bool
    validation_errors: list[str]
    deadlocks_detected: list[str]
    schedule_hash: str
    
    def to_json(self) -> str:
        from dataclasses import asdict
        d = asdict(self)
        d['waves'] = [asdict(w) for w in self.waves]
        d['batches'] = [asdict(b) for b in self.batches]
        d['resources'] = asdict(self.resources)
        return json.dumps(d, indent=2, default=str)
    
    def compute_hash(self) -> str:
        return hashlib.sha256(self.to_json().encode()).hexdigest()[:16]
