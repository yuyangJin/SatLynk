# SatLynk 代码架构文档

> **SatLynk** — LEO Satellite Constellation Task Scheduling Simulator  
> 面向低轨卫星星座的天基智能体任务调度离散事件仿真器。

---

## 目录

1. [项目概览](#项目概览)
2. [目录结构](#目录结构)
3. [分层架构](#分层架构)
4. [模块详解](#模块详解)
5. [核心数据流](#核心数据流)
6. [类关系图](#类关系图)
7. [调度器体系](#调度器体系)
8. [仿真运行流程](#仿真运行流程)
9. [如何添加新调度器](#如何添加新调度器)
10. [如何添加新场景](#如何添加新场景)

---

## 项目概览

SatLynk 是一个 **离散事件仿真器 (DES)**，模拟 LEO 卫星星座中的任务调度问题。核心关注：

- **时变拓扑**：卫星间通信链路随轨道运动出现/消失
- **能量约束**：太阳能充电 + 地影放电 + 负载功耗
- **计算卸载**：探测星产出数据 → 通过 ISL 转发 → 计算星推理 → 结果回传
- **带宽争抢**：多任务并发时共享有限链路带宽

## 目录结构

```
satlynk/
├── __init__.py              # 版本声明
├── benchmark.py             # 多调度器对比框架
├── core/
│   ├── engine.py            # DES 事件引擎
│   └── simulator.py         # 主集成类（872 行，最核心）
├── orbital/
│   ├── constellation.py     # 卫星定义 + Walker 星座生成 + 轨道传播
│   └── eclipse.py           # 地影模型（柱形阴影）
├── network/
│   ├── contact_plan.py      # 通信窗口预计算
│   └── teg.py               # 时空扩展图 (Time-Expanded Graph)
├── energy/
│   └── battery.py           # Component-based 能耗模型
├── task/
│   ├── dag.py               # 任务 DAG 数据结构
│   └── weight_cache.py      # 模型权重缓存 + LRU/LFU 淘汰
├── scheduler/
│   ├── interface.py         # Scheduler Protocol + NearestFirst baseline
│   ├── heuristics.py        # Random / ShortestPath / CGR+EDF
│   ├── oracle.py            # 穷举最优（小规模）
│   ├── oracle_milp.py       # CP-SAT 最优（OR-Tools）
│   ├── teg_scheduler.py     # 基于 TEG 的调度
│   ├── energy_aware.py      # 能量感知调度
│   └── load_balanced.py     # 负载均衡调度
├── baselines/
│   ├── static_topology.py   # 静态拓扑 baseline（MEC 论文假设）
│   └── compare_all.py       # SatLynk vs Static 对比脚本
├── metrics/
│   └── collector.py         # KPI 收集器
├── scenarios/               # 可执行的仿真场景
│   ├── case1_grb_bandwidth.py    ... case8_wildfire_detection.py
│   ├── tiange_grb.py        # 天格 + 计算星座场景
│   ├── tiange_2800.py       # 2800 星大规模场景
│   └── energy_validation.py # 能耗模型精度验证
├── viz/
│   ├── exporter.py          # 仿真数据 → JSON 导出
│   ├── build_frontend.py    # JSON → Three.js 3D 可视化 HTML
│   └── generate_*.py        # 各场景可视化生成脚本
└── tests/                   # pytest 测试套件
```

---

## 分层架构

```
┌─────────────────────────────────────────────────────────────────────┐
│                         Scenarios / Benchmark                        │
│  (case1..case8, tiange_grb, benchmark.py — 组装星座+任务+调度器)       │
├─────────────────────────────────────────────────────────────────────┤
│                            Simulator                                 │
│  (core/simulator.py — 集成层，驱动整个仿真循环)                         │
├────────┬──────────┬───────────┬──────────┬───────────┬──────────────┤
│Scheduler│  Task    │  Network  │  Energy  │  Orbital  │   Metrics   │
│(可插拔) │  Engine  │  Layer    │  Model   │  Dynamics │   & Viz     │
├────────┼──────────┼───────────┼──────────┼───────────┼──────────────┤
│interface│ dag.py   │contact_   │battery.py│constella- │collector.py │
│heurist-│ weight_  │ plan.py   │          │ tion.py   │exporter.py  │
│ics.py  │ cache.py │teg.py     │          │eclipse.py │build_front- │
│oracle.py│         │           │          │           │ end.py      │
│teg_sch.│         │           │          │           │             │
└────────┴──────────┴───────────┴──────────┴───────────┴──────────────┘
                              │
                    ┌─────────┴─────────┐
                    │   DES Engine      │
                    │  (core/engine.py) │
                    └───────────────────┘
```

**依赖方向**：上层依赖下层，同层模块互不依赖（除 Network → Orbital）。

---

## 模块详解

### `core/engine.py` — DES 事件引擎

| 类/枚举 | 说明 |
|---------|------|
| `EventType(Enum)` | 事件类型：LINK_UP, LINK_DOWN, TASK_ARRIVE, COMPUTE_DONE, TRANSFER_DONE 等 |
| `Event(dataclass)` | 事件体：time + priority + type + payload |
| `DESEngine` | 核心引擎，堆排序事件 + 固定步长回调 + 空闲时间跳跃 |

关键方法：
- `schedule(event)` / `schedule_batch(events)` — 注入事件
- `register_handler(event_type, fn)` — 事件驱动回调
- `register_step_callback(fn)` — 每 Δt 调用（推进 transfer/compute 进度）
- `run()` — 主循环

### `core/simulator.py` — 主集成类

**Simulator** 是最核心的类（~870 行），负责：
1. 初始化所有子系统（轨道、网络、能耗、任务引擎）
2. 预计算轨道位置和通信窗口
3. 注册 DES 事件处理器
4. 驱动 transfer 和 compute 的步进推进
5. 收集 metrics 和 viz 数据

| 类 | 说明 |
|----|------|
| `SimConfig(dataclass)` | 仿真参数：duration_s, dt, data_rate_bps, compute_flops_default |
| `Transfer(dataclass)` | 在途数据传输状态 |
| `ComputeJob(dataclass)` | 在运算节点上的计算任务 |
| `Simulator` | 主类 |

### `orbital/constellation.py` — 轨道与星座

| 类 | 说明 |
|----|------|
| `Role(Enum)` | 卫星角色：COMPUTE, DETECTOR, RELAY, HYBRID |
| `OrbitalElements(dataclass)` | 开普勒轨道根数 (a, i, Ω, ν) |
| `Satellite(dataclass)` | 卫星实例，包含硬件参数（FLOPS、电池容量、通信距离等） |

关键函数：
- `generate_walker_delta(n, planes, f, ...)` — 生成 Walker-δ 星座
- `propagate_positions(sats, times)` — 两体开普勒传播 (ECI)
- `compute_distances(positions)` — 向量化距离矩阵
- `check_line_of_sight(pos_i, pos_j)` — 地球遮挡判断

### `orbital/eclipse.py` — 地影模型

- `compute_eclipse_schedule_vectorized(positions, times)` → `(N,T) bool mask`
- 柱形阴影模型，约 33% 轨道周期在影中

### `network/contact_plan.py` — 通信窗口

| 类 | 说明 |
|----|------|
| `ContactWindow(dataclass)` | 一次通信机会：src, dst, start_s, end_s, avg_rate_bps |
| `ContactPlan` | 窗口集合 + 索引查询 |

关键函数：
- `compute_contact_plan(sats, times, positions, ...)` — 预计算所有卫星对的可见窗口

### `network/teg.py` — 时空扩展图

将时变网络展开为静态有向图，支持图算法路由。

| 类 | 说明 |
|----|------|
| `EdgeType(Enum)` | STORE（同星跨时隙）, TRANSFER（星间传输）, COMPUTE（计算耗时） |
| `TEGNode(frozen dataclass)` | 顶点 (sat_id, time_slot) |
| `TEGEdge(dataclass)` | 有向边，含容量和代价 |
| `TEGPath(dataclass)` | 路径查询结果 |
| `TimeExpandedGraph` | TEG 核心类 |

关键方法：
- `from_contact_plan(plan, sats, duration, slot_size)` — 工厂方法
- `shortest_path(src, dst, depart, data_bytes)` — Dijkstra 最短路径
- `earliest_arrival(src, dst, depart)` — 最早到达
- `reachable_nodes(src, depart, deadline)` — 可达性分析

### `energy/battery.py` — 能耗模型

Component-based 设计，每颗星维护独立的功耗组件集合。

| 类 | 说明 |
|----|------|
| `PowerMode(Enum)` | FULL, LOW_POWER, SAFE_MODE, OFF |
| `PowerComponent(Enum)` | BASE, DETECTOR, COMM_TX, COMM_RX, COMPUTE, HEATER |
| `PowerProfile(dataclass)` | 每种组件的功耗瓦数 |
| `BatteryState(dataclass)` | 单节点能量状态 |
| `EnergyModel` | 全局能量管理器 |

关键方法：
- `activate_component(node, op_id, comp)` / `deactivate_component(node, op_id)` — 动态负载
- `step(t, dt)` — 推进能量变化（充电/放电 + 模式迁移带磁滞）
- `has_enough_energy(node, joules)` — 调度器可查询的能量预算

### `task/dag.py` — 任务 DAG

| 类 | 说明 |
|----|------|
| `TaskState(Enum)` | PENDING, WAITING_DATA, COMPUTING, DONE |
| `SubTask(dataclass)` | 原子计算单元：compute_flops, required_model, model_size_bytes |
| `DataDependency(dataclass)` | DAG 边：src_task → dst_task + data_size_bytes |
| `TaskDAG(dataclass)` | 有向无环任务图 |

### `task/weight_cache.py` — 权重缓存

| 类 | 说明 |
|----|------|
| `EvictionPolicy(Enum)` | LRU, LFU, PRIORITY |
| `WeightCache` | 单节点本地缓存（容量受限 + 淘汰） |
| `WeightCacheManager` | 全局缓存管理器，支持 `find_nearest_source()` 触发权重迁移 |

### `scheduler/` — 调度器体系

见下方 [调度器体系](#调度器体系) 专节。

### `metrics/collector.py`

| 类 | 说明 |
|----|------|
| `TaskResult(dataclass)` | 单任务结果：makespan_s, success, relay_hops |
| `SimMetrics(dataclass)` | 聚合 KPI：success_rate, avg_makespan_s, min_battery_pct |
| `MetricsCollector` | 仿真过程中收集统计 |

### `viz/` — 可视化

| 文件 | 说明 |
|------|------|
| `exporter.py` | `VizRecorder` 挂接 Simulator，捕获位置/事件/传输/能耗时间线 → JSON |
| `build_frontend.py` | 将 JSON 注入 Three.js HTML 模板，生成 3D 可视化单文件 |
| `generate_*.py` | 各场景的可视化生成入口 |

---

## 核心数据流

```
                         ┌───────────────┐
                         │   Scenario    │
                         │ (定义星座+任务) │
                         └──────┬────────┘
                                │ create
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                          Simulator                               │
│                                                                  │
│  1. precompute_orbits()                                          │
│     ├─ propagate_positions() ──→ positions (N×T×3)               │
│     ├─ compute_contact_plan() ──→ ContactPlan                    │
│     └─ compute_eclipse_schedule() ──→ eclipse_mask (N×T)         │
│                                                                  │
│  2. DESEngine.run() ← 事件循环                                    │
│     │                                                            │
│     ├─ LINK_UP/DOWN events ──→ 更新活跃链路集合                    │
│     │                                                            │
│     ├─ TASK_ARRIVE ──→ scheduler.on_task_arrive(task, env)       │
│     │                   └──→ Schedule (assignments)               │
│     │                        └──→ _apply_schedule()              │
│     │                             ├─ 启动 Transfer (input data)  │
│     │                             └─ 或 启动 ComputeJob          │
│     │                                                            │
│     ├─ step_callback(dt):                                        │
│     │   ├─ _step_transfers() ──→ 推进传输进度 (带宽共享)           │
│     │   ├─ _step_computes() ──→ 推进计算进度                      │
│     │   └─ energy.step() ──→ 更新电池状态                         │
│     │                                                            │
│     ├─ TRANSFER_DONE ──→ 触发下一阶段                             │
│     │   ├─ input done → 开始计算                                  │
│     │   ├─ compute done → 回传结果                                │
│     │   └─ result done → 任务完成                                 │
│     │                                                            │
│     └─ COMPUTE_DONE ──→ 启动 result transfer                     │
│                                                                  │
│  3. 收集 Metrics + Viz 数据                                       │
└─────────────────────────────────────────────────────────────────┘
```

---

## 类关系图

```
┌──────────────────────────────────────────────────────────────────────────┐
│                              Simulator                                    │
│  (core/simulator.py)                                                     │
│                                                                          │
│  组合关系 (has-a):                                                        │
│  ┌────────────┐  ┌────────────┐  ┌────────────┐  ┌──────────────────┐  │
│  │ DESEngine  │  │ContactPlan │  │EnergyModel │  │WeightCacheManager│  │
│  └────────────┘  └────────────┘  └────────────┘  └──────────────────┘  │
│  ┌────────────┐  ┌────────────┐  ┌────────────┐  ┌──────────────────┐  │
│  │ Scheduler  │  │MetricsCol- │  │VizRecorder │  │List[Satellite]   │  │
│  │ (Protocol) │  │   lector   │  │            │  │                  │  │
│  └────────────┘  └────────────┘  └────────────┘  └──────────────────┘  │
│                                                                          │
│  管理的运行时状态:                                                         │
│  ┌────────────────────┐  ┌────────────────────┐                         │
│  │ Dict[str,Transfer] │  │ Dict[str,ComputeJob]│                        │
│  └────────────────────┘  └────────────────────┘                         │
└──────────────────────────────────────────────────────────────────────────┘

Scheduler 协议实现 (继承/实现关系):

         ┌──────────────────────┐
         │  Scheduler (Protocol)│  ← interface.py
         │  on_task_arrive()    │
         │  on_event()          │
         └─────────┬────────────┘
                   │ 实现
    ┌──────────────┼──────────────────────────────────┐
    │              │              │          │         │
    ▼              ▼              ▼          ▼         ▼
┌────────┐  ┌──────────┐  ┌─────────┐ ┌────────┐ ┌────────┐
│Nearest │  │ Shortest │  │CGR+EDF  │ │ Oracle │ │  TEG   │
│ First  │  │  Path    │  │         │ │(枚举)  │ │Schedul.│
└────────┘  └──────────┘  └─────────┘ └────────┘ └────────┘
    │              │              │                    │
    │         ┌────┴────┐    ┌───┴───┐           ┌───┴────┐
    │         │用ContactPlan │用ContactPlan       │用 TEG  │
    │         │做路由查询    │做多跳路由│           │做路径  │
    │         └─────────┘    └───────┘           │查询    │
    │                                            └────────┘
    ▼
┌────────────┐  ┌──────────────┐  ┌────────────────┐
│EnergyAware │  │LoadBalanced  │  │OracleMILP      │
│(电池过滤)   │  │(带宽感知)    │  │(CP-SAT 精确解) │
└────────────┘  └──────────────┘  └────────────────┘


数据结构依赖:

Satellite ──→ OrbitalElements
           ──→ Role (Enum)

TaskDAG ──→ SubTask (节点)
         ──→ DataDependency (边)
         ──→ TaskState (Enum)

ContactPlan ──→ ContactWindow
TimeExpandedGraph ──→ TEGNode + TEGEdge
                   ──→ ContactPlan (输入)

EnergyModel ──→ BatteryState (per node)
             ──→ PowerProfile (per node)
             ──→ PowerComponent / PowerMode (Enum)

WeightCacheManager ──→ WeightCache (per node)
                    ──→ ModelWeight + EvictionPolicy
```

---

## 调度器体系

所有调度器实现 `Scheduler` Protocol，核心接口：

```python
class Scheduler(Protocol):
    def on_task_arrive(self, task: TaskDAG, env: EnvSnapshot) -> Schedule: ...
    def on_event(self, event_type, payload, env) -> Optional[Schedule]: ...
```

| 调度器 | 文件 | 策略 | 复杂度 | 适用场景 |
|--------|------|------|--------|---------|
| **RandomScheduler** | heuristics.py | 随机选 compute 节点 | O(1) | 下界 baseline |
| **NearestFirstScheduler** | interface.py | 欧氏距离最近 | O(N) | 简单 baseline |
| **ShortestPathScheduler** | heuristics.py | 最小 t_transfer + t_compute + t_return | O(N·W) | 延迟优化 |
| **CGR_EDF_Scheduler** | heuristics.py | Contact Graph Dijkstra + 最早截止时间 | O(N·W·logW) | 多跳 + deadline |
| **TEGScheduler** | teg_scheduler.py | 时空扩展图 Dijkstra | O(\|V_TEG\|·log\|V_TEG\|) | 最优路由 |
| **EnergyAwareScheduler** | energy_aware.py | 电池过滤 + 距离 | O(N) | 能量受限场景 |
| **LoadBalancedScheduler** | load_balanced.py | 有效带宽评分 (避免争抢) | O(N·W) | 多任务并发 |
| **OracleScheduler** | oracle.py | 穷举最优 (小规模) | O(N^K) | 上界参考 |
| **OracleMILPScheduler** | oracle_milp.py | CP-SAT 精确解 | NP-hard | 精确最优 |

**EnvSnapshot** 是调度器的观察窗口，包含：
- `current_time_s` — 当前仿真时间
- `nodes: Dict[int, NodeSnapshot]` — 各节点状态（位置、电量、负载、缓存）
- `contact_plan` — 完整通信窗口表
- `active_windows` — 当前活跃链路

---

## 仿真运行流程

```python
# 典型使用模式
sim = Simulator(SimConfig(duration_s=1800, dt=1.0))
sim.set_satellites(satellites)        # 注入星座定义
sim.set_scheduler(TEGScheduler(...))  # 选择调度算法
sim.add_task(task_dag, arrive_time=0) # 注入任务

results = sim.run()
# results.success_rate, results.avg_makespan_s, ...
```

**初始化阶段** (`run()` 内部)：
1. `precompute_orbits()` → 传播所有卫星位置
2. `compute_contact_plan()` → 预计算通信窗口
3. `compute_eclipse_schedule()` → 预计算地影
4. 初始化 `EnergyModel`（每星注册功耗配置）
5. 将 LINK_UP/DOWN 事件批量注入 DES Engine
6. 将 TASK_ARRIVE 事件注入

**运行阶段** (DES 主循环)：
1. 弹出最早事件 → dispatch to handler
2. 每 dt 调用 step callbacks → 推进物理过程
3. 事件触发链式反应（transfer done → compute start → result transfer）
4. 直到仿真结束或所有任务完成

---

## 如何添加新调度器

1. 创建文件 `scheduler/my_scheduler.py`
2. 实现 `Scheduler` Protocol：

```python
from satlynk.scheduler.interface import Scheduler, Schedule, TaskAssignment, EnvSnapshot
from satlynk.task.dag import TaskDAG

class MyScheduler:
    def on_task_arrive(self, task: TaskDAG, env: EnvSnapshot) -> Schedule:
        # 你的调度逻辑
        assignments = []
        for subtask in task.topological_order():
            target_node = ...  # 选择执行节点
            assignments.append(TaskAssignment(subtask.id, target_node, env.current_time_s))
        return Schedule(assignments=assignments)

    def on_event(self, event_type, payload, env):
        return None  # 或返回新 Schedule 做动态重调度
```

3. 在 `benchmark.py` 的 `get_all_schedulers()` 中注册
4. 运行 `python -m satlynk.benchmark` 验证

**调度器可用信息**（通过 `EnvSnapshot`）：
- 各节点实时位置、电量、计算利用率
- 完整 Contact Plan（可查未来窗口）
- 当前活跃链路列表
- 各节点已缓存的模型权重列表

---

## 如何添加新场景

1. 创建 `scenarios/my_scenario.py`
2. 定义星座：

```python
from satlynk.orbital.constellation import Satellite, Role, OrbitalElements, generate_walker_delta
from satlynk.task.dag import TaskDAG, SubTask, DataDependency
from satlynk.core.simulator import Simulator, SimConfig

def create_constellation() -> list[Satellite]:
    # 用 generate_walker_delta() 或手动定义
    ...

def create_tasks() -> list[tuple[TaskDAG, float]]:
    # (task, arrive_time_s)
    ...

def run():
    sim = Simulator(SimConfig(duration_s=1800))
    sim.set_satellites(create_constellation())
    sim.set_scheduler(...)
    for task, t in create_tasks():
        sim.add_task(task, arrive_time=t)
    return sim.run()
```

3. 运行：`python -m satlynk.scenarios.my_scenario`

---

## 关键设计决策

| 决策 | 原因 |
|------|------|
| 自研 DES 引擎（非 SimPy） | 支持时间跳跃优化 + 固定步长回调混合模式 |
| 两体传播（非 SGP4） | 对 LEO 短期仿真足够精确，避免 TLE 依赖 |
| Contact Plan 预计算 | 避免逐步计算 LOS，O(N²·T) 预处理后 O(1) 查询 |
| Component-based 能耗 | 避免 delta 累积漂移，每步从组件集合重算 |
| TEG 静态图 | 将时变网络路由转化为标准图算法，可复用 Dijkstra |
| Scheduler 是 Protocol | 鸭子类型，无需继承，测试时易 mock |
| 多跳中继 store-and-forward | BFS 找路径 → 传输链式转发，无需端到端连通 |

---

## 外部依赖

- `numpy` — 向量化轨道计算和距离矩阵
- `ortools` (可选) — CP-SAT solver for OracleMILP
- 无其他重型依赖（不依赖 SimPy / sgp4 / Skyfield）

---

## 运行命令速查

```bash
# 安装
cd /workspace/satlynk && pip install .

# 运行单个场景
python -m satlynk.scenarios.case1_grb_bandwidth

# 运行 benchmark（所有调度器 × 所有场景）
python -m satlynk.benchmark

# 运行 static baseline 对比
python -m satlynk.baselines.compare_all

# 运行测试
pytest satlynk/tests/

# 生成可视化
python -m satlynk.viz.generate_tiange
```
