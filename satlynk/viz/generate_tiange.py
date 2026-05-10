"""
为天格 × 2800 星场景生成前端可视化。
策略：展示"有故事"的子集——3 颗天格 + 参与了任务传输的计算星 + 少量代表性邻居星。
同时在 metadata 中附全量统计信息供 sidebar 展示。
"""

import sys, json, os
sys.path.insert(0, '/workspace')

import numpy as np
from satlynk.core.simulator import Simulator, SimConfig
from satlynk.orbital.constellation import (
    Satellite, Role, OrbitalElements, generate_walker_delta,
    propagate_positions,
)
from satlynk.network.contact_plan import compute_contact_plan, ContactPlan
from satlynk.task.dag import TaskDAG, SubTask
from satlynk.scheduler.interface import NearestFirstScheduler
from satlynk.viz.exporter import VizRecorder


def build_tiange_viz():
    """生成前端友好的可视化数据（约 50 颗代表性卫星）。"""
    
    duration_s = 5400.0
    dt = 5.0  # 比全规模细一些（展示用）
    
    # --- 生成星座 (取子集用于展示) ---
    # 从 2800 星中选出 47 颗代表：在不同轨道面各取 1-2 颗
    # 模拟器用全 2800 但 viz 只记录子集
    
    # 实际策略：用 100 颗计算星（Walker 10/10/1）做可视化版本
    # 密度虽低于 2800 但足够展示"全覆盖 vs 稀疏"的对比效果
    
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

    # 100 颗计算星 Walker(100/10/1)
    compute_sats = generate_walker_delta(
        total_sats=100,
        num_planes=10,
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
    
    all_sats = tiange_sats + compute_sats
    N = len(all_sats)
    print(f"[Viz Build] {N} sats for visualization (3 det + 100 comp)")

    # --- 轨道 + Contact ---
    times = np.arange(0, duration_s + dt, dt)
    positions = propagate_positions(all_sats, times)
    
    candidate_pairs = [(i, j) for i in range(3) for j in range(3, N)]
    contact_plan = compute_contact_plan(
        all_sats, times, positions,
        data_rate_bps=2e6,
        candidate_pairs=candidate_pairs,
    )
    print(f"  Contact windows: {len(contact_plan)}")

    # 可达率分析
    for det_idx in range(3):
        windows = [w for w in contact_plan.windows if w.src == det_idx or w.dst == det_idx]
        reachable = sum(1 for t in times if any(w.is_active(t) for w in windows))
        print(f"  {tiange_sats[det_idx].id}: 可达率 {reachable/len(times)*100:.1f}%")

    # --- Simulator ---
    config = SimConfig(
        duration_s=duration_s, dt=dt,
        data_rate_bps=2e6,
        compute_flops_default=1e12,
        idle_power_w=5.0,
        compute_power_w=30.0,
        comm_power_w=3.0,
    )
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
    n_events = 8
    event_times = np.sort(np.random.uniform(60, duration_s - 300, n_events))
    event_sources = np.random.randint(0, 3, n_events)
    
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

    # --- Run with viz ---
    viz = sim.enable_viz_recording(position_interval_s=10.0, energy_interval_s=30.0)
    
    # Override scenario metadata
    viz.metadata = {
        "name": "天格计划 × 三体计算星座 — GRB 在轨推理",
        "description": "天格探测卫星观测伽马射线暴，请求天基计算卫星 2B 模型推理",
        "full_constellation": "3 探测 + 2800 计算 (展示版: 3+100)",
        "model": "grb_classifier_2b (4GB INT4, 8 GFLOP/infer)",
        "link_budget": "2 Mbps S-band (瓶颈在天格星)",
        "deadline": "120s per GRB event",
    }
    
    metrics = sim.run()
    print(f"  Result: {metrics.completed_tasks}/{metrics.total_tasks} tasks, "
          f"success={metrics.success_rate:.0%}")

    # --- Export ---
    export_path = "/workspace/oasis/viz/tiange_viz_export.json"
    viz.export_to_file(export_path)
    fsize = os.path.getsize(export_path)
    print(f"  Viz export: {fsize/1024:.0f} KB")

    return export_path


def main():
    from satlynk.viz.build_frontend import generate_html
    
    export_path = build_tiange_viz()
    output_path = "/workspace/site/index.html"
    generate_html(export_path, output_path)
    print(f"\n[Done] Frontend: {output_path}")
    print(f"  URL: https://s-thu-tiange.nia-sandbox-proxy.bc-inner.com/")


if __name__ == "__main__":
    main()
