"""
MC-0002 Mission Scheduler — 9-stage pipeline.
Transforms Mission IR → Mission Schedule.
No execution. No agents. Scheduling only.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../mc-0001/src'))
sys.path.insert(0, os.path.dirname(__file__))

from datetime import datetime, timezone
from collections import deque
from schedule_schema import (
    MissionSchedule, ScheduledTask, ParallelBatch, ExecutionWave,
    ResourceEstimate, QueueType
)

# Default resource costs per task
DEFAULT_CPU_MIN = 2.0
DEFAULT_MEM_MB = 256.0

class MissionScheduler:
    """9-stage scheduler: Mission IR → Mission Schedule."""

    def schedule(self, ir) -> MissionSchedule:
        """Run all 9 stages."""
        self.ir = ir
        self.errors: list[str] = []
        self.deadlocks: list[str] = []
        
        loaded     = self._stage1_load(ir)
        resolved   = self._stage2_resolve_dependencies(loaded)
        ready      = self._stage3_generate_ready(resolved)
        batches    = self._stage4_build_batches(ready, resolved)
        waves      = self._stage5_plan_waves(batches)
        critical   = self._stage6_schedule_critical_path(waves)
        resources  = self._stage7_estimate_resources(waves)
        schedule   = self._stage8_generate(resolved, batches, waves, critical, resources)
        validated  = self._stage9_validate(schedule)
        
        return validated

    # ── Stage 1: Load IR ─────────────────────────────────

    def _stage1_load(self, ir) -> dict:
        if not ir.validation_passed:
            self.errors.append("Input Mission IR is not validated")
        return {
            'mission_id': ir.mission_id,
            'tasks': dict(ir.tasks),
            'dependencies': [(d.source, d.target) for d in ir.dependencies],
            'parallel_groups': [(pg.id, pg.tasks, pg.max_concurrency) for pg in ir.parallel_groups],
            'critical_path': list(ir.critical_path),
            'total_tasks': ir.total_tasks,
            'story_points': ir.estimated_story_points,
            'ir_hash': ir.ir_hash,
            'capabilities': list(ir.capabilities_required),
        }

    # ── Stage 2: Dependency Resolution ───────────────────

    def _stage2_resolve_dependencies(self, loaded: dict) -> dict:
        tasks = loaded['tasks']
        deps = loaded['dependencies']
        
        # Build in-degree and adjacency
        in_degree = {tid: 0 for tid in tasks}
        adj = {tid: [] for tid in tasks}
        
        for src, tgt in deps:
            if src in in_degree and tgt in in_degree:
                in_degree[tgt] += 1
                adj.setdefault(src, []).append(tgt)
        
        # Detect cycles
        if self._has_cycle(adj):
            self.deadlocks.append("Dependency cycle detected")
        
        # Task state
        task_states = {}
        for tid in tasks:
            deps_remaining = [(s, t) for s, t in deps if t == tid]
            task_states[tid] = {
                'name': tasks[tid].name,
                'complexity': tasks[tid].estimated_complexity,
                'deps_total': len(deps_remaining),
                'deps_remaining': [s for s, _ in deps_remaining],
                'dependents': adj.get(tid, []),
            }
        
        loaded['task_states'] = task_states
        loaded['in_degree'] = in_degree
        loaded['adj'] = adj
        return loaded

    # ── Stage 3: Ready Queue Generator ───────────────────

    def _stage3_generate_ready(self, resolved: dict) -> dict:
        in_degree = dict(resolved['in_degree'])
        task_states = resolved['task_states']
        
        ready = [tid for tid, deg in in_degree.items() if deg == 0]
        blocked = [tid for tid, deg in in_degree.items() if deg > 0]
        
        resolved['ready_queue'] = ready
        resolved['blocked_queue'] = blocked
        resolved['waiting_queue'] = []
        resolved['completed_queue'] = []
        return resolved

    # ── Stage 4: Parallel Batch Builder ──────────────────

    def _stage4_build_batches(self, ready_data: dict, resolved: dict) -> list[dict]:
        in_degree = dict(resolved['in_degree'])
        adj = resolved['adj']
        task_states = resolved['task_states']
        max_concurrent = 3
        
        batches = []
        processed = 0
        total = len(in_degree)
        
        queue = deque([tid for tid, deg in in_degree.items() if deg == 0])
        visited = set()
        wave_num = 1
        batch_num = 1
        
        while processed < total:
            if not queue and len(visited) < total:
                # Deadlock: remaining tasks have unresolved deps
                remaining = [t for t in in_degree if t not in visited]
                self.deadlocks.append(f"Deadlock: {len(remaining)} tasks cannot be scheduled")
                break
            
            # Take up to max_concurrent from queue for this batch
            batch_tasks = []
            for _ in range(min(len(queue), max_concurrent)):
                tid = queue.popleft()
                batch_tasks.append(tid)
            
            processed += len(batch_tasks)
            
            # Compute batch duration = max complexity of tasks in batch
            batch_duration = max(
                (task_states[t]['complexity'] for t in batch_tasks),
                default=1
            )
            
            batches.append({
                'batch_id': f'B-{batch_num}',
                'wave': wave_num,
                'tasks': batch_tasks,
                'max_concurrency': len(batch_tasks),
                'duration_min': batch_duration,
            })
            
            # Release dependents
            for tid in batch_tasks:
                visited.add(tid)
                for dep in adj.get(tid, []):
                    in_degree[dep] -= 1
                    if in_degree[dep] == 0:
                        queue.append(dep)
            
            batch_num += 1
            if not queue and processed < total:
                wave_num += 1
        
        return batches

    # ── Stage 5: Wave Planner ────────────────────────────

    def _stage5_plan_waves(self, batches: list[dict]) -> list[dict]:
        waves_dict = {}
        for b in batches:
            w = b['wave']
            waves_dict.setdefault(w, []).append(b)
        
        waves = []
        for w in sorted(waves_dict):
            w_batches = waves_dict[w]
            waves.append({
                'wave': w,
                'batches': w_batches,
                'total_tasks': sum(len(b['tasks']) for b in w_batches),
                'duration_min': sum(b['duration_min'] for b in w_batches),
                'dependencies_released': [],
            })
        
        return waves

    # ── Stage 6: Critical Path Scheduler ─────────────────

    def _stage6_schedule_critical_path(self, waves: list[dict]) -> list[str]:
        # Critical path from the IR — tasks that form the longest chain
        cp = list(self.ir.critical_path)
        cp_duration = sum(
            self.ir.tasks[tid].estimated_complexity 
            for tid in cp if tid in self.ir.tasks
        )
        return cp

    # ── Stage 7: Resource Estimator ──────────────────────

    def _stage7_estimate_resources(self, waves: list[dict]) -> dict:
        total_cpu = 0.0
        total_mem = 0.0
        peak_tasks = 0
        peak_mem = 0.0
        
        for w in waves:
            for b in w['batches']:
                ntasks = len(b['tasks'])
                duration = b['duration_min']
                total_cpu += ntasks * duration * DEFAULT_CPU_MIN
                total_mem += ntasks * duration * DEFAULT_MEM_MB
                if ntasks > peak_tasks:
                    peak_tasks = ntasks
                    peak_mem = ntasks * DEFAULT_MEM_MB
        
        return {
            'total_cpu_core_minutes': round(total_cpu, 1),
            'total_memory_mb_minutes': round(total_mem, 1),
            'peak_concurrent_tasks': peak_tasks,
            'peak_memory_mb_estimate': round(peak_mem, 1),
        }

    # ── Stage 8: Schedule Generator ──────────────────────

    def _stage8_generate(self, resolved, batches, waves, critical, resources) -> MissionSchedule:
        ready = resolved.get('ready_queue', [])
        blocked = resolved.get('blocked_queue', [])
        
        # Convert waves to ExecutionWave objects
        wave_objects = []
        all_batches = []
        total_min = 0
        
        for w in waves:
            w_batches = []
            for b in w['batches']:
                pb = ParallelBatch(
                    batch_id=b['batch_id'],
                    wave=b['wave'],
                    tasks=b['tasks'],
                    max_concurrency=b['max_concurrency'],
                    estimated_duration_min=b['duration_min'],
                )
                w_batches.append(pb)
                all_batches.append(pb)
                total_min += b['duration_min']
            
            wave_objects.append(ExecutionWave(
                wave=w['wave'],
                batches=w_batches,
                total_tasks=w['total_tasks'],
                estimated_duration_min=w['duration_min'],
                dependencies_released=w['dependencies_released'],
            ))
        
        cp_duration = sum(
            self.ir.tasks[t].estimated_complexity 
            for t in critical if t in self.ir.tasks
        ) if critical else 0
        
        return MissionSchedule(
            mission_id=self.ir.mission_id,
            version='1.0.0',
            created_at=datetime.now(timezone.utc).isoformat(),
            ir_hash=self.ir.ir_hash,
            ready_queue=ready,
            blocked_queue=blocked,
            waiting_queue=resolved.get('waiting_queue', []),
            completed_queue=resolved.get('completed_queue', []),
            waves=wave_objects,
            batches=all_batches,
            critical_path=critical,
            critical_path_duration_min=cp_duration,
            total_tasks=self.ir.total_tasks,
            total_waves=len(wave_objects),
            total_batches=len(all_batches),
            estimated_total_minutes=total_min,
            resources=ResourceEstimate(**resources),
            valid=False,
            validation_errors=[],
            deadlocks_detected=list(self.deadlocks),
            schedule_hash='',
        )
    
    # ── Stage 9: Schedule Validator ──────────────────────

    def _stage9_validate(self, schedule: MissionSchedule) -> MissionSchedule:
        errors = []
        
        # Every task in a batch
        scheduled_tasks = set()
        for b in schedule.batches:
            scheduled_tasks.update(b.tasks)
        
        task_ids = set(self.ir.tasks.keys())
        missing = task_ids - scheduled_tasks
        if missing:
            errors.append(f"Tasks not scheduled: {missing}")
        
        # No task appears in multiple batches
        all_scheduled = []
        for b in schedule.batches:
            all_scheduled.extend(b.tasks)
        duplicates = [t for t in all_scheduled if all_scheduled.count(t) > 1]
        if duplicates:
            errors.append(f"Duplicate tasks in schedule: {set(duplicates)}")
        
        # Critical path present
        if not schedule.critical_path:
            errors.append("No critical path in schedule")
        
        # Waves in order
        for i in range(1, len(schedule.waves)):
            if schedule.waves[i].wave <= schedule.waves[i-1].wave:
                errors.append("Waves not in ascending order")
        
        schedule.validation_errors = errors + self.errors
        schedule.deadlocks_detected = list(self.deadlocks)
        schedule.valid = len(errors) == 0 and len(self.deadlocks) == 0
        schedule.schedule_hash = schedule.compute_hash()
        
        return schedule

    # ── Helpers ──────────────────────────────────────────

    def _has_cycle(self, adj: dict) -> bool:
        WHITE, GRAY, BLACK = 0, 1, 2
        color = {n: WHITE for n in adj}
        
        def dfs(node):
            color[node] = GRAY
            for neighbor in adj.get(node, []):
                if color.get(neighbor) == GRAY:
                    return True
                if color.get(neighbor) == WHITE and dfs(neighbor):
                    return True
            color[node] = BLACK
            return False
        
        for n in adj:
            if color.get(n) == WHITE and dfs(n):
                return True
        return False
