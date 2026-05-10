"""
天格-天基计算卫星联合场景：GRB 探测 + 在轨推理
==================================================

背景：
  天格计划（GRID）= 清华大学发起的"空间分布式伽马射线暴探测网"，
  截至 2024.11 已成功发射 10+ 颗卫星载荷（搭载于吉林一号等平台），
  使用 SiPM + CsI(Tl) 闪烁体探测器，实现纳卫星伽马暴多星在轨观测。
  
  三体计算星座 = 之江实验室 2025.5.14 首批 12 星入轨的天基智能计算
  基础设施，单星算力比传统卫星提升 10× 以上，搭载星载智能计算机、
  星间激光通信机（24 套终端），已验证三星组网在轨 AI 推理。

任务流：
  1. 天格探测卫星观测到伽马射线暴候选事件
  2. 本地 MCU 做初步脉冲筛选 + 光变曲线提取（排除宇宙线等噪声）
  3. 将预处理后的光变曲线/能谱数据通过 ISL 上传至天基计算卫星
  4. 天基计算卫星运行 2B 参数量化模型做 GRB 分类/定位/关联判断
  5. 决策结果回传天格卫星（触发高通量模式、联合多星三角定位等）

星座配置（本场景简化）：
  - 天格探测星：3 颗，搭载于 6U CubeSat 平台，~535km SSO
    参考 GRID-10B/11B：24h 全天观测，支持在轨自适应模式切换
    算力极低（ARM Cortex-M7 / FPGA ~100 MFLOPS），仅做触发和预处理
  - 天基计算星：4 颗，550km 53° Walker(4/2/1)
    参考三体计算星座：星载智能计算机 + 星间激光互联
    算力约 100 TOPS INT8（~1 TFLOPS FP16），可运行 2B 量化模型

2B 模型推理估算（GRB 分类/定位模型）：
  - 模型权重：~4 GB（INT4 量化后的 2B 参数 Transformer）
  - 单次推理 FLOPs：约 4×10^9 FLOP（前向传播，batch=1）
  - 在 1 TFLOPS FP16 芯片上耗时：~4s（考虑内存带宽瓶颈实际 ~8s）
  - 输入数据：光变曲线 + 能谱矩阵 ~500 KB
  - 输出：分类概率 + 天区定位概率图 + 决策指令 ~50 KB
  
通信参数：
  - 天格星 ISL：S-band ~2 Mbps（受限于 6U 平台功耗和天线尺寸）
  - 计算星 ISL：激光通信 ~1 Gbps 星间 / X-band 50 Mbps 备份
  - 本场景瓶颈在天格星的 2 Mbps 上行（决定端到端用什么速率）
"""

import sys

import numpy as np
from satlynk.core.simulator import Simulator, SimConfig
from satlynk.orbital.constellation import (
    Satellite, Role, OrbitalElements, generate_walker_delta,
)
from satlynk.task.dag import TaskDAG, SubTask, DataDependency
from satlynk.scheduler.interface import NearestFirstScheduler


