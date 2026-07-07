"""
MC-0001 Mission Compiler — 9-stage pipeline.
Transforms Mission Specification → Mission IR.
"""
from __future__ import annotations
from collections import deque
from datetime import datetime, timezone
from typing import Optional
import json, re, hashlib

from ir_schema import (
    MissionIR, AtomicTask, Dependency, ParallelGroup,
    TaskType, DependencyType, ConstraintType
)

class MissionCompiler:
    """9-stage compiler transforming mission spec → executable IR."""

    def compile(self, spec: dict) -> MissionIR:
        """Run all 9 stages sequentially."""
        self.spec = spec
        self.errors: list[str] = []

        parsed      = self._stage1_parse(spec)
        constraints = self._stage2_analyze_constraints(parsed)
        caps        = self._stage3_extract_capabilities(parsed)
        deps_graph  = self._stage4_build_dependency_graph(parsed, constraints)
        tasks       = self._stage5_decompose_atomic(parsed, deps_graph)
        parallel    = self._stage6_analyze_parallelism(tasks, deps_graph)
        critical    = self._stage7_critical_path(tasks, deps_graph)
        ir          = self._stage8_generate_ir(tasks, deps_graph, parallel, critical, caps)
        validated   = self._stage9_validate(ir)

        return validated

    # ── Stage 1: Parse ──────────────────────────────────

    def _stage1_parse(self, spec: dict) -> dict:
        required = ['mission_id', 'title', 'objectives', 'deliverables']
        for field in required:
            if field not in spec:
                self.errors.append(f"Missing required field: {field}")
        return {
            'mission_id': spec.get('mission_id', 'UNKNOWN'),
            'title': spec.get('title', ''),
            'objectives': spec.get('objectives', []),
            'deliverables': spec.get('deliverables', []),
            'workstreams': spec.get('workstreams', []),
            'quality_gates': spec.get('quality_gates', []),
            'dependencies': spec.get('dependencies', []),
            'constraints': spec.get('constraints', []),
        }

    # ── Stage 2: Constraint Analysis ────────────────────

    def _stage2_analyze_constraints(self, parsed: dict) -> list[ConstraintType]:
        constraints: list[ConstraintType] = []
        raw = parsed.get('constraints', [])

        for c in raw:
            c_lower = c.lower() if isinstance(c, str) else ''
            if 'parallel' in c_lower:
                constraints.append(ConstraintType.PARALLEL_OK)
            if 'sequential' in c_lower:
                constraints.append(ConstraintType.SEQUENTIAL_ONLY)
            if 'atomic' in c_lower:
                constraints.append(ConstraintType.ATOMIC)
            if 'reuse' in c_lower:
                constraints.append(ConstraintType.REUSE_REQUIRED)

        if not constraints:
            constraints.append(ConstraintType.PARALLEL_OK)

        return constraints

    # ── Stage 3: Capability Extraction ──────────────────

    def _stage3_extract_capabilities(self, parsed: dict) -> list[str]:
        caps = set()
        text = json.dumps(parsed).lower()

        capability_keywords = {
            'architecture': 'architecture',
            'implementation': 'implementation',
            'integration': 'integration',
            'certification': 'certification',
            'reporting': 'reporting',
            'database': 'persistence',
            'deployment': 'deployment',
            'security': 'security',
            'testing': 'testing',
            'agent': 'agent_runtime',
            'scheduler': 'scheduler',
        }

        for keyword, cap in capability_keywords.items():
            if keyword in text:
                caps.add(cap)

        return sorted(caps)

    # ── Stage 4: Dependency Graph ───────────────────────

    def _stage4_build_dependency_graph(self, parsed: dict, constraints: list[ConstraintType]) -> dict:
        deps: dict[str, list[str]] = {}
        workstreams = parsed.get('workstreams', [])
        deliverables = parsed.get('deliverables', [])
        raw_deps = parsed.get('dependencies', [])

        # Initialize graph nodes from deliverables
        for d in deliverables:
            node_id = self._slug(d) if isinstance(d, str) else self._slug(d.get('name', str(d)))
            deps[node_id] = []

        # Parse explicit dependencies — slug both ends
        for dep in raw_deps:
            if isinstance(dep, dict):
                source = self._slug(dep.get('from', ''))
                target = self._slug(dep.get('to', ''))
                if source and target and source != target:
                    deps.setdefault(source, []).append(target)

        # Add implicit dependencies: certification depends on everything
        cert_tasks = [n for n in deps if 'certif' in n.lower()]
        for node in deps:
            if 'certif' not in node.lower() and cert_tasks:
                deps.setdefault(node, []).append(cert_tasks[0])

        return deps

    # ── Stage 5: Atomic Decomposition ───────────────────

    def _stage5_decompose_atomic(self, parsed: dict, deps: dict) -> dict[str, AtomicTask]:
        tasks: dict[str, AtomicTask] = {}
        deliverables = parsed.get('deliverables', [])
        counter = 0

        for d in deliverables:
            name = d if isinstance(d, str) else d.get('name', str(d))
            task_id = self._slug(name)
            counter += 1

            # Determine task type from name
            task_type = TaskType.IMPLEMENTATION
            name_lower = name.lower()
            if 'architecture' in name_lower or 'design' in name_lower:
                task_type = TaskType.ARCHITECTURE
            elif 'integration' in name_lower:
                task_type = TaskType.INTEGRATION
            elif 'certif' in name_lower or 'report' in name_lower:
                task_type = TaskType.CERTIFICATION
            elif 'report' in name_lower:
                task_type = TaskType.REPORTING

            tasks[task_id] = AtomicTask(
                id=task_id,
                name=name,
                type=task_type,
                description=f"Deliver: {name}",
                estimated_complexity=min(counter % 13 + 1, 13),
                required_capabilities=self._guess_capabilities(name_lower),
                required_interfaces=[],
                constraints=[ConstraintType.ATOMIC],
            )

        return tasks

    # ── Stage 6: Parallelism Analysis ───────────────────

    def _stage6_analyze_parallelism(self, tasks: dict[str, AtomicTask], deps: dict) -> list[ParallelGroup]:
        # Topological sort to group independent tasks
        in_degree = {t: 0 for t in tasks}
        adj: dict[str, list[str]] = {t: [] for t in tasks}

        for node, children in deps.items():
            if node not in adj:
                adj[node] = []
            for child in children:
                if child in in_degree:
                    in_degree[child] = in_degree.get(child, 0) + 1
                    adj.setdefault(node, []).append(child)

        # Kahn's algorithm for topological levels
        queue = deque([t for t in in_degree if in_degree[t] == 0])
        groups: list[ParallelGroup] = []
        processed = 0

        while queue:
            group_size = len(queue)
            group_tasks = []
            for _ in range(group_size):
                node = queue.popleft()
                group_tasks.append(node)
                processed += 1
                for neighbor in adj.get(node, []):
                    in_degree[neighbor] -= 1
                    if in_degree[neighbor] == 0:
                        queue.append(neighbor)

            if group_tasks:
                groups.append(ParallelGroup(
                    id=f"PG-{len(groups)+1}",
                    tasks=group_tasks,
                    max_concurrency=min(len(group_tasks), 3),
                ))

        return groups

    # ── Stage 7: Critical Path ──────────────────────────

    def _stage7_critical_path(self, tasks: dict[str, AtomicTask], deps: dict) -> list[str]:
        """Longest path through the dependency DAG by complexity weight."""
        if not tasks:
            return []

        # Forward topological order
        in_degree = {t: 0 for t in tasks}
        adj: dict[str, list[str]] = {t: [] for t in tasks}

        for node, children in deps.items():
            if node not in adj:
                adj[node] = []
            for child in children:
                if child in in_degree:
                    in_degree[child] += 1
                    adj.setdefault(node, []).append(child)

        queue = deque([t for t in in_degree if in_degree[t] == 0])
        topo_order = []
        while queue:
            node = queue.popleft()
            topo_order.append(node)
            for neighbor in adj.get(node, []):
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        # Longest path (DP)
        dist = {t: tasks[t].estimated_complexity for t in tasks}
        prev = {t: None for t in tasks}

        for u in topo_order:
            for v in adj.get(u, []):
                if v in dist and dist[v] < dist[u] + tasks[v].estimated_complexity:
                    dist[v] = dist[u] + tasks[v].estimated_complexity
                    prev[v] = u

        # Trace back from max distance
        end = max(dist, key=dist.get) if dist else None
        path = []
        curr = end
        while curr:
            path.append(curr)
            curr = prev.get(curr)
        path.reverse()

        return path

    # ── Stage 8: IR Generation ──────────────────────────

    def _stage8_generate_ir(self, tasks, deps_graph, parallel, critical, caps) -> MissionIR:
        dep_objects = []
        for node, children in deps_graph.items():
            for child in children:
                dep_objects.append(Dependency(source=node, target=child, type=DependencyType.HARD))

        total_sp = sum(t.estimated_complexity for t in tasks.values())

        ir = MissionIR(
            mission_id=self.spec.get('mission_id', 'UNKNOWN'),
            version='1.0.0',
            created_at=datetime.now(timezone.utc).isoformat(),
            tasks=tasks,
            dependencies=dep_objects,
            parallel_groups=parallel,
            critical_path=critical,
            capabilities_required=caps,
            interfaces_required=self._extract_interfaces(tasks),
            total_tasks=len(tasks),
            estimated_story_points=total_sp,
            validation_passed=False,
            validation_errors=[],
            ir_hash='',
        )
        ir.ir_hash = ir.compute_hash()
        return ir

    # ── Stage 9: Validation ─────────────────────────────

    def _stage9_validate(self, ir: MissionIR) -> MissionIR:
        errors = []

        # Structural validation
        if ir.total_tasks == 0:
            errors.append("No tasks generated")
        if not ir.critical_path:
            errors.append("No critical path computed")
        if not ir.capabilities_required:
            errors.append("No capabilities identified")

        # Dependency validation
        task_ids = set(ir.tasks.keys())
        for dep in ir.dependencies:
            if dep.source not in task_ids:
                errors.append(f"Dependency references unknown source: {dep.source}")
            if dep.target not in task_ids:
                errors.append(f"Dependency references unknown target: {dep.target}")

        # Cycle detection
        if self._has_cycle(ir.dependencies):
            errors.append("Circular dependency detected")

        # Parallel group coverage
        parallel_tasks = set()
        for pg in ir.parallel_groups:
            for t in pg.tasks:
                parallel_tasks.add(t)
        missing = task_ids - parallel_tasks
        if missing:
            errors.append(f"Tasks not in any parallel group: {missing}")

        ir.validation_errors = errors + self.errors
        ir.validation_passed = len(ir.validation_errors) == 0
        return ir

    # ── Helpers ─────────────────────────────────────────

    def _slug(self, text: str) -> str:
        return re.sub(r'[^a-z0-9]+', '_', text.lower()).strip('_')

    def _guess_capabilities(self, text: str) -> list[str]:
        caps = []
        if 'implement' in text or 'service' in text:
            caps.append('implementation')
        if 'architect' in text or 'design' in text:
            caps.append('architecture')
        if 'integrat' in text:
            caps.append('integration')
        if 'certif' in text:
            caps.append('certification')
        if 'report' in text:
            caps.append('reporting')
        if 'database' in text or 'schema' in text:
            caps.append('persistence')
        return caps or ['implementation']

    def _extract_interfaces(self, tasks: dict[str, AtomicTask]) -> list[str]:
        ifaces = set()
        for t in tasks.values():
            for cap in t.required_capabilities:
                ifaces.add(f"{cap}_api")
        return sorted(ifaces)

    def _has_cycle(self, deps: list[Dependency]) -> bool:
        adj: dict[str, list[str]] = {}
        for d in deps:
            adj.setdefault(d.source, []).append(d.target)

        WHITE, GRAY, BLACK = 0, 1, 2
        color = {}
        for d in deps:
            color[d.source] = WHITE
            color[d.target] = WHITE

        def dfs(node):
            color[node] = GRAY
            for neighbor in adj.get(node, []):
                if neighbor not in color:
                    continue
                if color[neighbor] == GRAY:
                    return True
                if color[neighbor] == WHITE and dfs(neighbor):
                    return True
            color[node] = BLACK
            return False

        for node in list(color.keys()):
            if color[node] == WHITE and dfs(node):
                return True
        return False


# ── Validation Harness ──────────────────────────────────

def validate_against_real_mission(mission_id: str, spec: dict) -> dict:
    """Compile a real Atlas mission and return validation results."""
    compiler = MissionCompiler()
    ir = compiler.compile(spec)
    return {
        'mission_id': mission_id,
        'ir': ir,
        'passed': ir.validation_passed,
        'errors': ir.validation_errors,
        'tasks_count': ir.total_tasks,
        'story_points': ir.estimated_story_points,
        'parallel_groups': len(ir.parallel_groups),
        'critical_path_length': len(ir.critical_path),
        'dependencies': len(ir.dependencies),
        'ir_hash': ir.ir_hash,
    }
