"""
MC-0001 Unit Tests — 9-stage compiler validation
"""
import json, sys, os
sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

import pytest
from compiler import MissionCompiler
from ir_schema import MissionIR, AtomicTask, Dependency, ParallelGroup, TaskType, DependencyType, ConstraintType

# ── Test Fixtures ──────────────────────────────────────

@pytest.fixture
def compiler():
    return MissionCompiler()

@pytest.fixture
def simple_spec():
    return {
        'mission_id': 'TEST-0001',
        'title': 'Test Mission',
        'objectives': ['Build test service', 'Deploy to production'],
        'deliverables': [
            'Database Schema',
            'Auth Service',
            'API Gateway',
            'Integration Tests',
            'Certification Report',
        ],
        'workstreams': [],
        'quality_gates': ['Tests pass', 'Deployment verified'],
        'dependencies': [
            {'from': 'Database Schema', 'to': 'Auth Service'},
            {'from': 'Auth Service', 'to': 'API Gateway'},
            {'from': 'API Gateway', 'to': 'Integration Tests'},
            {'from': 'Integration Tests', 'to': 'Certification Report'},
        ],
        'constraints': ['parallel_ok'],
    }

# ── Stage 1: Parse ─────────────────────────────────────

def test_stage1_parse_valid(compiler, simple_spec):
    result = compiler._stage1_parse(simple_spec)
    assert result['mission_id'] == 'TEST-0001'
    assert len(result['deliverables']) == 5

def test_stage1_parse_missing_fields(compiler):
    result = compiler._stage1_parse({})
    assert len(compiler.errors) >= 4

# ── Stage 2: Constraint Analysis ───────────────────────

def test_stage2_parallel_ok(compiler):
    parsed = {'constraints': ['parallel_ok']}
    constraints = compiler._stage2_analyze_constraints(parsed)
    assert ConstraintType.PARALLEL_OK in constraints

def test_stage2_default_parallel(compiler):
    constraints = compiler._stage2_analyze_constraints({'constraints': []})
    assert ConstraintType.PARALLEL_OK in constraints

def test_stage2_reuse_required(compiler):
    parsed = {'constraints': ['reuse_required']}
    constraints = compiler._stage2_analyze_constraints(parsed)
    assert ConstraintType.REUSE_REQUIRED in constraints

# ── Stage 3: Capability Extraction ─────────────────────

def test_stage3_extracts_capabilities(compiler):
    caps = compiler._stage3_extract_capabilities({
        'objectives': ['Implement authentication service', 'Deploy to production'],
        'deliverables': ['Database Schema'],
    })
    assert 'implementation' in caps
    assert 'deployment' in caps

# ── Stage 4: Dependency Graph ──────────────────────────

def test_stage4_builds_graph(compiler, simple_spec):
    graph = compiler._stage4_build_dependency_graph(simple_spec, [])
    assert 'database_schema' in graph
    assert 'certification_report' in graph

# ── Stage 5: Atomic Decomposition ──────────────────────

def test_stage5_creates_atomic_tasks(compiler, simple_spec):
    graph = compiler._stage4_build_dependency_graph(simple_spec, [])
    tasks = compiler._stage5_decompose_atomic(simple_spec, graph)
    assert len(tasks) == 5
    for task in tasks.values():
        assert isinstance(task, AtomicTask)
        assert task.id
        assert task.type in TaskType
        assert 1 <= task.estimated_complexity <= 13

def test_stage5_task_type_classification(compiler):
    spec = {'deliverables': ['Architecture Design', 'Certification Report']}
    graph = compiler._stage4_build_dependency_graph(spec, [])
    tasks = compiler._stage5_decompose_atomic(spec, graph)
    assert tasks['architecture_design'].type == TaskType.ARCHITECTURE
    assert tasks['certification_report'].type == TaskType.CERTIFICATION

# ── Stage 6: Parallelism Analysis ──────────────────────

def test_stage6_creates_parallel_groups(compiler, simple_spec):
    graph = compiler._stage4_build_dependency_graph(simple_spec, [])
    tasks = compiler._stage5_decompose_atomic(simple_spec, graph)
    groups = compiler._stage6_analyze_parallelism(tasks, graph)
    assert len(groups) > 0
    for pg in groups:
        assert isinstance(pg, ParallelGroup)
        assert pg.max_concurrency <= 3

