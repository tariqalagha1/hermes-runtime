"""
MC-0003 Execution Dispatcher — Task lifecycle state machine.
Bridges Mission Schedule → Execution state tracking.
No workers. No agents. State management only.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
import json, hashlib
from datetime import datetime, timezone

class TaskState(str, Enum):
    QUEUED = "queued"
    READY = "ready"
    BLOCKED = "blocked"
    DISPATCHED = "dispatched"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"

class MissionState(str, Enum):
    CREATED = "created"
    SCHEDULED = "scheduled"
    DISPATCHING = "dispatching"
    EXECUTING = "executing"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"

# Valid state transitions
TRANSITIONS = {
    TaskState.QUEUED:    [TaskState.READY],
    TaskState.READY:     [TaskState.DISPATCHED, TaskState.SKIPPED],
    TaskState.BLOCKED:   [TaskState.READY],
    TaskState.DISPATCHED:[TaskState.RUNNING, TaskState.FAILED],
    TaskState.RUNNING:   [TaskState.COMPLETED, TaskState.FAILED, TaskState.PAUSED],
    TaskState.PAUSED:    [TaskState.RUNNING, TaskState.FAILED, TaskState.SKIPPED],
    TaskState.COMPLETED: [],
    TaskState.FAILED:    [TaskState.QUEUED],
    TaskState.SKIPPED:   [TaskState.QUEUED],
}

@dataclass
class TaskRecord:
    task_id: str
    task_name: str
    state: TaskState
    batch_id: str
    wave: int
    dependencies: list[str]
    dependents: list[str]
    state_history: list[dict] = field(default_factory=list)
    evidence: dict = field(default_factory=dict)
    error: str = ""
    
    def transition(self, new_state: TaskState) -> bool:
        if new_state in TRANSITIONS.get(self.state, []):
            self.state_history.append({
                "from": self.state.value,
                "to": new_state.value,
                "at": datetime.now(timezone.utc).isoformat(),
            })
            self.state = new_state
            return True
        return False


class ExecutionDispatch:
    """Manages task lifecycle from schedule through completion."""
    
    def __init__(self):
        self.mission_state = MissionState.CREATED
        self.tasks: dict[str, TaskRecord] = {}
        self.events: list[dict] = []
        self.errors: list[str] = []
        self.mission_id = ""
        
    def load_schedule(self, schedule) -> None:
        """Load MissionSchedule and create task records."""
        self.mission_id = schedule.mission_id
        self.mission_state = MissionState.SCHEDULED
        
        # Build task records from schedule
        task_deps = {}
        for b in schedule.batches:
            for tid in b.tasks:
                task_deps.setdefault(tid, {"blocked_by": [], "blocks": []})
        
        # Compute dependencies from original schedule
        for b in schedule.batches:
            for tid in b.tasks:
                for other_b in schedule.batches:
                    if other_b.wave < b.wave:
                        task_deps.setdefault(tid, {"blocked_by": [], "blocks": []})
                        task_deps[tid]["blocked_by"].extend(other_b.tasks)
        
        # Create records
        for b in schedule.batches:
            for tid in b.tasks:
                deps = list(set(task_deps.get(tid, {}).get("blocked_by", [])))
                deps = [d for d in deps if d != tid]
                
                is_ready = len(deps) == 0
                initial_state = TaskState.READY if is_ready else TaskState.BLOCKED
                
                self.tasks[tid] = TaskRecord(
                    task_id=tid,
                    task_name=tid,
                    state=initial_state,
                    batch_id=b.batch_id,
                    wave=b.wave,
                    dependencies=deps,
                    dependents=[],
                    state_history=[{
                        "from": "created",
                        "to": initial_state.value,
                        "at": datetime.now(timezone.utc).isoformat(),
                    }],
                )
        
        # Set dependents
        for tid, record in self.tasks.items():
            for other_tid, other in self.tasks.items():
                if tid in other.dependencies:
                    record.dependents.append(other_tid)
        
        self._log_event("schedule_loaded", {"tasks": len(self.tasks)})
    
    def ready_queue(self) -> list[str]:
        """Tasks ready for dispatch."""
        return [tid for tid, t in self.tasks.items() 
                if t.state == TaskState.READY]
    
    def blocked_queue(self) -> list[str]:
        """Tasks blocked by dependencies."""
        return [tid for tid, t in self.tasks.items() 
                if t.state == TaskState.BLOCKED]
    
    def dispatch(self, task_id: str) -> bool:
        """Dispatch a ready task."""
        if task_id not in self.tasks:
            return False
        task = self.tasks[task_id]
        if task.state != TaskState.READY:
            self.errors.append(f"Cannot dispatch {task_id}: state is {task.state.value}")
            return False
        if task.transition(TaskState.DISPATCHED):
            self.mission_state = MissionState.EXECUTING
            self._log_event("task_dispatched", {"task_id": task_id})
            return True
        return False
    
    def start(self, task_id: str) -> bool:
        """Mark dispatched task as running."""
        if task_id not in self.tasks:
            return False
        task = self.tasks[task_id]
        if task.state != TaskState.DISPATCHED:
            return False
        if task.transition(TaskState.RUNNING):
            self._log_event("task_started", {"task_id": task_id})
            return True
        return False
    
    def complete(self, task_id: str, evidence: dict = None) -> bool:
        """Mark running task as completed. Release dependents."""
        if task_id not in self.tasks:
            return False
        task = self.tasks[task_id]
        if task.state != TaskState.RUNNING:
            return False
        task.evidence = evidence or {}
        if task.transition(TaskState.COMPLETED):
            # Release dependents
            for dep_id in task.dependents:
                dep_task = self.tasks.get(dep_id)
                if dep_task and task_id in dep_task.dependencies:
                    dep_task.dependencies.remove(task_id)
                    if not dep_task.dependencies:
                        dep_task.transition(TaskState.READY)
                        self._log_event("dependency_released", {
                            "task_id": dep_id,
                            "released_by": task_id,
                        })
            self._log_event("task_completed", {"task_id": task_id})
            self._check_mission_complete()
            return True
        return False
    
    def pause(self, task_id: str) -> bool:
        """Pause a running task."""
        if task_id not in self.tasks:
            return False
        task = self.tasks[task_id]
        if task.transition(TaskState.PAUSED):
            self._log_event("task_paused", {"task_id": task_id})
            return True
        return False
    
    def resume(self, task_id: str) -> bool:
        """Resume a paused task."""
        if task_id not in self.tasks:
            return False
        task = self.tasks[task_id]
        if task.transition(TaskState.RUNNING):
            self._log_event("task_resumed", {"task_id": task_id})
            return True
        return False
    
    def fail(self, task_id: str, error: str) -> bool:
        """Mark task as failed."""
        if task_id not in self.tasks:
            return False
        task = self.tasks[task_id]
        task.error = error
        if task.transition(TaskState.FAILED):
            self._log_event("task_failed", {"task_id": task_id, "error": error})
            return True
        return False
    
    def _check_mission_complete(self) -> bool:
        """Check if all tasks are completed."""
        all_done = all(
            t.state in (TaskState.COMPLETED, TaskState.SKIPPED) 
            for t in self.tasks.values()
        )
        if all_done:
            self.mission_state = MissionState.COMPLETED
            self._log_event("mission_complete", {"tasks": len(self.tasks)})
        return all_done
    
    def _log_event(self, event_type: str, data: dict) -> None:
        self.events.append({
            "type": event_type,
            "data": data,
            "mission_state": self.mission_state.value,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
    
    def status(self) -> dict:
        """Full execution status."""
        return {
            "mission_id": self.mission_id,
            "mission_state": self.mission_state.value,
            "tasks": {
                "total": len(self.tasks),
                "ready": len(self.ready_queue()),
                "blocked": len(self.blocked_queue()),
                "dispatched": sum(1 for t in self.tasks.values() if t.state == TaskState.DISPATCHED),
                "running": sum(1 for t in self.tasks.values() if t.state == TaskState.RUNNING),
                "paused": sum(1 for t in self.tasks.values() if t.state == TaskState.PAUSED),
                "completed": sum(1 for t in self.tasks.values() if t.state == TaskState.COMPLETED),
                "failed": sum(1 for t in self.tasks.values() if t.state == TaskState.FAILED),
            },
            "events_count": len(self.events),
            "errors": self.errors,
        }
