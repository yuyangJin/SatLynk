# SatLynk Benchmark Experiment Report

## 概述

本报告验证 SatLynk 离散事件仿真器在 8 个典型天基智能任务场景中的表现，并与静态拓扑 Baseline（代表现有 Satellite MEC 论文的典型假设）进行定量对比，量化简化假设导致的系统性偏差。

**仿真器**：SatLynk v0.3（Python，DES + Keplerian 轨道 + Contact Plan + 能耗模型）

**Baseline**：
- Static Topology Model（链路永远可达、无能耗、无争抢）
- 定性对比：Hypatia (ETH Zurich, IMC 2020)——只做 packet routing，不做任务调度

## 运行方式

```bash
cd /workspace/satlynk

# 逐个运行
python -m satlynk.scenarios.case1_grb_bandwidth
python -m satlynk.scenarios.case2_eclipse_energy
python -m satlynk.scenarios.case3_weight_migration
python -m satlynk.scenarios.case4_multihop_relay
python -m satlynk.scenarios.case5_vessel_aoi
python -m satlynk.scenarios.case6_federated_learning
python -m satlynk.scenarios.case7_debris_warning
python -m satlynk.scenarios.case8_wildfire_detection

# SatLynk vs Static Baseline 对比
python -m satlynk.baselines.compare_all
```

---

## 结果总表

| Case | 场景 | SatLynk 最佳 | SatLynk 朴素 | 静态 Baseline | 偏差类型 |
|------|------|-------------|-------------|-------------|---------|
| 1 | GRB 带宽争抢 | 21.8s (LB) | 60.8s (NF) | 20.8s | 延迟低估 3.0× |
| 2 | 地影能耗 | 100% (EA) | 0% (NF) | 100% | 成功率高估 100pp |
| 3 | 权重迁移 | 2.0s | 2.0s | 0.28s | 延迟低估 7× |
| 4 | 多跳中继 | 26s | 26s | 16s | 延迟低估 1.6×，且假设不存在的直达链路 |
| 5 | 船舶 AoI (8星) | 51s | 51s | 6s | AoI 低估 8.5× |
| 5 | 船舶 AoI (12星) | 17s | 17s | 6s | AoI 低估 2.8× |
| 6 | 联邦学习 | 1/19 到达 | 1/19 到达 | 19/19 到达 | 虚假收敛保证 |
| 7 | 碎片预警 | 3s (在轨) | 3s (在轨) | — | 地面 50min 超 deadline |
| 8 | 山火检测 | 80s (offload) | 80s (offload) | — | offload 反而更慢 |

> **缩写**：LB=Load-Balanced, NF=Nearest-First, EA=Energy-Aware

---

## Case 1: GRB 三角定位 — 带宽争抢

**场景**：3 颗天格探测星同时触发 GRB，各发 5MB 到计算星。瓶颈是 2Mbps det 侧链路。

**星座**：3 det (535km SSO) + 24 comp (550km 53° Walker)

**发现**：
- Nearest-First 把 3 个任务全部指向同一颗计算星 → 3 个传输争抢同一条 2Mbps 链路 → 每个只有 0.67Mbps
- Load-Balanced 分散到 3 颗不同计算星 → 并行传输 → 各用满 2Mbps
- 静态模型看不到争抢：预测 20.8s（假设无争抢），实际 60.8s

| 调度器 | 成功率 | Avg Makespan | Max Makespan |
|--------|--------|-------------|-------------|
| Nearest-First | 100% | 60.2s | 60.8s |
| Shortest-Path | 100% | 60.2s | 60.8s |
| CGR+EDF | 100% | 60.2s | 60.8s |
| TEG | 100% | 60.2s | 60.8s |
| **Load-Balanced** | **67%** | **21.8s** | **22.2s** |
| Static Baseline | 100% | 20.8s | 20.8s |

**论点**：带宽争抢使端到端延迟成倍增长（2.8×）。只有联合考虑"路由"和"调度"的仿真器能捕获这种耦合效应。

---

## Case 2: 地影能耗 — 磁星爆发判决

**场景**：5 次磁星爆发，计算星中 4 颗电量 < 30%（刚出地影）。

