# SatLynk

**LEO 卫星星座任务调度仿真器** — 面向天基智能体的离散事件仿真平台

<p align="center">
  <img src="docs/viz-screenshot.png" width="800" alt="SatLynk 3D Visualization">
</p>

## Background

随着天基计算从"天感地算"走向"天感天算"，在轨 AI 推理成为现实需求。但 LEO 卫星星座面临独特的调度挑战：

- **通信窗口时变**：卫星之间的链路受轨道几何约束，每次接触窗口仅数分钟
- **能耗刚性约束**：太阳能供电 + 地影周期性断供，电池容量有限
- **模型权重部署**：大模型权重需预先缓存到目标节点，"搬权重"本身消耗带宽
- **实时性要求**：科学观测事件（如伽马射线暴）有严格的响应时间窗口

SatLynk 聚焦于这一调度问题的建模与仿真——给定星座构型、任务流、约束条件，评估不同调度策略的可行性和性能。

## Core Scenario

**天格计划 × 三体计算星座：GRB 在轨推理**

| 角色 | 卫星 | 参数 |
|------|------|------|
| 探测星 | 天格 GRID-10B/11B | 535km SSO, SiPM+CsI 探测器, 100 MFLOPS MCU |
| 计算星 | 三体计算星座 | 550km 53°, 100 TOPS INT8, 星间激光互联 |

任务流：GRB 触发 → MCU 预处理 → **500KB 上传 (2Mbps)** → **2B 模型推理 (8ms)** → 50KB 回传 → 决策执行

### 仿真结果

| 场景 | 计算星规模 | 成功率 | 平均延时 | 关键发现 |
|------|-----------|--------|---------|---------|
| 稀疏星座 | 4 颗 | **17%** | 3.0s | 链路门控 (C2) 主导，大部分触发时刻无可达计算星 |
| 三体最终形态 | 2800 颗 | **92%** | 24.8s | 星座密度是解决时空可达性的根本途径 |
| 展示版 | 100 颗 | **100%** | ~20s | ~87% 时间步可达，覆盖临界点在 50-100 颗 |

## Benchmark Cases

8 个基准场景，量化"静态拓扑假设"的系统性偏差：

| Case | 场景 | 动态仿真 | 静态 Baseline | 偏差 |
|------|------|---------|--------------|------|
| 1 | GRB 带宽争抢 | LB 21.8s | NF 60.8s | 3.0× 延迟低估 |
| 2 | 地影能耗 | EA 100% 成功 | NF 0% 成功 | 100pp 高估 |
| 3 | 权重迁移 | C4 约束生效 | 假设权重已到位 | ∞ |
| 4 | 多跳中继 | store-forward 26s | 假设直达 16s | 1.6× |
| 5 | 船舶 AoI | 8星51s / 12星17s | — | 2.8-8.5× AoI 低估 |
| 6 | 联邦学习 | 1/19 梯度到达 | 全部到达 | 虚假收敛保证 |
| 7 | 碎片预警 | 在轨3s | 地面50min | 地面超 deadline |
| 8 | 山火检测 | offload 80s | 本地0.03s | 大图+窄链→offload更慢 |

运行：`python -m satlynk.scenarios.case1_grb_bandwidth` ... `case8_wildfire_detection`

## Scheduler Comparison

6 种调度器 + Oracle 上界：

| 调度器 | 策略 | 15星场景成功率 |
|--------|------|---------------|
| Random | 随机分配 | ~36% |
| Nearest-First | 最近距离贪心 | 57.1% |
| Shortest-Path | 最小端到端延迟 | **64.3%** |
| CGR+EDF | Contact Graph Routing + 最早截止 | **64.3%** |
| TEG | 时空扩展图 Dijkstra | **64.3%** |
| Oracle | 穷举最优 | **64.3%** (物理上限) |

运行 benchmark：`python -m satlynk.benchmark`

## Features

- **离散事件仿真引擎** — 事件驱动 + 时间步混合，支持 idle 时自动跳步
- **轨道力学** — Keplerian 二体传播 + Walker-Delta 星座生成
- **通信模型** — 距离 + 视线 (LoS) 判定，自动生成 Contact Plan
- **时空扩展图 (TEG)** — 将时变网络展开为静态有向图，Dijkstra 路由
- **地影模型** — 柱形阴影 + 向量化计算，影响光伏充电
- **能耗模型** — Component-based 电池动力学 + 功耗模式迁移（磁滞）
- **权重缓存** — C4 约束实现，LRU/LFU/Priority 淘汰策略
- **多跳中继** — Store-and-forward，BFS 路由 + 链式转发
- **带宽共享** — 同一链路多传输公平分带宽
- **可插拔调度器** — Protocol 接口，9 种实现开箱即用
- **Benchmark 框架** — 一键对比所有调度器 × 所有场景
- **Static Baseline** — 量化静态假设的系统性偏差
- **3D 可视化** — Three.js 地球 + 卫星轨道 + 任务流播放（单 HTML 文件）

