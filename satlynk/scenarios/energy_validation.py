"""
Energy Validation Scenario
===========================
专门验证能量模块逐星逐秒准确性的小场景。

设计：3 天格探测星 + 4 计算星，仿真 30 分钟（约半个轨道周期）。
预期行为：
  1. 初始光照段 → 太阳能充电 → 电池缓慢上升
  2. 进入地影 → solar=0 → 电池以 base_load 速率下降
  3. 地影中触发 GRB → 通信开始 → 电池下降加速（+comm_tx/rx）
  4. 传输完成 → 计算开始 → 电池下降更快（+compute_w）
  5. 计算完成 → 回到 base_load → 下降减缓
  6. 退出地影 → 光伏恢复 → 电池回升

输出：逐星能量时间线 + 斜率验证 + 关键事件标注
"""

import numpy as np
from satlynk.core.simulator import Simulator, SimConfig
from satlynk.orbital.constellation import (
    Satellite, Role, OrbitalElements, generate_walker_delta,
)
from satlynk.task.dag import TaskDAG, SubTask, DataDependency
from satlynk.scheduler.interface import NearestFirstScheduler
from satlynk.energy.battery import PowerComponent


def create_small_constellation():
    """3 天格 + 4 计算星（与 tiange_grb 相同配置）"""
    tiange_sats = []
    for i, raan in enumerate([0.0, 120.0, 240.0]):
        sat = Satellite(
            id=f"TG-{i+1:02d}",
            role=Role.DETECTOR,
            elements=OrbitalElements(
                semi_major_axis_km=6906.0,
                inclination_deg=97.5,
                raan_deg=raan,
                true_anomaly_deg=i * 60.0,
            ),
            compute_flops=100e6,
            storage_bytes=int(4e9),
            max_comm_range_km=3000.0,
            power_solar_w=12.0,
            battery_capacity_wh=40.0,
        )
        tiange_sats.append(sat)

    compute_sats = generate_walker_delta(
        total_sats=4,
        num_planes=2,
        phase_factor=1,
        altitude_km=550,
        inclination_deg=53.0,
        role=Role.COMPUTE,
        prefix="COMP",
        compute_flops=1e12,
        storage_bytes=int(64e9),
        max_comm_range_km=5000.0,
        power_solar_w=80.0,
        battery_capacity_wh=300.0,
    )
    return tiange_sats, compute_sats


def create_grb_task(task_id: str, source_node: int, arrival_time: float) -> TaskDAG:
    """Single-subtask GRB inference task."""
    subtask = SubTask(
        id=f"{task_id}_infer",
        compute_flops=10e12,           # 10 TFLOP — 10s on 1 TFLOPS node
        required_model="grb_2b",
        model_size_bytes=int(4e9),
    )
    task = TaskDAG(
        id=task_id,
        subtasks=[subtask],
        dependencies=[],
        source_node=source_node,
        arrival_time_s=arrival_time,
        result_size_bytes=int(50e3),
        global_deadline_s=120.0,
    )
    task.input_size_bytes = 500_000  # 500 KB
    return task


