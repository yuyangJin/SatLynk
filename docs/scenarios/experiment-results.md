# Benchmark Case 实验结果 — SatLynk vs 现有工具

## 运行方式

```bash
cd /workspace/satlynk

# 单独运行各 case
python -m satlynk.scenarios.case1_grb_bandwidth
python -m satlynk.scenarios.case2_eclipse_energy

# 对比运行（SatLynk vs Static Baseline）
python -m satlynk.baselines.compare_all
```

## 对比对象说明

### SatLynk（本项目）
- 时变拓扑（Contact Plan 精确建模链路间歇性）
- 能耗耦合（地影/功耗/电池模式转换影响可用性）
- 带宽争抢（同一链路多传输公平分带宽）
- 可插拔调度器（Nearest-First / Load-Balanced / Energy-Aware / TEG / CGR+EDF）

### Static Baseline（`satlynk/baselines/static_topology.py`）
代表大量 Satellite MEC / Task Offloading 论文的典型假设：
- 链路**永远可达**（忽略 Contact Plan）
- 带宽**恒定且独占**（不建模争抢）
- **无能耗模型**（电池无限）
- 调度策略：Nearest-First

### Hypatia（ETH Zurich, IMC 2020）
LEO 星座网络仿真框架。能力：
- 基于 SGP4 的精确轨道传播
- 每时间步 Floyd-Warshall 最短路径计算
- ns-3 packet-level 仿真（TCP/UDP 延迟、throughput）

**为什么不能跑我们的 case**：
- 没有"计算任务"概念——只做 packet routing
- 没有调度决策——不做"选哪个计算节点"
- 没有能耗/带宽争抢建模
- 输入格式是"从 A 到 B 发 TCP 流"，不是"推理任务到达，选择执行节点"

**与 SatLynk 的互补关系**：Hypatia 验证"网络延迟"的准确性（packet-level），SatLynk 在此之上增加"任务调度+能耗"维度。

---

## Case 1: GRB 三角定位 — 带宽争抢

### 场景
- 3 det + 24 comp，2 Mbps det 侧链路瓶颈
- 同一颗探测星 10s 内连续发出 3 个 5MB 推理任务
- 所有调度器看到同一批可达计算星（3 颗）

### 结果

| 模拟器/调度器 | 成功率 | Avg Makespan | Max Makespan |
|--------------|--------|-------------|-------------|
| Static Baseline (Nearest) | 100% | 20.8s | 20.8s |
| SatLynk + Nearest-First | 100% | 61.8s | 62.2s |
| SatLynk + Load-Balanced | 100% | 21.8s | 22.2s |

### 关键发现
1. **Static Baseline 低估延迟 3.0×**：它看不到 3 个传输争抢同一条 2Mbps 链路
2. **Load-Balanced 调度器恢复最优**：分散到 3 颗不同计算星，消除争抢
3. 在 Hypatia 中：能观察到链路拥塞导致的排队延迟增长，但无法做出"换一颗计算星"的决策

### 论文论点
> 当多个任务同时到达（burst 事件），带宽争抢使端到端延迟成倍增长。  
> 只有联合考虑"路由"和"调度"的仿真器才能捕获这种耦合效应。

---

## Case 2: 地影穿越期磁星爆发 — 能耗约束

### 场景
- 3 det + 10 comp，部分计算星电量 26-30%（刚出地影）
- 5 次磁星爆发事件，45s 间隔
- LOW_POWER 阈值 30%（低于此拒绝新计算任务）

### 结果

| 模拟器/调度器 | 成功率 | 说明 |
|--------------|--------|------|
| Static Baseline | 100% | 无能耗模型，看不到电量问题 |
| Hypatia (理论) | 100% | 同上，无能耗维度 |
| SatLynk + Nearest-First | 0% | 最近节点电量不足→拒绝计算→全部失败 |
| SatLynk + Energy-Aware | 100% | 跳过低电量节点→选远但健康的星 |

### 关键发现
1. **Static/Hypatia 高估成功率 100pp**：完全无法建模能耗导致的任务失败
2. **Energy-Aware 调度完全恢复性能**：只需检查 `battery_pct > threshold`
3. 这不是 edge case——LEO 卫星 33% 时间在地影中，每 96 分钟一次

### 论文论点
> 能耗约束在操作层面直接 kill 任务。  
> 任何不建模电池状态的仿真器都会系统性高估系统可用性。

---

## Case 4: 多跳中继 — 引力波对应体定位（文档已完成，代码待扩展）

### 状态
场景文档和参数设计已完成。代码实现揭示了一个 **架构 gap**：
- SatLynk 当前传输层只做**直接点到点**传输
- TEG/CGR 调度器能发现多跳路径，但 Simulator 无法执行 store-and-forward
- 需要 ~300 行代码扩展 `_start_transfer` 支持逐跳转发

### 预期结果（一旦扩展完成）

| 调度器 | 成功率 | 说明 |
|--------|--------|------|
| Static Baseline | 100% (14s) | 假设直达链路存在 |
| Nearest-First (1-hop only) | 0% | 找不到直达路径 |
| TEG (multi-hop) | 100% (~220s) | 通过中继星 4 跳到达 |

**Static 的误差**：延迟低估 15×，且 100% 成功率是虚假的（实际上无直达链路）

---

## Case 5: 船舶检测 AoI（文档已完成，代码待实现）

### 预期对比

| 模拟器 | Peak AoI @ 20 sats | 达标(< 60s)所需密度 |
|--------|-------------------|-------------------|
| Static (论文假设) | ~15s | 400 sats |
| SatLynk (Contact Plan) | ~40-80s | ~800-1200 sats |
| Hypatia (packet-level) | ~20-25s (无调度) | — |

---

## 对比工具能力总结

| 维度 | Static Baseline | Hypatia | SatLynk |
|------|:-:|:-:|:-:|
| 轨道传播 | ✗ (单时刻快照) | ✓ (SGP4) | ✓ (Kepler) |
| 链路间歇性 | ✗ | ✓ | ✓ |
| Packet-level 延迟 | ✗ | ✓ (ns-3) | ✗ (抽象模型) |
| 计算任务调度 | ✗ | ✗ | ✓ |
| 带宽争抢 | ✗ | ✓ (ns-3 队列) | ✓ (公平分带宽) |
| 能耗模型 | ✗ | ✗ | ✓ |
| 权重位置 | ✗ | ✗ | ✓ |
| 仿真速度 (15星/10min) | <1ms | ~分钟 (ns-3) | ~1s |

**核心论点**：SatLynk 牺牲了 packet-level 精度（±几秒误差），换取了在任务调度+能耗维度的建模能力——这是其他工具完全缺失的维度，而正是这些维度决定了任务成败。
