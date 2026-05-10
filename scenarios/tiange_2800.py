"""
天格 × 三体计算星座 2800 星全规模场景
=====================================
计算星座最终形态：2800 颗计算卫星（参考之江实验室三体计算星座目标）
探测星座：3 颗天格卫星

优化策略：
- Contact Plan 仅计算 det↔comp 对（3×2800=8400 对），跳过 comp↔comp
  （本场景任务流为 det→comp→det，不需要多跳 relay）
- 位置传播向量化处理
- 时间步 dt=10s（降采样）减少内存占用
"""

import sys
sys.path.insert(0, '/workspace')

import numpy as np
import time as walltime
from satlynk.core.simulator import Simulator, SimConfig
from satlynk.orbital.constellation import (
    Satellite, Role, OrbitalElements, generate_walker_delta,
    propagate_positions,
)
from satlynk.network.contact_plan import compute_contact_plan
from satlynk.task.dag import TaskDAG, SubTask
from satlynk.scheduler.interface import NearestFirstScheduler


def create_full_constellation():
    """
    三体计算星座最终形态 + 天格探测星。
    
    计算星：2800 颗 Walker-Delta
      - 参考三体计算星座规划：千星→2800 星（总算力 1000+ POPS）
      - 分布：40 轨道面 × 70 颗/面 = 2800
      - 高度：550 km，倾角 53°
      - 单星：100 TOPS INT8 (~1 TFLOPS FP16)
    
    探测星：3 颗天格
      - 535 km SSO
    """
    # --- 天格 (3颗) ---
    tiange_sats = []
    for i in range(3):
        sat = Satellite(
            id=f"TG-{i+1:02d}",
            role=Role.DETECTOR,
            elements=OrbitalElements(
                semi_major_axis_km=6906.0,
                inclination_deg=97.5,
                raan_deg=i * 120.0,
                true_anomaly_deg=i * 60.0,
            ),
            compute_flops=100e6,
            storage_bytes=int(4e9),
            max_comm_range_km=3000.0,
            power_solar_w=12.0,
            battery_capacity_wh=40.0,
        )
        tiange_sats.append(sat)

    # --- 三体计算星座 (2800颗, Walker 40/70/1) ---
    compute_sats = generate_walker_delta(
        total_sats=2800,
        num_planes=40,
        phase_factor=1,
        altitude_km=550,
        inclination_deg=53.0,
        role=Role.COMPUTE,
        prefix="SC",
        compute_flops=1e12,
        storage_bytes=int(64e9),
        max_comm_range_km=5000.0,
        power_solar_w=80.0,
        battery_capacity_wh=300.0,
    )

    return tiange_sats, compute_sats