## Quick Start

### 环境要求

- Python ≥ 3.11
- NumPy (唯一必需依赖)

```bash
git clone https://github.com/yuyangJin/SatLynk.git
cd SatLynk
pip install .            # 基础安装
pip install .[solver]    # 若需 Oracle MILP (OR-Tools)
```

### 运行场景

```bash
# 天格 GRB 场景 — 3 探测星 + 4 计算星
python -m satlynk.scenarios.tiange_grb

# 2800 星全规模场景
python -m satlynk.scenarios.tiange_2800

# Benchmark Case 场景 (case1 ~ case8)
python -m satlynk.scenarios.case1_grb_bandwidth

# 多调度器对比 benchmark
python -m satlynk.benchmark

# Static Baseline 对比
python -m satlynk.baselines.compare_all
```

### 生成 3D 可视化

```bash
python -m satlynk.viz.generate_tiange
# 输出 → output/index.html，用浏览器打开即可
```

### 运行测试

```bash
pytest satlynk/tests/
# 或单独运行
python -m satlynk.tests.test_integration
python -m satlynk.tests.test_phase2
python -m satlynk.tests.test_teg
```

## Architecture

```
satlynk/
├── core/
│   ├── engine.py            # DES 事件引擎
│   └── simulator.py         # 主仿真器（集成所有模块，~870行）
├── orbital/
│   ├── constellation.py     # Walker 星座生成 + 轨道传播
│   └── eclipse.py           # 地影计算（柱形阴影模型）
├── network/
│   ├── contact_plan.py      # 通信窗口预计算
│   └── teg.py               # 时空扩展图 (Time-Expanded Graph)
├── energy/
│   └── battery.py           # Component-based 能耗模型
├── task/
│   ├── dag.py               # Task DAG 数据结构
│   └── weight_cache.py      # 模型权重缓存管理 (LRU/LFU)
├── scheduler/
│   ├── interface.py         # Scheduler Protocol + NearestFirst
│   ├── heuristics.py        # Random / ShortestPath / CGR+EDF
│   ├── oracle.py            # 穷举最优（小规模上界）
│   ├── oracle_milp.py       # CP-SAT 精确解 (OR-Tools)
│   ├── teg_scheduler.py     # 基于 TEG 的路由调度
│   ├── energy_aware.py      # 能量感知调度
│   └── load_balanced.py     # 负载均衡（带宽感知）
├── baselines/
│   ├── static_topology.py   # 静态拓扑 baseline
│   └── compare_all.py       # 动态 vs 静态对比
├── metrics/
│   └── collector.py         # 仿真指标收集
├── viz/
│   ├── exporter.py          # JSON 数据导出
│   ├── build_frontend.py    # Three.js HTML 生成
│   └── generate_*.py        # 各场景可视化脚本
├── scenarios/
│   ├── case1..case8         # 8 个 benchmark case
│   ├── tiange_grb.py        # 3+4 星 GRB 场景
│   ├── tiange_2800.py       # 3+2800 星全规模
│   └── energy_validation.py # 能耗模型精度验证
├── benchmark.py             # 多调度器对比框架
└── tests/
    ├── test_integration.py
    ├── test_phase2.py
    └── test_teg.py
```

详细架构文档见 [docs/architecture.md](docs/architecture.md)。

## Formal Model

仿真器实现了以下形式化调度约束：

| 约束 | 含义 | 实现模块 |
|------|------|---------|
| C1 | 执行唯一性：每个子任务恰好在一个节点执行一次 | `scheduler/` TaskAssignment |
| C2 | 链路门控：传输只能在通信窗口内发生 | `network/` ContactPlan + LINK events |
| C3 | 依赖就绪：输入数据到达后才能开始计算 | `core/simulator.py` Transfer→Compute 链 |
| C4 | 权重前置：模型权重必须预先缓存在目标节点 | `task/weight_cache.py` |
| C5 | 能量动力学：电池 SoC 不能降到 0 | `energy/battery.py` + eclipse |
| C6 | 存储约束：节点缓存容量有限 | `task/weight_cache.py` LRU/LFU |

## Documentation

- [`docs/architecture.md`](docs/architecture.md) — 代码架构、类关系图、开发指南
- [`docs/input-configuration.md`](docs/input-configuration.md) — 输入参数配置说明
- [`docs/scenarios/`](docs/scenarios/) — 各 Benchmark Case 的场景设计文档

## License

MIT