def create_tiange_constellation():
    """
    创建天格 + 天基计算星混合星座。
    
    天格卫星参数（参考 GRID-10B/11B 载荷 + 吉林一号平台）：
    - 6U CubeSat (~8-12 kg)
    - SiPM + CsI(Tl) 闪烁体探测器，带电粒子屏蔽
    - 算力：ARM Cortex-M7 + FPGA ~100 MFLOPS（触发判定 + 光变曲线提取）
    - 通信：UHF 9.6 kbps 下行, S-band 2 Mbps ISL
    - 功耗：~5W 载荷, ~12W 整星
    - 电池：~40 Wh (6U 标准)
    - 轨道：~535km SSO（搭载于吉林一号平台）
    
    天基计算星参数（参考三体计算星座首发星）：
    - 小卫星平台 ~50-100 kg
    - 星载智能计算机（之江自研）
    - 算力：~100 TOPS INT8 = 约 1 TFLOPS FP16（单星算力比传统卫星提升 10×）
    - 通信：星间激光 ~1 Gbps + X-band 50 Mbps 备份
    - 存储：64 GB（足够存多个 2B 量化模型）
    - 功耗：~50W 峰值（AI 推理），20W 待机
    - 电池：~300 Wh
    - 太阳能：~80W（展板）
    - 轨道：~550km，53° 倾角
    """
    # --- 天格探测星 (3颗, 535km SSO, 搭载于吉林一号等平台) ---
    tiange_sats = []
    tiange_raans = [0.0, 120.0, 240.0]  # 均匀分布在 SSO 轨道面
    for i, raan in enumerate(tiange_raans):
        sat = Satellite(
            id=f"TIANGE-{i+1:02d}",
            role=Role.DETECTOR,
            elements=OrbitalElements(
                semi_major_axis_km=6906.0,  # 535 km（吉林一号平台轨道）
                inclination_deg=97.5,        # SSO
                raan_deg=raan,
                true_anomaly_deg=i * 60.0,   # 相位错开
            ),
            compute_flops=100e6,             # 100 MFLOPS (ARM Cortex-M7 + FPGA)
            storage_bytes=int(4e9),          # 4 GB
            max_comm_range_km=3000.0,        # S-band ISL 最大通信距离
            power_solar_w=12.0,              # 6U CubeSat 太阳能
            battery_capacity_wh=40.0,        # 6U 电池
        )
        tiange_sats.append(sat)

    # --- 天基计算星 (4颗, 550km Walker-Delta, 参考三体计算星座) ---
    compute_sats = generate_walker_delta(
        total_sats=4,
        num_planes=2,
        phase_factor=1,
        altitude_km=550,
        inclination_deg=53.0,
        role=Role.COMPUTE,
        prefix="COMPUTE",
        compute_flops=1e12,              # ~1 TFLOPS FP16（100 TOPS INT8）
        storage_bytes=int(64e9),         # 64 GB
        max_comm_range_km=5000.0,        # 激光/X-band 通信距离
        power_solar_w=80.0,              # 小卫星展板
        battery_capacity_wh=300.0,       # 大容量电池
    )

    return tiange_sats, compute_sats


def create_grb_task(task_id: str, source_node: int, arrival_time: float,
                    model_name: str = "grb_classifier_2b") -> TaskDAG:
    """
    创建一个 GRB 探测→推理 任务。

    任务结构 (DAG):
        [local_filter] → [upload] → [model_infer] → [return_result]
    
    简化为单一 SubTask（推理），因为：
    - 本地滤波由天格星 MCU 在触发时已完成（不占调度资源）
    - 传输由 simulator 自动处理
    - 核心调度决策是：送到哪颗计算星做推理
    """
    task = TaskDAG(
        id=task_id,
        source_node=source_node,
        arrival_time_s=arrival_time,
        subtasks=[
            SubTask(
                id=f"{task_id}_infer",
                compute_flops=8e9,             # 2B 模型前向 ~4 GFLOP 理论, 含内存瓶颈实际 ~8 GFLOP 等效
                required_model=model_name,      # 需要模型权重在目标节点
                model_size_bytes=int(4e9),      # 4 GB INT4 量化权重
                output_size_bytes=50_000,       # 50 KB: 分类概率 + 天区定位 + 决策指令
            ),
        ],
        dependencies=[],
        global_deadline_s=120.0,               # 2 分钟内必须完成（GRB 时效性）
        result_destination=source_node,        # 结果回传探测星
        result_size_bytes=50_000,              # 50 KB
    )
    # 输入数据：MCU 预处理后的光变曲线 + 多通道能谱
    task.input_size_bytes = 500_000            # 500 KB
    return task