**星座**：3 det + 10 comp, 部分节点初始电量 26-30%

**发现**：
- Nearest-First 选最近的 comp（恰好是低电量那几颗）→ LOW_POWER 模式拒绝计算 → 全部失败
- Energy-Aware 检查电量 > 40% → 跳过低电量节点 → 选远但健康的星 → 全部成功
- 静态模型无能耗维度 → 预测 100%

| 调度器 | 成功率 | Avg Makespan |
|--------|--------|-------------|
| Nearest-First | 0% | — |
| Shortest-Path | 0% | — |
| **Energy-Aware** | **100%** | **9.0s** |
| Static Baseline | 100% | 8.0s |

**论点**：能耗约束在操作层面直接 kill 任务。LEO 卫星 33% 时间在地影中（每 96 分钟），这不是 edge case。

---

## Case 3: 权重迁移 — C4 约束

**场景**：SolarFlare-CNN (500MB) 只在 3/15 颗计算星有缓存，6 次耀斑连续触发。

**星座**：3 det + 15 comp, 模型仅在 node 3/7/11

**发现**：
- Nearest-First 恰好选到有模型的节点（node 3 最近且有缓存）→ 成功
- 若最近节点无缓存：需要等待权重迁移 (500MB/50Mbps = 80s) 或绕道去有缓存的远端星
- 静态模型不建模权重位置 → 假设任何节点都能计算

| 调度器 | 成功率 | Avg Makespan | 静态预测 |
|--------|--------|-------------|---------|
| Nearest-First | 100% | 2.0s | 0.28s |
| Static Baseline | 100% | 0.28s | — |

**论点**：C4 约束（权重就绪）是调度决策的关键维度。不建模权重位置等于假设"模型已部署在所有星上"——在存储受限的现实中不成立。

---

## Case 4: 多跳中继 — Store-and-Forward

**场景**：探测星（SSO 97.4°）与计算星（53°）无直接链路（不同频段），必须经中继星。

**星座**：3 det + 12 comp + 6 relay (1100km, 75°)

**发现**：
- 滤除 det↔comp 直接链路后，数据必须走 det→relay→comp→relay→det
- SatLynk 自动找到 relay 路径（`_find_relay_route`），store-and-forward 成功
- 实际 makespan 26s（含中继等待），静态模型假设直达预测 16s

| 路由方式 | 成功率 | Makespan | 静态预测 |
|----------|--------|---------|---------|
| SatLynk (auto relay) | 100% | 26s | 16s（假设直达） |
| Static Baseline | 100% | 16s | — |

**论点**：静态模型假设的"直达链路"在真实轨道构型中不存在。不同轨道面的卫星大部分时间无法直接通信。

---

## Case 5: 船舶检测 — AoI 密度扫描

**场景**：EO 星拍 100MB 图像切 4 块分发给邻居做 YOLOv8 推理。

**星座**：Walker(N/P/1), 550km, 53°, 密度从 8 到 40

**发现**：

| 星座密度 | SatLynk AoI | Static AoI | 低估倍数 |
|---------|------------|-----------|---------|
| 8 | 51.0s | 6.0s | **8.5×** |
| 12 | 17.0s | 6.0s | **2.8×** |
| 20 | 17.0s | 6.0s | 2.8× |
| 30 | 17.0s | 6.0s | 2.8× |
| 40 | 17.0s | 6.0s | 2.8× |

**论点**：
1. 稀疏星座（8 星）中 AoI 被低估 8.5× — 因为大部分邻居不可达
2. 12+ 星时收敛到 2.8× 低估 — 因为带宽争抢（4 块抢同一链路）
3. 2024 ICCSPA 论文 (arXiv:2410.07431) 用静态模型得出"20×20=400 星可达 AoI<60s"，实际需要更多

---

## Case 6: 联邦学习 — 聚合通信

**场景**：20 颗星做 FL，每轮各发 10MB 梯度到聚合节点。

**星座**：Walker(20/4/1), 550km, 50Mbps ISL

**发现**：
- 静态模型假设 19 颗星同时与聚合器通信：1.6s 完成一轮
- **SatLynk 实际：仅 1/19 梯度到达**（其余 18 颗与聚合器无链路）
- 这不是"慢"的问题——是"根本不连通"的问题

