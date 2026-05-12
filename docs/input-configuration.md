# SatLynk 模拟器输入配置文档

SatLynk 模拟器接收 4 类输入，从仿真环境到调度策略逐层定义。

---

## 目录

1. [SimConfig — 仿真全局参数](#1-simconfig--仿真全局参数)
2. [Satellite 列表 — 星座配置](#2-satellite-列表--星座配置)
3. [TaskDAG 列表 — 任务定义](#3-taskdag-列表--任务定义)
4. [Scheduler — 调度策略](#4-scheduler--调度策略)
5. [隐式派生输入](#5-隐式派生输入)
6. [完整示例](#6-完整示例)

---

## 1. SimConfig — 仿真全局参数

控制仿真运行的全局设置。

```python
from satlynk.core.simulator import SimConfig

config = SimConfig(
    duration_s=1800.0,          # 仿真总时长（秒）
    dt=1.0,                     # 时间步长（秒）
    max_skip_s=60.0,            # 空闲时最大跳跃（秒）
    data_rate_bps=50e6,         # 链路数据率（bit/s）
    compute_flops_default=8e9,  # 默认计算节点峰值 FLOPS
    idle_power_w=2.0,           # 基础待机功耗（W）
    compute_power_w=15.0,       # 计算时额外功耗（W）
    comm_power_w=5.0,           # 通信时额外功耗（W）
)
```

### 参数说明

| 参数 | 类型 | 默认值 | 含义 |
|------|------|--------|------|
| `duration_s` | float | 60.0 | 仿真总时长。典型值：验证 60-600s，完整实验 1800-7200s |
| `dt` | float | 1.0 | 离散时间步长，驱动轨道传播、传输推进、能耗计算。减小可提高精度但增加计算量 |
| `max_skip_s` | float | 60.0 | DES 引擎空闲时最大时间跳跃，加速无事件时段 |
| `data_rate_bps` | float | 10e6 | 星间链路固定数据率。同一链路上多个传输公平分享该带宽 |
| `compute_flops_default` | float | 1e9 | 若卫星未指定 `compute_flops`，使用此默认值 |
| `idle_power_w` | float | 2.0 | 基础平台功耗（OBC + ADCS + thermal），始终消耗 |
| `compute_power_w` | float | 15.0 | 推理计算时叠加的额外功耗 |
| `comm_power_w` | float | 5.0 | 通信发射时的额外功耗（接收端为 0.4x） |

### 典型场景配置

| 场景 | duration_s | dt | data_rate_bps |
|------|------------|-----|---------------|
| Toy case 验证 | 60 | 1.0 | 10 Mbps |
| 15 星 30min | 1800 | 1.0 | 50 Mbps |
| 2800 星 2h | 7200 | 5.0 | 50 Mbps |
| 高精度能耗分析 | 600 | 0.1 | 50 Mbps |

---

## 2. Satellite 列表 — 星座配置

每颗卫星由**轨道参数**和**硬件参数**两部分定义。

### 2.1 轨道参数 (OrbitalElements)

```python
from satlynk.orbital.constellation import OrbitalElements

elements = OrbitalElements(
    semi_major_axis_km=6921.0,    # R_E(6371) + 轨道高度(550)
    inclination_deg=53.0,          # 轨道倾角
    raan_deg=0.0,                  # 升交点赤经 Ω
    true_anomaly_deg=0.0,          # 初始真近点角 ν₀
    eccentricity=0.0,              # 离心率（≈0 近圆轨道）
)
```

| 参数 | 单位 | 含义 | 取值范围 |
|------|------|------|----------|
| `semi_major_axis_km` | km | 轨道半长轴 a | LEO: 6571-7371 (200-1000km 高度) |
| `inclination_deg` | ° | 轨道面与赤道面夹角 | 0°(赤道) ~ 180°(逆行) |
| `raan_deg` | ° | 升交点赤经，区分同倾角不同轨道面 | 0° ~ 360° |
| `true_anomaly_deg` | ° | 初始位置的真近点角 | 0° ~ 360° |
| `eccentricity` | - | 轨道离心率 | 0(圆) ~ 1(抛物线)，LEO 通常 ≈ 0 |

**物理意义**：
- `semi_major_axis_km` 决定轨道周期（550km → 95.6min，500km → 94.6min）
- `inclination_deg` 决定覆盖纬度（53° 覆盖 ±53°，97.6° 为太阳同步轨道）
- `raan_deg` 区分不同轨道面，Walker 星座中等间距分布
- `true_anomaly_deg` 决定同一轨道面内的卫星初始相位

### 2.2 卫星对象 (Satellite)

```python
from satlynk.orbital.constellation import Satellite, Role

sat = Satellite(
    id="COMP-001",
    role=Role.COMPUTE,
    elements=elements,
    compute_flops=100e12,         # 100 TOPS
    storage_bytes=int(64e9),      # 64 GB
    max_comm_range_km=5000.0,     # 星间链路最大距离
    power_solar_w=80.0,           # 太阳能板峰值功率
    battery_capacity_wh=500.0,    # 电池容量
)
```

| 参数 | 单位 | 含义 | 典型值 |
|------|------|------|--------|
| `id` | str | 卫星唯一标识 | "COMP-001"、"GRID-10B" |
| `role` | Role | 卫星角色 | 见下表 |
| `compute_flops` | FLOPS | 峰值算力 | 探测器 0，算力星 8e9-100e12 |
| `storage_bytes` | bytes | 总存储容量 | 8GB-256GB |
| `max_comm_range_km` | km | 最大通信距离 | RF: 2000-3000, 激光ISL: 5000-8000 |
| `power_solar_w` | W | 光照时太阳能板输出 | 小星 10-20, 大星 50-150 |
| `battery_capacity_wh` | Wh | 电池总容量 | 小星 20-60, 大星 100-500 |

### 2.3 卫星角色 (Role)

| 角色 | 含义 | 典型配置 |
|------|------|----------|
| `COMPUTE` | 纯算力节点 | 高算力、高能耗、中等存储 |
| `DETECTOR` | 探测/传感节点 | 无算力、低功耗、产生任务 |
| `RELAY` | 中继节点 | 无算力、长通信距离 |
| `HYBRID` | 探测+计算混合 | 中等算力、有载荷 |
| `GROUND` | 地面站 | 无轨道、大带宽、无限能量 |

### 2.4 Walker-Delta 快捷生成

对于规则星座，使用 `generate_walker_delta()` 批量生成：

```python
from satlynk.orbital.constellation import generate_walker_delta, Role

compute_sats = generate_walker_delta(
    total_sats=12,           # 总卫星数
    num_planes=3,            # 轨道面数
    phase_factor=1,          # 面间相位因子 F
    altitude_km=550,         # 轨道高度
    inclination_deg=53.0,    # 倾角
    role=Role.COMPUTE,       # 角色
    prefix='COMP',           # ID 前缀
    # 以下为 Satellite 硬件参数
    compute_flops=8e9,
    power_solar_w=50,
    battery_capacity_wh=200,
    max_comm_range_km=5000,
)
```

**Walker-Delta 参数解释**：
- `Walker(N/P/F, h, i)` = N 颗星、P 个轨道面、相位因子 F
- 每面 N/P 颗星，面内等间距 360°/(N/P)
- 轨道面 RAAN 等间距 360°/P
- 面间相位偏移 F × 360°/N

**现实参照**：

| 星座 | Walker 配置 | 轨道 |
|------|-------------|------|
| 三体计算星座（首批） | 12/4/1 | 550km, 53° |
| 三体计算星座（全量） | 2800/40/1 | 550km, 53° |
| 天格探测网 | 13/1/0 | 535km, 97.6° SSO |
| Starlink shell-1 | 1584/72/1 | 550km, 53° |

### 2.5 逐星定义（非规则星座）

对于不规则分布的卫星，逐一构造：

```python
sats = [
    Satellite(
        id="DET-A", role=Role.DETECTOR,
        elements=OrbitalElements(
            semi_major_axis_km=6371+535, inclination_deg=97.6,
            raan_deg=0, true_anomaly_deg=0,
        ),
        compute_flops=0, power_solar_w=10,
        battery_capacity_wh=40, max_comm_range_km=3000,
    ),
    Satellite(
        id="COMP-X", role=Role.COMPUTE,
        elements=OrbitalElements(
            semi_major_axis_km=6371+550, inclination_deg=53.0,
            raan_deg=45, true_anomaly_deg=120,
        ),
        compute_flops=100e12, power_solar_w=80,
        battery_capacity_wh=500, max_comm_range_km=5000,
    ),
]
```

---

## 3. TaskDAG 列表 — 任务定义

每个任务是一个有向无环图（DAG），描述计算需求及数据流。

### 3.1 单子任务（最常见场景）

```python
from satlynk.task.dag import TaskDAG, SubTask

task = TaskDAG(
    id='grb_001',
    source_node=0,             # 产生任务的卫星索引
    arrival_time_s=120.0,      # 任务到达时刻
    subtasks=[
        SubTask(
            id='infer_grb_001',
            compute_flops=16e9,           # 计算量（FLOP）
            required_model='gamma_2b',    # 所需模型（可选）
            model_size_bytes=int(2e9),    # 模型大小（可选）
            output_size_bytes=1_000_000,  # 输出数据大小
        ),
    ],
    dependencies=[],           # 无依赖（单任务）
    global_deadline_s=300.0,   # 最大端到端延迟
    result_destination=0,      # 结果回传目标（-1=源节点）
    result_size_bytes=1_000_000,
)
task.input_size_bytes = 5_000_000  # 输入数据大小
```

### 3.2 多子任务 DAG

```python
from satlynk.task.dag import TaskDAG, SubTask, DataDependency

task = TaskDAG(
    id='pipeline_001',
    source_node=0,
    arrival_time_s=60.0,
    subtasks=[
        SubTask(id='preprocess', compute_flops=2e9, output_size_bytes=2_000_000),
        SubTask(id='inference', compute_flops=50e9, required_model='yolo_v8',
                model_size_bytes=int(500e6), output_size_bytes=500_000),
        SubTask(id='postprocess', compute_flops=1e9, output_size_bytes=100_000),
    ],
    dependencies=[
        DataDependency(src_task='preprocess', dst_task='inference', 
                       data_size_bytes=2_000_000),
        DataDependency(src_task='inference', dst_task='postprocess', 
                       data_size_bytes=500_000),
    ],
    global_deadline_s=600.0,
    result_destination=0,
    result_size_bytes=100_000,
)
task.input_size_bytes = 10_000_000
```

### 3.3 参数详解

#### TaskDAG 级

| 参数 | 类型 | 含义 |
|------|------|------|
| `id` | str | 任务唯一标识 |
| `source_node` | int | 产生任务的卫星索引（如探测器发现 GRB） |
| `arrival_time_s` | float | 任务在仿真中的到达时刻（秒） |
| `subtasks` | List[SubTask] | 子任务列表 |
| `dependencies` | List[DataDependency] | 子任务间数据依赖 |
| `global_deadline_s` | float \| None | 允许的最大端到端时延。超时则任务判定失败 |
| `result_destination` | int | 结果回传目标节点。-1 表示返回 source_node |
| `result_size_bytes` | int | 最终结果数据大小（需回传） |
| `input_size_bytes` | int | 输入数据大小（需从源传到计算节点）。需在构造后单独赋值 |

#### SubTask 级

| 参数 | 类型 | 含义 |
|------|------|------|
| `id` | str | 子任务唯一标识 |
| `compute_flops` | float | 计算量 w_v（FLOP）。实际耗时 = compute_flops / node.compute_flops |
| `required_model` | str \| None | 所需模型权重名称。触发 C4 约束：执行前必须在目标节点缓存该模型 |
| `model_size_bytes` | int | 模型权重大小。若目标节点未缓存，需先传输 |
| `output_size_bytes` | int | 子任务输出大小（供 DAG 下游消费） |
| `deadline_s` | float \| None | 子任务级 deadline（可选，一般用 global_deadline） |

#### DataDependency

| 参数 | 类型 | 含义 |
|------|------|------|
| `src_task` | str | 生产者子任务 ID |
| `dst_task` | str | 消费者子任务 ID |
| `data_size_bytes` | int | 依赖数据大小。若两个子任务在不同节点，需通过链路传输 |

### 3.4 典型计算量参考

| 任务类型 | compute_flops | input_size | result_size |
|----------|---------------|------------|-------------|
| GRB 分类（2B INT8） | 16 GFLOP | 5 MB | 1 MB |
| 目标检测（YOLOv8） | 50 GFLOP | 10 MB | 0.5 MB |
| 图像分割 | 100 GFLOP | 20 MB | 5 MB |
| 大模型推理（7B FP16） | 200 GFLOP | 1 MB | 0.1 MB |
| 简单触发判定 | 1 GFLOP | 0.1 MB | 0.01 MB |

### 3.5 任务生成模式

在 benchmark 中，任务通常按以下模式生成：

```python
import numpy as np

rng = np.random.default_rng(seed=42)
tasks = []

for i in range(num_tasks):
    # Poisson 到达
    t_arrive = rng.exponential(scale=mean_interval)
    
    # 随机选择探测器
    det_idx = rng.integers(0, num_detectors)
    
    task = TaskDAG(
        id=f'task_{i:03d}',
        source_node=det_idx,
        arrival_time_s=t_arrive,
        subtasks=[SubTask(id=f'infer_{i}', compute_flops=25e9, 
                          output_size_bytes=500_000)],
        dependencies=[],
        global_deadline_s=300.0,
        result_destination=det_idx,
        result_size_bytes=500_000,
    )
    task.input_size_bytes = 3_000_000
    tasks.append(task)
```

---

## 4. Scheduler — 调度策略

调度器是模拟器的**被测对象**，通过 Protocol 接口与仿真环境交互。

### 4.1 接口定义

```python
from satlynk.scheduler.interface import (
    Scheduler, Schedule, TaskAssignment, EnvSnapshot, NodeSnapshot,
)

class MyScheduler:
    def on_task_arrive(self, task: TaskDAG, env: EnvSnapshot) -> Schedule:
        """新任务到达时调用。必须返回调度决策。"""
        ...
    
    def on_event(self, event_type: str, payload: dict, 
                 env: EnvSnapshot) -> Optional[Schedule]:
        """环境变化时调用（链路切换等）。返回 None 表示不调整。"""
        ...
```

### 4.2 调度器输入：EnvSnapshot

调度器通过 `EnvSnapshot` 观察当前环境状态：

```python
@dataclass
class EnvSnapshot:
    current_time_s: float                # 当前仿真时刻
    nodes: Dict[int, NodeSnapshot]       # 所有卫星状态
    contact_plan: ContactPlan            # 完整通信窗口计划
    active_windows: List[ContactWindow]  # 当前活跃链路
```

每个节点的观测：

```python
@dataclass
class NodeSnapshot:
    node_id: int                 # 卫星索引
    role: str                    # "compute" / "detector" / ...
    position: np.ndarray         # (3,) ECI 位置向量 (km)
    compute_flops: float         # 峰值算力
    compute_utilization: float   # 当前利用率 [0,1]
    battery_pct: float           # 电池百分比 [0,100]
    weight_cache: List[str]      # 已缓存的模型名称
```

### 4.3 调度器输出：Schedule

```python
@dataclass
class TaskAssignment:
    subtask_id: str           # 子任务 ID
    execute_on: int           # 分配到的节点索引
    scheduled_start_s: float  # 建议开始时间（不强制）

@dataclass
class Schedule:
    assignments: List[TaskAssignment]
```

### 4.4 内置调度器

| 调度器 | 类名 | 策略 | 适用场景 |
|--------|------|------|----------|
| Random | `RandomScheduler(seed)` | 随机分配到任意算力节点 | 下界参照 |
| Nearest-First | `NearestFirstScheduler()` | 分配到距离最近的算力节点 | 简单 baseline |
| Shortest-Path | `ShortestPathScheduler(data_rate_bps)` | 最短传输时间路径 | 考虑时间窗 |
| CGR+EDF | `CGR_EDF_Scheduler(data_rate_bps, max_hops)` | Contact Graph Routing + 最早截止优先 | 多跳中继 |
| Oracle | `OracleScheduler(contact_plan, satellites, ...)` | 穷举离线最优 | 上界参照 |

### 4.5 使用方式

```python
from satlynk.scheduler.heuristics import ShortestPathScheduler

sim = Simulator(config)
sim.set_satellites(all_sats)
sim.precompute_orbits()
sim.set_scheduler(ShortestPathScheduler(data_rate_bps=50e6))
```

Oracle 需要预计算：

```python
from satlynk.scheduler.oracle import OracleScheduler

oracle = OracleScheduler(
    contact_plan=sim.contact_plan,
    satellites=all_sats,
    data_rate_bps=50e6,
    time_horizon_s=1800.0,
)
oracle.precompute_all(tasks)
sim.set_scheduler(oracle)
```

---

## 5. 隐式派生输入

以下内容由模拟器从上述输入自动计算，用户无需手动提供：

### 5.1 Contact Plan（通信窗口计划）

由 `sim.precompute_orbits()` 自动生成。

**计算逻辑**：
1. 遍历所有卫星对 (i, j)
2. 逐时间步计算距离 d_ij(t) 和视线可达性（地球遮挡检测）
3. 当 d_ij(t) ≤ min(range_i, range_j) 且无地球遮挡时，链路可用
4. 连续可用时段合并为一个 `ContactWindow`

**ContactWindow 属性**：

| 属性 | 含义 |
|------|------|
| `src, dst` | 两端节点索引 |
| `start_s, end_s` | 窗口起止时刻 |
| `avg_rate_bps` | 窗口内平均数据率 |
| `min_distance_km` | 窗口内最近距离 |
| `duration_s` | 窗口持续时间 |
| `capacity_bits` | 窗口总传输容量 |

也可手动指定候选对以减少计算量（大规模星座）：

```python
from satlynk.network.contact_plan import compute_contact_plan

# 只计算探测器↔算力星的链路（跳过算力星之间）
pairs = [(i, j) for i in det_indices for j in comp_indices]
plan = compute_contact_plan(satellites, times, positions,
                            candidate_pairs=pairs, data_rate_bps=50e6)
sim.set_contact_plan(plan)
```

### 5.2 Eclipse Schedule（地影时刻表）

由 `sim.precompute_orbits()` 自动生成。

**计算逻辑**：柱形地球阴影模型。当卫星处于地球阴影锥内时：
- 太阳能板输出归零
- 加热器自动开启（防止设备过冷）
- 电池纯放电

**典型值**：LEO 550km 轨道约 33% 时间在地影中（~31.5 min/圈）。

### 5.3 PowerProfile（功耗配置）

由 `sim.set_satellites()` 根据卫星角色自动组装：

| 组件 | COMPUTE 节点 | DETECTOR 节点 |
|------|-------------|---------------|
| BASE (OBC+ADCS) | idle_power_w | idle_power_w × 0.5 |
| DETECTOR 载荷 | 0 W | 3 W (常开) |
| COMM_TX 发射 | comm_power_w | comm_power_w |
| COMM_RX 接收 | comm_power_w × 0.4 | comm_power_w × 0.4 |
| COMPUTE 计算 | compute_power_w | compute_power_w |
| HEATER 加热器 | 1.0 W (地影中) | 0.5 W (地影中) |

---

## 6. 完整示例

### 6.1 最小可运行示例

```python
from satlynk.core.simulator import Simulator, SimConfig
from satlynk.orbital.constellation import generate_walker_delta, Role
from satlynk.task.dag import TaskDAG, SubTask
from satlynk.scheduler.heuristics import ShortestPathScheduler

# 1. 配置
config = SimConfig(duration_s=600.0, dt=1.0, data_rate_bps=50e6)

# 2. 星座
detectors = generate_walker_delta(
    total_sats=1, num_planes=1, phase_factor=0,
    altitude_km=535, inclination_deg=97.6,
    role=Role.DETECTOR, prefix='DET',
    compute_flops=0, power_solar_w=10,
    battery_capacity_wh=40, max_comm_range_km=3000,
)
computers = generate_walker_delta(
    total_sats=4, num_planes=2, phase_factor=1,
    altitude_km=550, inclination_deg=53.0,
    role=Role.COMPUTE, prefix='COMP',
    compute_flops=8e9, power_solar_w=50,
    battery_capacity_wh=200, max_comm_range_km=5000,
)
all_sats = detectors + computers

# 3. 任务
task = TaskDAG(
    id='task_001', source_node=0, arrival_time_s=30.0,
    subtasks=[SubTask(id='infer_1', compute_flops=25e9, output_size_bytes=500_000)],
    dependencies=[], global_deadline_s=300.0,
    result_destination=0, result_size_bytes=500_000,
)
task.input_size_bytes = 3_000_000

# 4. 组装运行
sim = Simulator(config)
sim.set_satellites(all_sats)
sim.precompute_orbits()
sim.set_scheduler(ShortestPathScheduler(data_rate_bps=50e6))
sim.add_task(task)

metrics = sim.run()
print(f"Success: {metrics.success_rate*100:.0f}%")
print(f"Makespan: {metrics.avg_makespan_s:.1f}s")
```

### 6.2 Benchmark 一键对比

```python
from satlynk.benchmark import make_scenario_15sat, run_benchmark, print_comparison_table

scenario = make_scenario_15sat()
result = run_benchmark(scenario, include_oracle=True)
print_comparison_table(result)
```

或命令行直接运行：

```bash
python -m satlynk.benchmark
```

### 6.3 自定义场景模板

```python
def make_my_scenario():
    config = SimConfig(duration_s=3600.0, dt=1.0, data_rate_bps=100e6)
    
    # 混合星座：探测 + 算力 + 中继
    detectors = generate_walker_delta(
        total_sats=6, num_planes=2, phase_factor=0,
        altitude_km=500, inclination_deg=97.6,
        role=Role.DETECTOR, prefix='DET',
        compute_flops=0, power_solar_w=15,
        battery_capacity_wh=60, max_comm_range_km=3000,
    )
    computers = generate_walker_delta(
        total_sats=24, num_planes=4, phase_factor=1,
        altitude_km=550, inclination_deg=53.0,
        role=Role.COMPUTE, prefix='COMP',
        compute_flops=50e12, power_solar_w=100,
        battery_capacity_wh=400, max_comm_range_km=5000,
    )
    relays = generate_walker_delta(
        total_sats=4, num_planes=2, phase_factor=1,
        altitude_km=1000, inclination_deg=60.0,
        role=Role.RELAY, prefix='RELAY',
        compute_flops=0, power_solar_w=30,
        battery_capacity_wh=150, max_comm_range_km=8000,
    )
    
    all_sats = detectors + computers + relays
    
    # Poisson 到达的 GRB 任务
    rng = np.random.default_rng(42)
    tasks = []
    t = 60.0
    for i in range(20):
        t += rng.exponential(150.0)
        det = rng.integers(0, len(detectors))
        task = TaskDAG(
            id=f'grb_{i:03d}', source_node=det, arrival_time_s=t,
            subtasks=[SubTask(id=f'infer_{i}', compute_flops=16e9,
                              output_size_bytes=1_000_000)],
            dependencies=[], global_deadline_s=300.0,
            result_destination=det, result_size_bytes=1_000_000,
        )
        task.input_size_bytes = 5_000_000
        tasks.append(task)
    
    return {'name': 'custom_34sat', 'config': config, 
            'satellites': all_sats, 'tasks': tasks}
```

---

## 附录：约束与输入的对应关系

文档形式化中的 6 条约束如何由输入参数控制：

| 约束 | 含义 | 对应输入 |
|------|------|----------|
| C1 执行唯一 | 每个子任务只在一个节点执行 | 由 Scheduler 保证（返回唯一 assignment） |
| C2 链路门控 | 传输只在窗口内进行 | `max_comm_range_km` → ContactPlan → L_ij(t) |
| C3 依赖就绪 | 计算在输入到达后才开始 | `input_size_bytes` + `data_rate_bps` + C2 |
| C4 权重前置 | 模型必须先到位 | `required_model` + `model_size_bytes` |
| C5 能量动力学 | 电池不耗尽 | `power_solar_w` + `battery_capacity_wh` + 各功耗参数 |
| C6 热/存储 | 存储和散热约束 | `storage_bytes`（存储），地影模型（热） |