def run_2800sat_scenario():
    print("=" * 70)
    print("SatLynk — 天格 × 三体计算星座 (2800星) 全规模场景")
    print("=" * 70)

    t0 = walltime.time()

    # --- Config ---
    duration_s = 5400.0   # 90 分钟 (约一个轨道周期)
    dt = 10.0             # 降采样 10s/步 (减少内存)
    config = SimConfig(
        duration_s=duration_s,
        dt=dt,
        data_rate_bps=2e6,
        compute_flops_default=1e12,
        idle_power_w=5.0,
        compute_power_w=30.0,
        comm_power_w=3.0,
    )

    # --- 生成星座 ---
    tiange_sats, compute_sats = create_full_constellation()
    all_sats = tiange_sats + compute_sats
    N = len(all_sats)
    print(f"\n[星座] {N} 颗卫星 (3 探测 + 2800 计算)")
    print(f"  计算星: Walker(2800/40/1), 550km, 53°")
    print(f"  探测星: 3× 天格, 535km SSO")

    # --- 轨道传播 ---
    print(f"\n[轨道传播] dt={dt}s, {int(duration_s/dt)+1} 步...")
    t1 = walltime.time()
    times = np.arange(0, duration_s + dt, dt)
    positions = propagate_positions(all_sats, times)
    print(f"  完成: {walltime.time()-t1:.1f}s, shape={positions.shape}")

    # --- Contact Plan (仅 det↔comp) ---
    print(f"\n[Contact Plan] 仅计算 det↔comp 对 (3×2800=8400 对)...")
    t2 = walltime.time()
    # 只计算探测星(0-2) 到 计算星(3-2802) 的 link
    candidate_pairs = [(i, j) for i in range(3) for j in range(3, N)]
    contact_plan = compute_contact_plan(
        all_sats, times, positions,
        data_rate_bps=config.data_rate_bps,
        candidate_pairs=candidate_pairs,
    )
    print(f"  完成: {walltime.time()-t2:.1f}s, {len(contact_plan)} 窗口")

    # --- 分析各探测星的覆盖 ---
    print(f"\n[通信覆盖分析]")
    for det_idx in range(3):
        windows = [w for w in contact_plan.windows
                   if w.src == det_idx or w.dst == det_idx]
        total_contact = sum(w.duration_s for w in windows)
        unique_comp = len(set(
            w.dst if w.src == det_idx else w.src for w in windows
        ))
        # 计算"任意时刻可达率" — 在所有时间步中有多少百分比至少有一颗计算星可达
        reachable_steps = 0
        for t_idx, t in enumerate(times):
            for w in windows:
                if w.is_active(t):
                    reachable_steps += 1
                    break
        reachable_pct = reachable_steps / len(times) * 100
        print(f"  {tiange_sats[det_idx].id}: "
              f"{len(windows)} 窗口, "
              f"接触 {unique_comp} 颗计算星, "
              f"可达率 {reachable_pct:.1f}%")

    # --- 设置 Simulator ---
    sim = Simulator(config)
    sim.set_satellites(all_sats)
    sim.positions = positions
    sim.times = times
    sim.contact_plan = contact_plan
    sim._preload_link_events(contact_plan)
    sim.set_scheduler(NearestFirstScheduler())

    # 预装模型
    model_name = "grb_classifier_2b"
    sim.weight_mgr.register_model(model_name, int(4e9))
    for i in range(3, N):
        sim.weight_mgr.cache_weight(i, model_name, t=0.0)

    # --- GRB 事件 ---
    np.random.seed(42)
    n_events = 12
    event_times = np.sort(np.random.uniform(60, duration_s - 300, n_events))
    event_sources = np.random.randint(0, 3, n_events)

    print(f"\n[GRB 触发] {n_events} 个事件")
    for i, (t, src) in enumerate(zip(event_times, event_sources)):
        task = TaskDAG(
            id=f"grb_{i:03d}",
            source_node=int(src),
            arrival_time_s=float(t),
            subtasks=[SubTask(
                id=f"grb_{i:03d}_infer",
                compute_flops=8e9,
                required_model=model_name,
                model_size_bytes=int(4e9),
                output_size_bytes=50_000,
            )],
            dependencies=[],
            global_deadline_s=120.0,
            result_destination=int(src),
            result_size_bytes=50_000,
        )
        task.input_size_bytes = 500_000
        sim.add_task(task)
        print(f"  #{i}: t={t:.0f}s, {tiange_sats[src].id}")

    # --- 仿真 ---
    print(f"\n[运行仿真...]")
    sim.enable_viz_recording(position_interval_s=30.0, energy_interval_s=60.0)
    metrics = sim.run()

    # --- 结果 ---
    print(f"\n{'='*70}")
    print(f"[结果]")
    print(f"{'='*70}")
    print(f"  任务完成: {metrics.completed_tasks}/{metrics.total_tasks}")
    print(f"  成功率: {metrics.success_rate:.0%}")
    if metrics.completed_tasks > 0:
        print(f"  平均 makespan: {metrics.avg_makespan_s:.1f}s")
        print(f"  最大 makespan: {metrics.max_makespan_s:.1f}s")
    print(f"  总传输: {metrics.total_data_transferred_bytes/1e6:.2f} MB")
    print(f"  最低电池: {metrics.min_battery_pct:.1f}%")
    print(f"  总耗时: {walltime.time()-t0:.1f}s")

    # 逐任务
    print(f"\n[逐任务]")
    for result in sim.metrics.task_results:
        task = sim._tasks[result.task_id]
        status = "✓" if result.success else "✗"
        print(f"  {status} {result.task_id}: {tiange_sats[task.source_node].id}, "
              f"makespan={result.makespan_s:.1f}s")

    # --- 对比 ---
    print(f"\n[对比: 4星 vs 2800星]")
    print(f"  4 计算星 (Phase 1):  成功率 17%, 仅 TIANGE-01 有足够覆盖")
    print(f"  2800 计算星 (当前): 成功率 {metrics.success_rate:.0%}")
    if metrics.success_rate > 0.8:
        print(f"  → 星座密度是解决时空可达性的根本途径")

    # --- 导出 viz ---
    export_path = "/workspace/oasis/viz/tiange_2800_export.json"
    sim.viz.export_to_file(export_path)
    import os
    print(f"\n[Viz] {export_path} ({os.path.getsize(export_path)/1024/1024:.1f} MB)")

    return metrics, contact_plan


if __name__ == "__main__":
    metrics, _ = run_2800sat_scenario()
