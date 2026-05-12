"""Benchmark Framework — Run the same scenario with multiple schedulers and compare.

Usage:
    python -m satlynk.benchmark
    python -m satlynk.benchmark --scenario tiange_15  --output results.json
"""

from __future__ import annotations

import time as walltime
import json
import sys
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Any, Callable, Optional
from copy import deepcopy
import numpy as np

from satlynk.core.simulator import Simulator, SimConfig
from satlynk.orbital.constellation import (
    Satellite, Role, generate_walker_delta,
)
from satlynk.task.dag import TaskDAG, SubTask
from satlynk.scheduler.interface import NearestFirstScheduler, Scheduler
from satlynk.scheduler.heuristics import (
    RandomScheduler, ShortestPathScheduler, CGR_EDF_Scheduler,
)
from satlynk.scheduler.teg_scheduler import TEGScheduler
from satlynk.metrics.collector import SimMetrics


# ─── Result Data Structures ──────────────────────────────────────────────

@dataclass
class SchedulerResult:
    """Result of running one scheduler on one scenario."""
    scheduler_name: str
    success_rate: float
    completed_tasks: int
    total_tasks: int
    avg_makespan_s: float
    max_makespan_s: float
    min_battery_pct: float
    data_transferred_mb: float
    wall_clock_ms: float
    events_processed: int


@dataclass 
class BenchmarkResult:
    """Full benchmark result for one scenario."""
    scenario_name: str
    num_satellites: int
    num_tasks: int
    duration_s: float
    contact_windows: int
    results: List[SchedulerResult] = field(default_factory=list)


# ─── Scenario Definitions ────────────────────────────────────────────────

def make_scenario_5sat() -> Dict[str, Any]:
    """5 satellites, 5 tasks — minimal scenario for validation."""
    config = SimConfig(
        duration_s=600.0, dt=1.0,
        data_rate_bps=50e6, compute_flops_default=8e9,
    )
    
    compute_sats = generate_walker_delta(
        total_sats=4, num_planes=2, phase_factor=1,
        altitude_km=550, inclination_deg=53.0,
        role=Role.COMPUTE, prefix='COMP',
        compute_flops=8e9, power_solar_w=50, battery_capacity_wh=200,
        max_comm_range_km=5000,
    )
    detector_sats = generate_walker_delta(
        total_sats=1, num_planes=1, phase_factor=0,
        altitude_km=500, inclination_deg=97.4,
        role=Role.DETECTOR, prefix='DET',
        compute_flops=0, power_solar_w=10, battery_capacity_wh=40,
        max_comm_range_km=3000,
    )
    
    all_sats = detector_sats + compute_sats
    
    # Generate tasks
    rng = np.random.default_rng(42)
    tasks = []
    for i in range(5):
        t_arrive = 30.0 + i * 80
        task = TaskDAG(
            id=f'task_{i:03d}',
            source_node=0,  # detector
            arrival_time_s=t_arrive,
            subtasks=[SubTask(id=f'infer_{i}', compute_flops=25e9, output_size_bytes=500_000)],
            dependencies=[],
            global_deadline_s=300.0,
            result_destination=0,
            result_size_bytes=500_000,
        )
        task.input_size_bytes = 3_000_000
        tasks.append(task)
    
    return {
        'name': '5sat_5task',
        'config': config,
        'satellites': all_sats,
        'tasks': tasks,
    }


def make_scenario_15sat() -> Dict[str, Any]:
    """15 satellites, 14 tasks — Phase 2 reference scenario."""
    config = SimConfig(
        duration_s=1800.0, dt=1.0,
        data_rate_bps=50e6, compute_flops_default=8e9,
    )
    
    compute_sats = generate_walker_delta(
        total_sats=12, num_planes=3, phase_factor=1,
        altitude_km=550, inclination_deg=53.0,
        role=Role.COMPUTE, prefix='COMP',
        compute_flops=8e9, power_solar_w=50, battery_capacity_wh=200,
        max_comm_range_km=5000,
    )
    detector_sats = generate_walker_delta(
        total_sats=3, num_planes=1, phase_factor=0,
        altitude_km=500, inclination_deg=97.4,
        role=Role.DETECTOR, prefix='DET',
        compute_flops=0, power_solar_w=10, battery_capacity_wh=40,
        max_comm_range_km=3000,
    )
    
    all_sats = detector_sats + compute_sats
    
    # 14 tasks: 8 burst + 6 spread
    rng = np.random.default_rng(123)
    tasks = []
    for i in range(14):
        if i < 8:
            t_arrive = 30.0 + i * 5
        else:
            t_arrive = 600.0 + (i - 8) * 100
        
        det_idx = rng.integers(0, 3)
        task = TaskDAG(
            id=f'task_{i:03d}',
            source_node=det_idx,
            arrival_time_s=t_arrive,
            subtasks=[SubTask(id=f'infer_{i}', compute_flops=25e9, output_size_bytes=500_000)],
            dependencies=[],
            global_deadline_s=600.0,
            result_destination=det_idx,
            result_size_bytes=500_000,
        )
        task.input_size_bytes = 3_000_000
        tasks.append(task)
    
    return {
        'name': '15sat_14task',
        'config': config,
        'satellites': all_sats,
        'tasks': tasks,
    }