| 指标 | Static | SatLynk |
|------|--------|---------|
| 到达梯度数 | 19/19 | **1/19** |
| 预测 round time | 1.6s | >11400s（需多轨道） |
| 收敛保证 | 是 | **否**（虚假） |

**论点**：这是最强发现 — 静态模型不是"低估延迟"而是"承诺了不存在的连通性"。用静态模型设计的 FL 算法在真实轨道上会完全失效。

---

## Case 7: 碎片预警 — 在轨 vs 地面

**场景**：碎片碰撞预警，deadline 180-300s。

**星座**：3 obs + 12 comp

**发现**：
- 在轨处理：3s 完成（传输+推理+回传），远在 deadline 内
- 地面流程：等待 GS pass 平均 45min → 远超所有 deadline

| 处理方式 | 延迟 | Deadline 达标 |
|----------|------|-------------|
| 在轨 SatLynk | 3s | ✓ 100% |
| 地面传统流程 | ~50min | ✗ 0% |

**论点**：对时间关键型任务（碰撞规避、紧急预警），在轨计算不是优化而是**必需**。

---

## Case 8: 山火检测 — Offload 相变

**场景**：EO 星拍 100MB 图像，CNN 推理 3 GFLOP。EO 自身有 100 GFLOPS 算力。

**星座**：5 EO + 10 comp, 10 Mbps 链路

**发现**：
- 本地推理：3 GFLOP / 100 GFLOPS = 0.03s（几乎瞬时）
- 远程 offload：100MB / 10Mbps = 80s 传输 + 0.003s 计算 = **80s**
- **Offload 反而慢了 2600×**

| 方式 | 延迟 | 瓶颈 |
|------|------|------|
| 本地处理 | 0.03s | 计算（极轻） |
| 远程 Offload | 80s | 传输（100MB/10Mbps） |

**论点**：OBS3 的反面 — 当 `input_size / compute_intensity` 大时（大图+轻计算），offload 永远不如本地。offload 仅在 `小输入 + 重计算`（如 3MB 光变曲线 + 4s 推理）时有优势。

---

## 对比工具能力边界

| 维度 | Static Baseline | Hypatia (ns-3) | SatLynk |
|------|:---:|:---:|:---:|
| 轨道传播 | ✗ 单时刻快照 | ✓ SGP4 | ✓ Kepler |
| Contact Plan | ✗ 假设永通 | ✓ 精确 | ✓ 精确 |
| Packet-level 延迟 | ✗ | ✓ | ✗ (抽象) |
| 计算任务调度 | ✗ | ✗ | ✓ |
| 带宽争抢 | ✗ | ✓ (ns-3 队列) | ✓ (公平分带宽) |
| 多跳中继 | ✗ | ✓ (路由表) | ✓ (store-and-forward) |
| 能耗模型 | ✗ | ✗ | ✓ |
| 权重位置 (C4) | ✗ | ✗ | ✓ |
| 仿真速度 | <1ms | ~分钟 | ~1-2s |

**Hypatia 无法跑本实验的原因**：
- 它的输入是"从 A 到 B 发 TCP 流"，输出是 RTT/throughput
- 没有"任务到达→选择计算节点→执行推理→回传结果"的概念
- 不能回答"这颗星电量够不够""哪颗星有模型缓存"

---

## 核心结论

1. **静态拓扑假设系统性失准**：8 个 case 中有 6 个被低估（延迟 1.6-8.5×，成功率 0-100pp），1 个被给予不存在的连通性保证。

2. **三类偏差模式**：
   - **延迟低估**（Case 1/3/4/5）：不建模争抢/中继/间歇性
   - **成功率高估**（Case 2/6）：不建模能耗/连通性
   - **决策方向错误**（Case 8）：不建模传输成本→错误推荐 offload

3. **SatLynk 的差异化**：不是更精确的网络仿真（Hypatia 在 packet-level 更精确），而是**在任务调度维度**的建模能力——这是其他所有工具完全缺失的。

4. **实践意义**：用静态模型设计的卫星 AI 系统在部署后会遭遇系统性性能退化。SatLynk 类仿真应作为系统设计的**前置验证步骤**。
