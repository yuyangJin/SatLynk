# Case 4: 跨轨道面多跳中继 — 引力波对应体紧急定位

## 科学背景

LIGO/Virgo 探测到双中子星并合引力波后，~1 分钟内发布初步天区概率图。
天格星座需要**立即**调整观测模式：判断是否探测到伴随的短 GRB，并做联合定位。
这是 GW170817 发现过程的在轨自动化版本。

**为什么需要多跳**：天格探测星在 535 km SSO（97.4° 倾角），计算星在
550 km / 53° Walker。两组轨道面交角 ~44°，在大部分时刻没有直接
视距链路（距离 > 通信距离限制）。数据必须经过中继星"桥接"。

**文献锚点**：
- GW170817: LIGO alert → Fermi GBM 独立触发 → 1.7s 延迟确认关联
- IPN (InterPlanetary Network): 多星三角定位延迟数小时（地面流程）
- 在轨闭环可将确认时间从小时级压缩到 ~分钟级

## 任务流

```
LIGO alert 时间窗内，TG-01 探测到候选短 GRB
    ↓
TG-01 ──3MB──→ R-02 (中继星)     [window: 0-55s]
                   ↓
              R-02 ──3MB──→ C-05 (计算星)   [window: 40-130s]
                              ↓
                         推理 8s (GW-EM Matcher)
                              ↓
              C-05 ──100KB──→ R-03 (另一颗中继星) [window: 140-200s]
                                  ↓
                             R-03 ──100KB──→ TG-01  [window: 180-240s]
                                                ↓
                                        切换全星座观测模式
```

## 观测数据

| 数据产物 | 规格 | 大小 |
|---------|------|------|
| 短 GRB 光变曲线 (高时间分辨率) | 100μs bin × 2s × 4 能段 | ~1.5 MB |
| 精确时标 (μs 级绝对时间) | GPS + 星载原子钟 | ~0.1 MB |
| 背景能谱 + 温度校准 | — | ~0.4 MB |
| LIGO alert 信息 (上注) | 天区概率图 + 参数 | ~1 MB |
| **合计** | — | **~3 MB** |

## AI 模型

| 属性 | 值 |
|------|---|
| 模型 | GW-EM Matcher (时空关联判断网络) |
| 参数量 | 1B |
| 权重大小 | 2 GB (INT4) |
| 输入 | GRB 数据 + LIGO 天区图 (~3 MB) |
| 推理 FLOPs | ~4×10⁹ |
| 在 1 TFLOPS 芯片上耗时 | ~8 s |
| 输出 | 关联置信度 + 联合定位更新 + 观测模式指令 (~100 KB) |

## 星座拓扑（精心设计使直接链路不存在）

```python
# 探测星: 535 km SSO (97.4°)
# 计算星: 550 km, 53° Walker(12/3/1)
# 中继星: 1100 km, 65° Walker(6/3/1) — 更高轨道，更大覆盖

# 通信距离限制:
det_max_range = 2000   # km (天格星小天线)
comp_max_range = 5000  # km (计算星激光)
relay_max_range = 4000 # km (中继星)

# 关键: SSO 与 53° Walker 的轨道面交角使得
# det↔comp 距离在大部分时刻 > 2000 km → 无直接链路
# 必须经过 65° 中继星桥接
```

## 时间窗口设计

| 链路 | 窗口 | 持续时间 | 带宽 |
|------|------|---------|------|
| TG-01 ↔ R-02 | [0, 55s] | 55s | 2 Mbps (S-band) |
| R-02 ↔ C-05 | [40, 130s] | 90s | 50 Mbps (laser) |
| C-05 ↔ R-03 | [140, 200s] | 60s | 50 Mbps |
| R-03 ↔ TG-01 | [180, 240s] | 60s | 2 Mbps |

**Overlap**: TG↔R-02 和 R-02↔C-05 有 15s 重叠 → store-and-forward

## SatLynk 仿真参数

```python
# 星座
detectors = 3       # 535 km SSO, 97.4°
compute = 12        # 550 km, 53° Walker(12/3/1)
relay = 6           # 1100 km, 65° Walker(6/3/1)

# 通信距离
det_comm_range_km = 2000    # 小! 确保 det↔comp 无直接链路
comp_comm_range_km = 5000
relay_comm_range_km = 4000

# 任务
n_tasks = 3          # 3 次 GW alert 窗口内的候选事件
input_size_bytes = 3_000_000
compute_flops = 4e9
output_size_bytes = 100_000
deadline_s = 300     # 5 分钟 (GCN 响应窗)
result_destination = "source"  # 回传触发星

# 数据率
det_data_rate_bps = 2e6
comp_data_rate_bps = 50e6
relay_data_rate_bps = 50e6
```

## Baseline 对比预期

| 指标 | 静态拓扑 Baseline | SatLynk (Nearest-First) | SatLynk (TEG) |
|------|------------------|------------------------|---------------|
| 成功率 | 100% | 0% (找不到多跳路径) | 100% |
| Makespan | ~14s (假设直达) | N/A | ~200-240s |
| 路由发现 | trivial | 失败 | TEG 4-hop 最优路径 |
| 实际物理限制 | 不可见 | 可见但无解 | 可见且有最优解 |

## 验证目标

1. **OBS1 时空扩展图的必要性** — 单跳调度器成功率 0%，TEG 100%
2. 静态拓扑模型给出 ~14s（假设直达）vs 真实 ~220s（4 跳+窗口等待）→ **延迟被低估 15×**
3. 多跳接力是被约束"逼出"的唯一可行解（复现文档 toy case 论证）
4. 不同中继星座密度对端到端延迟的影响