def run_energy_validation():
    print("=" * 70)
    print("SatLynk — Energy Module Validation Scenario")
    print("=" * 70)

    # --- Setup ---
    config = SimConfig(
        duration_s=1800.0,   # 30 minutes
        dt=1.0,              # 1-second resolution for energy accuracy
        data_rate_bps=2e6,   # 2 Mbps (天格 ISL)
        compute_flops_default=1e12,
        idle_power_w=2.0,
        compute_power_w=50.0,   # Peak AI inference power
        comm_power_w=5.0,       # Comm transmit power
    )

    tiange_sats, compute_sats = create_small_constellation()
    all_sats = tiange_sats + compute_sats

    sim = Simulator(config)
    sim.set_satellites(all_sats)
    sim.set_scheduler(NearestFirstScheduler())
    sim.precompute_orbits()

    # Pre-cache weights on all compute stars (so we focus on energy, not weight logistics)
    sim.weight_mgr.register_model("grb_2b", int(4e9))
    for i in range(len(tiange_sats), len(all_sats)):
        sim.weight_mgr.cache_weight(i, "grb_2b", 0.0)

    # --- Print eclipse schedule ---
    print(f"\n[星座] {len(all_sats)} 颗卫星 ({len(tiange_sats)} 探测 + {len(compute_sats)} 计算)")
    print(f"[仿真] 持续 {config.duration_s:.0f}s, dt={config.dt}s")
    print(f"\n[地影时间表]")
    for i, sat in enumerate(all_sats):
        eclipses = []
        if sim.eclipse_map is not None:
            # Find eclipse windows from the boolean map
            in_ecl = False
            enter_t = 0.0
            for t_idx in range(sim.eclipse_map.shape[1]):
                t = sim.times[t_idx]
                if sim.eclipse_map[i, t_idx] and not in_ecl:
                    in_ecl = True
                    enter_t = t
                elif not sim.eclipse_map[i, t_idx] and in_ecl:
                    in_ecl = False
                    eclipses.append((enter_t, t))
            if in_ecl:
                eclipses.append((enter_t, sim.times[-1]))

        if eclipses:
            ecl_str = ", ".join(f"[{e[0]:.0f}s-{e[1]:.0f}s]" for e in eclipses)
            total_ecl = sum(e[1] - e[0] for e in eclipses)
            print(f"  {sat.id}: {ecl_str} (总计 {total_ecl:.0f}s, "
                  f"{total_ecl/config.duration_s*100:.1f}%)")
        else:
            print(f"  {sat.id}: 无地影")

    # --- Inject GRB task at specific timing ---
    # We want at least one task to arrive during eclipse for a compute star
    # Strategy: inject tasks at multiple times
    tasks_injected = []
    task_times = [300.0, 600.0, 900.0, 1200.0]
    for idx, arr_t in enumerate(task_times):
        source = idx % len(tiange_sats)  # Rotate among detectors
        task = create_grb_task(f"grb_{idx:03d}", source, arr_t)
        sim.add_task(task)
        tasks_injected.append((task.id, source, arr_t))

    print(f"\n[任务注入] {len(tasks_injected)} 个 GRB 事件")
    for tid, src, arr in tasks_injected:
        print(f"  {tid}: 来自 {all_sats[src].id}, t={arr:.0f}s")

    # --- Run ---
    print(f"\n[运行仿真...]")
    metrics = sim.run()

    # --- Results ---
    print(f"\n{'=' * 70}")
    print(f"[仿真结果]")
    print(f"{'=' * 70}")
    print(f"  成功率: {metrics.success_rate:.0%}")
    print(f"  总传输: {metrics.total_data_transferred_bytes/1e6:.2f} MB")

    # --- Energy Timeline Analysis ---
    print(f"\n{'=' * 70}")
    print(f"[能量时间线分析 — 逐星]")
    print(f"{'=' * 70}")

    for i, sat in enumerate(all_sats):
        timeline = sim.energy.get_timeline(i)
        if not timeline:
            continue

        print(f"\n  ── {sat.id} ({sat.role.value}) ──")
        state = sim.energy.states[i]
        print(f"  初始电量: 80.0%  |  最终电量: {state.pct:.2f}%")
        print(f"  太阳能面板: {sat.power_solar_w}W  |  电池容量: {sat.battery_capacity_wh}Wh")
        print(f"  功耗配置: base={state.power_profile.base_w}W, "
              f"comm_tx={state.power_profile.comm_tx_w}W, "
              f"compute={state.power_profile.compute_w}W")

        # Find key moments: eclipse transitions, comm start/end, compute start/end
        prev_eclipsed = False
        prev_ops = set()
        key_moments = []

        for entry in timeline:
            ops_set = set(entry.active_ops)
            # State transitions
            if entry.is_eclipsed != prev_eclipsed:
                event = "进入地影" if entry.is_eclipsed else "退出地影"
                key_moments.append((entry.t, event, entry.battery_pct,
                                    entry.solar_in_w, entry.total_load_w))
            # New operations started
            new_ops = ops_set - prev_ops
            ended_ops = prev_ops - ops_set
            for op in new_ops:
                key_moments.append((entry.t, f"开始:{op}", entry.battery_pct,
                                    entry.solar_in_w, entry.total_load_w))
            for op in ended_ops:
                key_moments.append((entry.t, f"结束:{op}", entry.battery_pct,
                                    entry.solar_in_w, entry.total_load_w))
            prev_eclipsed = entry.is_eclipsed
            prev_ops = ops_set

        if key_moments:
            print(f"  关键事件:")
            print(f"  {'时间':>8s} | {'事件':<30s} | {'电量%':>7s} | {'光伏W':>6s} | {'负载W':>6s} | {'净功率W':>7s}")
            print(f"  {'-'*8}-+-{'-'*30}-+-{'-'*7}-+-{'-'*6}-+-{'-'*6}-+-{'-'*7}")
            for t, event, pct, solar, load in key_moments[:20]:  # limit output
                net = solar - load
                print(f"  {t:>7.1f}s | {event:<30s} | {pct:>6.2f}% | {solar:>5.1f}W | {load:>5.1f}W | {net:>+6.1f}W")

        # Slope verification — check rates during different phases
        print(f"\n  斜率验证 (电量变化率):")
        # Sample at different phases
        samples = [(0, "初始"), (len(timeline)//4, "1/4处"),
                   (len(timeline)//2, "中间"), (3*len(timeline)//4, "3/4处")]
        for idx, label in samples:
            if idx < len(timeline) - 1:
                e = timeline[idx]
                print(f"    [{label}] t={e.t:.0f}s: "
                      f"电量={e.battery_pct:.2f}%, "
                      f"光伏={e.solar_in_w:.1f}W, "
                      f"负载={e.total_load_w:.1f}W, "
                      f"净={e.net_power_w:+.1f}W, "
                      f"{'🌑地影' if e.is_eclipsed else '☀光照'}, "
                      f"ops={e.active_ops if e.active_ops else 'idle'}")

    # --- Slope math verification ---
    print(f"\n{'=' * 70}")
    print(f"[数学验证 — 选取一颗计算星详细分析]")
    print(f"{'=' * 70}")

    # Pick first compute star with interesting activity
    comp_idx = len(tiange_sats)  # First compute star
    timeline = sim.energy.get_timeline(comp_idx)
    sat = all_sats[comp_idx]
    state = sim.energy.states[comp_idx]

    if timeline and len(timeline) > 10:
        cap_j = sat.battery_capacity_wh * 3600.0
        print(f"\n  卫星: {sat.id}")
        print(f"  电池容量: {sat.battery_capacity_wh} Wh = {cap_j:.0f} J")
        print(f"  充电效率: {state.charge_efficiency}, 放电效率: {state.discharge_efficiency}")

        # Compute actual vs expected slopes
        print(f"\n  逐段斜率对比 (实际 vs 理论):")
        print(f"  {'区间':>12s} | {'实际 %/min':>10s} | {'理论 %/min':>10s} | {'误差%':>6s} | {'状态'}")
        print(f"  {'-'*12}-+-{'-'*10}-+-{'-'*10}-+-{'-'*6}-+-{'─'*20}")

        # Sample pairs every 5 minutes
        step_interval = 300  # 5 min in seconds
        for seg_start in range(0, len(timeline) - step_interval, step_interval):
            seg_end = min(seg_start + step_interval, len(timeline) - 1)
            e_start = timeline[seg_start]
            e_end = timeline[seg_end]
            dt_min = (e_end.t - e_start.t) / 60.0
            if dt_min <= 0:
                continue

            actual_rate = (e_end.battery_pct - e_start.battery_pct) / dt_min

            # Theoretical: use average solar and load in this segment
            mid_idx = (seg_start + seg_end) // 2
            e_mid = timeline[mid_idx]
            net_w = e_mid.net_power_w
            # net_w positive → charging, pct change = net * 60 / cap_j * 100 * efficiency
            if net_w > 0:
                theory_rate = net_w * 60.0 * state.charge_efficiency / cap_j * 100.0
            else:
                theory_rate = net_w * 60.0 / state.discharge_efficiency / cap_j * 100.0

            error = abs(actual_rate - theory_rate) / max(abs(theory_rate), 0.001) * 100
            status = "光照" if not e_mid.is_eclipsed else "地影"
            ops = e_mid.active_ops if e_mid.active_ops else ["idle"]
            print(f"  {e_start.t:>5.0f}-{e_end.t:>5.0f}s | {actual_rate:>+9.4f} | "
                  f"{theory_rate:>+9.4f} | {error:>5.1f}% | {status} {','.join(ops[:2])}")

    print(f"\n{'=' * 70}")
    print(f"[完成] 能量验证场景执行完毕")
    print(f"{'=' * 70}")


if __name__ == "__main__":
    run_energy_validation()