def make_scenario_tiange_grb() -> Dict[str, Any]:
    """Tiange GRB scenario: 3 detectors + 12 compute, 10 GRB events.
    
    Assumes model weights are PRE-DEPLOYED on compute nodes (realistic ops scenario).
    More compute satellites for better coverage.
    """
    config = SimConfig(
        duration_s=1800.0, dt=1.0,
        data_rate_bps=50e6, compute_flops_default=100e12,
    )
    
    # Tiange detectors (SSO 535km)
    detector_sats = generate_walker_delta(
        total_sats=3, num_planes=1, phase_factor=0,
        altitude_km=535, inclination_deg=97.6,
        role=Role.DETECTOR, prefix='GRID',
        compute_flops=0, power_solar_w=10, battery_capacity_wh=40,
        max_comm_range_km=5000,  # ISL range
    )
    
    # Compute satellites (550km 53°, ~100 TOPS each) — larger constellation
    compute_sats = generate_walker_delta(
        total_sats=12, num_planes=3, phase_factor=1,
        altitude_km=550, inclination_deg=53.0,
        role=Role.COMPUTE, prefix='COMP',
        compute_flops=100e12, power_solar_w=80, battery_capacity_wh=500,
        max_comm_range_km=5000,
    )
    
    all_sats = detector_sats + compute_sats
    
    # 10 GRB trigger events — no model weight required (pre-deployed)
    rng = np.random.default_rng(777)
    tasks = []
    for i in range(10):
        t_arrive = rng.uniform(60, 1700)
        det_idx = rng.integers(0, 3)
        
        # 2B model inference: ~16 GFLOP at INT8
        task = TaskDAG(
            id=f'grb_{i:03d}',
            source_node=det_idx,
            arrival_time_s=t_arrive,
            subtasks=[SubTask(
                id=f'infer_grb_{i}',
                compute_flops=16e9,
                output_size_bytes=1_000_000,
            )],
            dependencies=[],
            global_deadline_s=300.0,
            result_destination=det_idx,
            result_size_bytes=1_000_000,
        )
        task.input_size_bytes = 5_000_000  # 5MB event data
        tasks.append(task)
    
    return {
        'name': 'tiange_grb_15sat',
        'config': config,
        'satellites': all_sats,
        'tasks': tasks,
    }


# ─── Benchmark Runner ────────────────────────────────────────────────────

def get_all_schedulers(contact_plan=None, satellites=None, 
                       tasks=None, data_rate_bps=50e6,
                       time_horizon_s=1800.0) -> Dict[str, Any]:
    """Get all schedulers to benchmark."""
    schedulers = {
        'Random': RandomScheduler(seed=42),
        'Nearest-First': NearestFirstScheduler(),
        'Shortest-Path': ShortestPathScheduler(data_rate_bps=data_rate_bps),
        'CGR+EDF': CGR_EDF_Scheduler(data_rate_bps=data_rate_bps, max_hops=3),
    }
    
    # TEG scheduler — uses time-expanded graph for optimal routing
    if contact_plan and satellites:
        teg_sched = TEGScheduler(
            contact_plan=contact_plan,
            satellites=satellites,
            data_rate_bps=data_rate_bps,
            time_horizon_s=time_horizon_s,
            teg_dt_s=10.0,
        )
        schedulers['TEG'] = teg_sched

    # Oracle — exhaustive search (no external deps, feasible for ≤20 sats)
    if contact_plan and satellites and tasks and len(satellites) <= 20:
        from satlynk.scheduler.oracle import OracleScheduler
        oracle = OracleScheduler(
            contact_plan=contact_plan,
            satellites=satellites,
            data_rate_bps=data_rate_bps,
            time_horizon_s=time_horizon_s,
        )
        oracle.precompute_all(tasks)
        schedulers['Oracle'] = oracle
    
    return schedulers


