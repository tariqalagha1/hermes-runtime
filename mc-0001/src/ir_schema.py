"""
MC-0001 Mission Compiler — Mission IR Schema
The Intermediate Representation produced by the compiler.
"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Optional
import json, hashlib
from datetime import datetime, timezone

class TaskType(str, Enum):
    ARCHITECTURE = "architecture"
    IMPLEMENTATION = "implementation"
    INTEGRATION = "integration"
    CERTIFICATION = "certification"
    REPORTING = "reporting"

class DependencyType(str, Enum):
    HARD = "hard"       # Must complete before dependent starts
    SOFT = "soft"       # Prefer before, but not blocking
    INTERFACE = "interface"  # Output contract required

class ConstraintType(str, Enum):
    PARALLEL_OK = "parallel_ok"
    SEQUENTIAL_ONLY = "sequential_only"
    ATOMIC = "atomic"
    REUSE_REQUIRED = "reuse_required"

@dataclass
class AtomicTask:
    id: str
    name: str
    type: TaskType
    description: str
    estimated_complexity: int  # 1-13 Fibonacci
    required_capabilities: list[str] = field(default_factory=list)
    required_interfaces: list[str] = field(default_factory=list)
    constraints: list[ConstraintType] = field(default_factory=list)

@dataclass
class Dependency:
    source: str  # task_id that must complete first
    target: str  # task_id that depends on source
    type: DependencyType = DependencyType.HARD

@dataclass
class ParallelGroup:
    id: str
    tasks: list[str]
    max_concurrency: int = 3

@dataclass
class MissionIR:
    mission_id: str
    version: str
    created_at: str
    tasks: dict[str, AtomicTask]
    dependencies: list[Dependency]
    parallel_groups: list[ParallelGroup]
    critical_path: list[str]
    capabilities_required: list[str]
    interfaces_required: list[str]
    total_tasks: int
    estimated_story_points: int
    validation_passed: bool
    validation_errors: list[str]
    ir_hash: str

    def to_json(self) -> str:
        return json.dumps(self._to_dict(), indent=2)

    def _to_dict(self) -> dict:
        d = asdict(self)
        d['tasks'] = {k: asdict(v) for k, v in self.tasks.items()}
        return d

    def compute_hash(self) -> str:
        return hashlib.sha256(self.to_json().encode()).hexdigest()[:16]