# ── Stage 7: Critical Path ─────────────────────────────

def test_stage7_critical_path(compiler, simple_spec):
    graph = compiler._stage4_build_dependency_graph(simple_spec, [])
    tasks = compiler._stage5_decompose_atomic(simple_spec, graph)
    path = compiler._stage7_critical_path(tasks, graph)
    assert len(path) > 0
    assert path[0] == 'database_schema'
    assert path[-1] == 'certification_report'

def test_stage7_critical_path_returns_list(compiler):
    path = compiler._stage7_critical_path({}, {})
    assert path == []

# ── Stage 8: IR Generation ─────────────────────────────

def test_stage8_generates_valid_ir(compiler, simple_spec):
    graph = compiler._stage4_build_dependency_graph(simple_spec, [])
    tasks = compiler._stage5_decompose_atomic(simple_spec, graph)
    parallel = compiler._stage6_analyze_parallelism(tasks, graph)
    critical = compiler._stage7_critical_path(tasks, graph)
    caps = compiler._stage3_extract_capabilities(simple_spec)

    compiler.spec = simple_spec
    ir = compiler._stage8_generate_ir(tasks, graph, parallel, critical, caps)
    assert isinstance(ir, MissionIR)
    assert ir.total_tasks == 5
    assert ir.ir_hash
    assert len(ir.ir_hash) == 16

# ── Stage 9: Validation ────────────────────────────────

def test_stage9_validates_clean_ir(compiler, simple_spec):
    graph = compiler._stage4_build_dependency_graph(simple_spec, [])
    tasks = compiler._stage5_decompose_atomic(simple_spec, graph)
    parallel = compiler._stage6_analyze_parallelism(tasks, graph)
    critical = compiler._stage7_critical_path(tasks, graph)
    caps = compiler._stage3_extract_capabilities(simple_spec)

    compiler.spec = simple_spec
    ir = compiler._stage8_generate_ir(tasks, graph, parallel, critical, caps)
    validated = compiler._stage9_validate(ir)
    assert validated.validation_passed

def test_stage9_detects_empty(compiler):
    ir = MissionIR(
        mission_id='EMPTY', version='1.0', created_at='now',
        tasks={}, dependencies=[], parallel_groups=[], critical_path=[],
        capabilities_required=[], interfaces_required=[],
        total_tasks=0, estimated_story_points=0,
        validation_passed=False, validation_errors=[], ir_hash='',
    )
    validated = compiler._stage9_validate(ir)
    assert not validated.validation_passed
    assert any('No tasks' in e for e in validated.validation_errors)

def test_stage9_detects_cycle(compiler, simple_spec):
    graph = compiler._stage4_build_dependency_graph(simple_spec, [])
    tasks = compiler._stage5_decompose_atomic(simple_spec, graph)
    parallel = compiler._stage6_analyze_parallelism(tasks, graph)
    critical = compiler._stage7_critical_path(tasks, graph)
    caps = compiler._stage3_extract_capabilities(simple_spec)

    compiler.spec = simple_spec
    ir = compiler._stage8_generate_ir(tasks, graph, parallel, critical, caps)
    # Inject cycle
    ir.dependencies.append(Dependency(source='certification_report', target='database_schema', type=DependencyType.HARD))
    validated = compiler._stage9_validate(ir)
    assert not validated.validation_passed
    assert any('Circular' in e for e in validated.validation_errors)

# ── Full Pipeline ──────────────────────────────────────

def test_full_pipeline_valid_mission(compiler, simple_spec):
    ir = compiler.compile(simple_spec)
    assert ir.validation_passed
    assert ir.total_tasks == 5
    assert len(ir.critical_path) > 0
    assert ir.estimated_story_points > 0
    assert ir.ir_hash

def test_to_json_output(compiler, simple_spec):
    ir = compiler.compile(simple_spec)
    json_str = ir.to_json()
    assert 'TEST-0001' in json_str
    assert 'critical_path' in json_str

def test_full_pipeline_no_deliverables(compiler):
    ir = compiler.compile({'mission_id': 'EMPTY', 'title': 'Empty'})
    assert not ir.validation_passed

if __name__ == '__main__':
    pytest.main([__file__, '-v'])