def run_tiange_scenario():
    """运行天格 GRB 场景仿真。"""
    print("=" * 70)
    print("SatLynk — 天格计划 × 天基计算卫星：GRB 在轨推理场景")
    print("=" * 70)

    # --- 场景参数 ---
    duration_s = 3600.0  # 1 小时仿真
    config = SimConfig(
        duration_s=duration_s,
        dt=1.0,
        data_rate_bps=2e6,            # 2 Mbps ISL (天格S-band限制，整条链路瓶颈)
        compute_flops_default=1e12,   # 计算星默认算力 1 TFLOPS FP16
        idle_power_w=5.0,             # 待机功耗
        compute_power_w=30.0,         # AI 推理额外功耗
        comm_power_w=3.0,             # 通信功耗
    )

    # --- 生成星座 ---
    tiange_sats, compute_sats = create_tiange_constellation()
    all_sats = tiange_sats + compute_sats  # index 0-2: 天格, 3-6: 计算星

    print(f"\n[星座配置]")
    print(f"  天格探测星: {len(tiange_sats)} 颗 (535km SSO)")
    for sat in tiange_sats:
        print(f"    {sat.id}: RAAN={sat.elements.raan_deg:.0f}°, "
              f"ν={sat.elements.true_anomaly_deg:.0f}°, "
              f"算力={sat.compute_flops/1e6:.0f} MFLOPS")
    print(f"  天基计算星: {len(compute_sats)} 颗 (550km, 53° Walker)")
    for sat in compute_sats:
        print(f"    {sat.id}: RAAN={sat.elements.raan_deg:.0f}°, "
              f"ν={sat.elements.true_anomaly_deg:.0f}°, "
              f"算力={sat.compute_flops/1e12:.0f} TFLOPS")

    # --- 初始化模拟器 ---
    sim = Simulator(config)
    sim.set_satellites(all_sats)
    
    # 预装模型权重到计算星
    model_name = "grb_classifier_2b"
    model_size = int(4e9)  # 4 GB
    sim.weight_mgr.register_model(model_name, model_size)
    # 每颗计算星都预装了模型（实际场景中可能不一定都有）
    for i in range(3, 7):
        sim.weight_mgr.cache_weight(i, model_name, t=0.0)

    print(f"\n[模型配置]")
    print(f"  模型: {model_name}")
    print(f"  权重大小: {model_size/1e9:.1f} GB (INT4 量化)")
    print(f"  推理算力需求: 8 GFLOP/次 (含内存带宽等效)")
    print(f"  预装节点: COMPUTE-000-000 ~ COMPUTE-001-001")
    print(f"  推理延时(理论): {8e9/1e12*1000:.0f} ms (1 TFLOPS 芯片)")

    # --- 轨道传播 + Contact Plan ---
    print(f"\n[轨道计算...]")
    sim.precompute_orbits()
    
    print(f"  仿真时长: {duration_s:.0f}s ({duration_s/60:.0f} min)")
    print(f"  通信窗口总数: {len(sim.contact_plan)}")
    
    # 统计各天格星的链路情况
    print(f"\n[通信链路分析]")
    for det_idx in range(3):
        windows_from_det = [w for w in sim.contact_plan.windows
                           if w.src == det_idx or w.dst == det_idx]
        total_contact = sum(w.duration_s for w in windows_from_det)
        print(f"  {tiange_sats[det_idx].id}: "
              f"{len(windows_from_det)} 窗口, "
              f"总接触时间 {total_contact:.0f}s "
              f"({total_contact/duration_s*100:.1f}%)")
    
    # 统计地影
    if sim.eclipse_map is not None:
        print(f"\n[地影分析]")
        for i, sat in enumerate(all_sats):
            eclipse_frac = sim.eclipse_map[i].sum() / len(sim.times) * 100
            print(f"  {sat.id}: {eclipse_frac:.1f}% 时间在地影中")

    # --- 生成 GRB 事件 (泊松过程) ---
    # 实际 GRB 触发率约 1/天（全天），天格 3 星视场覆盖约 2sr
    # 为了仿真效果，假设 1 小时内有 6 次触发事件（加速场景）
    np.random.seed(42)
    n_events = 6
    event_times = np.sort(np.random.uniform(60, duration_s - 300, n_events))
    # 随机分配到各天格星
    event_sources = np.random.randint(0, 3, n_events)

    print(f"\n[GRB 触发事件]")
    print(f"  总触发数: {n_events}")
    tasks = []
    for i, (t, src) in enumerate(zip(event_times, event_sources)):
        task = create_grb_task(
            task_id=f"grb_{i:03d}",
            source_node=int(src),
            arrival_time=float(t),
            model_name=model_name,
        )
        sim.add_task(task)
        tasks.append(task)
        print(f"  GRB #{i}: t={t:.0f}s, 源={tiange_sats[src].id}, "
              f"数据={task.input_size_bytes/1000:.0f} KB")

    # --- 运行仿真 ---
    print(f"\n[运行仿真...]")
    sim.enable_viz_recording()
    metrics = sim.run()

    # --- 结果分析 ---
    print(f"\n{'=' * 70}")
    print(f"[仿真结果]")
    print(f"{'=' * 70}")
    print(f"  处理事件数: {metrics.events_processed}")
    print(f"  任务完成: {metrics.completed_tasks}/{metrics.total_tasks}")
    print(f"  成功率: {metrics.success_rate:.0%}")
    if metrics.completed_tasks > 0:
        print(f"  平均 makespan: {metrics.avg_makespan_s:.1f}s")
        print(f"  最大 makespan: {metrics.max_makespan_s:.1f}s")
    print(f"  总传输数据: {metrics.total_data_transferred_bytes/1e6:.2f} MB")
    print(f"  最低电池: {metrics.min_battery_pct:.1f}%")
    print(f"  仿真耗时: {metrics.wall_clock_s:.3f}s")

    # 逐任务分析
    print(f"\n[逐任务结果]")
    print(f"  {'任务ID':<10} {'源星':<12} {'到达(s)':<10} "
          f"{'Makespan(s)':<14} {'状态':<8}")
    print(f"  {'-'*60}")
    
    successful = 0
    for result in sim.metrics.task_results:
        task = sim._tasks[result.task_id]
        src_name = tiange_sats[task.source_node].id
        status = "✓ 完成" if result.success else "✗ 超时"
        if result.success:
            successful += 1
        print(f"  {result.task_id:<10} {src_name:<12} "
              f"{task.arrival_time_s:<10.0f} "
              f"{result.makespan_s:<14.1f} {status}")

    # --- 性能分析 ---
    print(f"\n[性能分析]")
    if metrics.completed_tasks > 0:
        # 理论最优：直连时延
        theory_transfer = 500_000 * 8 / 2e6  # 500KB / 2Mbps = 2s
        theory_infer = 8e9 / 1e12             # 8 GFLOP / 1 TFLOPS = 8ms
        theory_return = 50_000 * 8 / 2e6      # 50KB / 2Mbps = 0.2s
        theory_total = theory_transfer + theory_infer + theory_return
        
        print(f"  理论最优 makespan (直连、无等待): {theory_total:.2f}s")
        print(f"    - 数据上传: {theory_transfer:.2f}s (500KB @ 2Mbps S-band)")
        print(f"    - 模型推理: {theory_infer*1000:.1f}ms (8 GFLOP @ 1 TFLOPS)")
        print(f"    - 结果回传: {theory_return:.3f}s (50KB @ 2Mbps)")
        print(f"  实际平均 makespan: {metrics.avg_makespan_s:.1f}s")
        print(f"  调度开销比: {metrics.avg_makespan_s / theory_total:.1f}× 理论最优")
        if metrics.avg_makespan_s > 10:
            print(f"  → 瓶颈: 通信窗口等待 (天格 SSO 与计算星 53° 轨道交叉窗口短)")
        else:
            print(f"  → 主导因素: 传输延时 (2 Mbps S-band 上行)")
    
    # 能耗分析
    print(f"\n[能耗状态]")
    for i, sat in enumerate(all_sats):
        batt_pct = sim.energy.get_battery_pct(i)
        sat_type = "探测" if sat.role == Role.DETECTOR else "计算"
        print(f"  {sat.id} ({sat_type}): 电池 {batt_pct:.1f}%")

    # --- 输出可视化数据 ---
    if sim.viz:
        import os
        output_dir = os.path.join(os.getcwd(), "output")
        os.makedirs(output_dir, exist_ok=True)
        export_path = os.path.join(output_dir, "tiange_grb_export.json")
        sim.viz.export_to_file(export_path)
        fsize = os.path.getsize(export_path)
        print(f"\n[可视化数据]")
        print(f"  输出: {export_path}")
        print(f"  大小: {fsize/1024:.1f} KB")

    print(f"\n{'=' * 70}")
    print(f"[结论]")
    if metrics.success_rate >= 0.8:
        print(f"  ✓ 高成功率 ({metrics.success_rate:.0%})：星座覆盖良好，")
        print(f"    天格星在大部分触发时刻能找到可达的计算星。")
    elif metrics.success_rate >= 0.5:
        print(f"  △ 中等成功率 ({metrics.success_rate:.0%})：存在盲区，")
        print(f"    部分 GRB 触发时无可用链路，需优化星座构型或增加节点。")
    else:
        print(f"  ✗ 低成功率 ({metrics.success_rate:.0%})：通信瓶颈严重，")
        print(f"    稀疏星座下 Nearest-First 策略无法保证实时性。")
    print(f"{'=' * 70}")

    return metrics


if __name__ == "__main__":
    metrics = run_tiange_scenario()
    sys.exit(0 if metrics.success_rate > 0 else 1)