def run_single(scenario: Dict[str, Any], scheduler_name: str, 
               scheduler: Any) -> SchedulerResult:
    """Run a single scenario with one scheduler."""
    config = scenario['config']
    satellites = scenario['satellites']
    tasks = scenario['tasks']
    
    sim = Simulator(config)
    sim.set_satellites(satellites)
    sim.precompute_orbits()
    sim.set_scheduler(scheduler)
    
    # Add all tasks
    for task in tasks:
        # Deep copy task to avoid state pollution between runs
        task_copy = TaskDAG(
            id=task.id,
            source_node=task.source_node,
            arrival_time_s=task.arrival_time_s,
            subtasks=[SubTask(
                id=st.id,
                compute_flops=st.compute_flops,
                required_model=st.required_model,
                model_size_bytes=st.model_size_bytes,
                output_size_bytes=st.output_size_bytes,
            ) for st in task.subtasks],
            dependencies=list(task.dependencies),
            global_deadline_s=task.global_deadline_s,
            result_destination=task.result_destination,
            result_size_bytes=task.result_size_bytes,
        )
        task_copy.input_size_bytes = getattr(task, 'input_size_bytes', 0)
        sim.add_task(task_copy)
    
    # Register model weights if any task needs them
    for task in tasks:
        for st in task.subtasks:
            if st.required_model:
                sim.weight_mgr.register_model(st.required_model, st.model_size_bytes)
    
    metrics = sim.run()
    
    return SchedulerResult(
        scheduler_name=scheduler_name,
        success_rate=metrics.success_rate,
        completed_tasks=metrics.completed_tasks,
        total_tasks=metrics.total_tasks,
        avg_makespan_s=metrics.avg_makespan_s,
        max_makespan_s=metrics.max_makespan_s,
        min_battery_pct=metrics.min_battery_pct,
        data_transferred_mb=metrics.total_data_transferred_bytes / 1e6,
        wall_clock_ms=metrics.wall_clock_s * 1000,
        events_processed=metrics.events_processed,
    )


def run_benchmark(scenario: Dict[str, Any], 
                  include_oracle: bool = True,
                  verbose: bool = True) -> BenchmarkResult:
    """Run full benchmark on one scenario."""
    name = scenario['name']
    config = scenario['config']
    satellites = scenario['satellites']
    tasks = scenario['tasks']
    
    if verbose:
        print(f"\n{'='*64}")
        print(f"  Benchmark: {name}")
        print(f"  Satellites: {len(satellites)}, Tasks: {len(tasks)}, Duration: {config.duration_s}s")
        print(f"{'='*64}\n")
    
    # Precompute contact plan once (shared across all schedulers)
    sim_ref = Simulator(config)
    sim_ref.set_satellites(satellites)
    sim_ref.precompute_orbits()
    contact_plan = sim_ref.contact_plan
    
    if verbose:
        print(f"  Contact windows: {len(contact_plan)}")
    
    # Get schedulers
    scheduler_kwargs = {
        'contact_plan': contact_plan,
        'satellites': satellites,
        'data_rate_bps': config.data_rate_bps,
        'time_horizon_s': config.duration_s,
    }
    if include_oracle:
        # Deep copy tasks for MILP (it modifies task objects during solve)
        milp_tasks = []
        for task in tasks:
            t_copy = TaskDAG(
                id=task.id,
                source_node=task.source_node,
                arrival_time_s=task.arrival_time_s,
                subtasks=[SubTask(
                    id=st.id,
                    compute_flops=st.compute_flops,
                    required_model=st.required_model,
                    model_size_bytes=st.model_size_bytes,
                    output_size_bytes=st.output_size_bytes,
                ) for st in task.subtasks],
                dependencies=list(task.dependencies),
                global_deadline_s=task.global_deadline_s,
                result_destination=task.result_destination,
                result_size_bytes=task.result_size_bytes,
            )
            t_copy.input_size_bytes = getattr(task, 'input_size_bytes', 0)
            milp_tasks.append(t_copy)
        scheduler_kwargs['tasks'] = milp_tasks
    
    schedulers = get_all_schedulers(**scheduler_kwargs)
    
    # Run each scheduler
    result = BenchmarkResult(
        scenario_name=name,
        num_satellites=len(satellites),
        num_tasks=len(tasks),
        duration_s=config.duration_s,
        contact_windows=len(contact_plan),
    )
    
    for sched_name, sched in schedulers.items():
        if verbose:
            print(f"  Running {sched_name}...", end='', flush=True)
        
        t0 = walltime.time()
        sched_result = run_single(scenario, sched_name, sched)
        t1 = walltime.time()
        
        result.results.append(sched_result)
        
        if verbose:
            print(f" {sched_result.success_rate*100:.0f}% "
                  f"({sched_result.completed_tasks}/{sched_result.total_tasks}), "
                  f"makespan={sched_result.avg_makespan_s:.1f}s, "
                  f"wall={t1-t0:.3f}s")
    
    return result


def print_comparison_table(result: BenchmarkResult):
    """Pretty-print comparison table."""
    print(f"\n{'─'*80}")
    print(f"  {result.scenario_name} | {result.num_satellites} sats | "
          f"{result.num_tasks} tasks | {result.contact_windows} windows")
    print(f"{'─'*80}")
    
    # Header
    print(f"  {'Scheduler':<16} {'Success':>8} {'Completed':>10} "
          f"{'Avg Mksp':>9} {'Max Mksp':>9} {'Data(MB)':>9} {'Wall(ms)':>9}")
    print(f"  {'─'*16} {'─'*8} {'─'*10} {'─'*9} {'─'*9} {'─'*9} {'─'*9}")
    
    # Sort by success rate descending
    sorted_results = sorted(result.results, key=lambda r: -r.success_rate)
    
    for r in sorted_results:
        print(f"  {r.scheduler_name:<16} {r.success_rate*100:>7.1f}% "
              f"{r.completed_tasks:>4}/{r.total_tasks:<4} "
              f"{r.avg_makespan_s:>8.1f}s {r.max_makespan_s:>8.1f}s "
              f"{r.data_transferred_mb:>8.1f} {r.wall_clock_ms:>8.1f}")
    
    print(f"{'─'*80}")
    
    # Gap analysis
    if len(sorted_results) >= 2:
        best = sorted_results[0]
        print(f"\n  Best: {best.scheduler_name} ({best.success_rate*100:.1f}%)")
        for r in sorted_results[1:]:
            gap = best.success_rate - r.success_rate
            print(f"  Gap to {r.scheduler_name}: {gap*100:+.1f}pp success rate")


# ─── Main ────────────────────────────────────────────────────────────────

def main():
    """Run all benchmark scenarios."""
    scenarios = [
        make_scenario_5sat(),
        make_scenario_15sat(),
        make_scenario_tiange_grb(),
    ]
    
    all_results = []
    
    for scenario in scenarios:
        result = run_benchmark(scenario, include_oracle=True, verbose=True)
        print_comparison_table(result)
        all_results.append(result)
    
    # Summary
    print(f"\n{'='*80}")
    print("  BENCHMARK SUMMARY")
    print(f"{'='*80}")
    
    for result in all_results:
        print(f"\n  [{result.scenario_name}]")
        for r in sorted(result.results, key=lambda x: -x.success_rate):
            bar_len = int(r.success_rate * 30)
            bar = '█' * bar_len + '░' * (30 - bar_len)
            print(f"    {r.scheduler_name:<16} |{bar}| {r.success_rate*100:.0f}%")
    
    # Save results
    output = {
        'timestamp': walltime.strftime('%Y-%m-%d %H:%M:%S'),
        'scenarios': [
            {
                'name': r.scenario_name,
                'num_satellites': r.num_satellites,
                'num_tasks': r.num_tasks,
                'contact_windows': r.contact_windows,
                'results': [asdict(sr) for sr in r.results],
            }
            for r in all_results
        ]
    }
    
    output_path = '/workspace/satlynk/output/benchmark_results.json'
    import os
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, 'w') as f:
        json.dump(output, f, indent=2)
    print(f"\n  Results saved to: {output_path}")


if __name__ == '__main__':
    main()
