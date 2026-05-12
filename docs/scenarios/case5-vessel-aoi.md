# Case 5: 海上船舶检测 — 分布式推理与信息新鲜度 (AoI)

## 科学/工程背景

对特定海域进行近实时船舶监控（非法捕鱼 / 走私 / IUU 渔业执法）。
传统流程：拍摄→下传地面→处理→生成告警，全链路延迟 30 分钟到数小时。
2024 年 ICCSPA 获奖论文 (arXiv:2410.07431) 提出将 YOLOv8 推理
分摊到相邻卫星做分布式 edge inference，以降低 Age of Information (AoI)。

**该论文的关键假设（SatLynk 要挑战的）**：
- 假设星间链路 **始终可达**（实际是间歇性的）
- 假设带宽 **恒定** 且 **对称**
- 不建模 **能耗约束**（某些邻居可能在地影中无法接受推理任务）
- AoI 计算使用 **静态模型**

**SatLynk 能揭示**：在真实 Contact Plan 约束下，实际 AoI 比理想模型预测值
高 2-5 倍。星座密度的临界点（相变点）也会右移。

**文献锚点**：
- arXiv:2410.07431: "20 planes × 20 sats = peak AoI < 60s, compression > 23000×"
- VHRShips dataset + YOLOv8 for vessel detection
- Sentinel-2 / SkySat 级别高分辨率图像

## 任务流

```
EO 卫星 S-01 拍摄海域图像 (100 MB)
    ↓
切分为 4×4 = 16 块 (每块 ~6 MB)
    ↓
分发给有 ISL 链路的邻居星做 YOLOv8 推理:
  S-01 自己处理 4 块 (本地)
  S-02 接收 4 块 [需要链路窗口]
  S-03 接收 4 块 [需要链路窗口]
  S-04 接收 4 块 [需要链路窗口]
    ↓
各星推理完成后回传 bounding box 列表 (~10 KB/块)
    ↓
S-01 汇聚 16 块结果 → 完整检测图
    ↓
AoI = t(最后一块结果汇聚) - t(拍摄)
```

## 观测数据

| 数据产物 | 规格 | 大小 |
|---------|------|------|
| 单景 VHR 图像 | 0.5m 分辨率, 压缩 | ~100 MB |
| 切片 (4×4) | 16 块 | ~6 MB / 块 |
| 推理结果 (per block) | bounding box 列表 | ~10 KB |
| **总上行流量** (分发) | 12 块 × 6 MB | ~72 MB |
| **总下行流量** (结果回传) | 12 块 × 10 KB | ~120 KB |

## AI 模型

| 属性 | 值 |
|------|---|
| 模型 | YOLOv8-L (ship detection, fine-tuned on VHRShips) |
| 参数量 | ~43M |
| 权重大小 | 200 MB (FP16) |
| 单块推理 FLOPs | ~2×10⁹ |
| 在 100 TOPS 芯片上耗时 | ~2 s / block |
| 功耗 | 15 W (推理) |

## AoI 定义

```
AoI = max over all blocks (t_result_received[i] - t_capture)

其中:
  t_capture = 图像拍摄时刻
  t_result_received[i] = 第 i 块推理结果回到 S-01 的时刻

对于本地处理的块: AoI_local = t_inference ≈ 2s
对于远程处理的块: AoI_remote = t_transfer_out + t_inference + t_transfer_back
                            = 6MB/rate + 2s + 10KB/rate
```

## 星座设计

```python
# Walker constellation (可变密度，用于 sweep)
# 基准配置: Walker(20/4/1), 550 km, 53°
total_sats = 20
num_planes = 4
altitude_km = 550
inclination_deg = 53

# 通信
max_comm_range_km = 3000
intra_plane_rate_bps = 1e9    # 1 Gbps (同面永久链路)
inter_plane_rate_bps = 50e6   # 50 Mbps (跨面间歇链路)

# 拍摄卫星 (EO + 计算能力有限)
eo_compute_flops = 100e9      # 能做本地推理但慢
comp_compute_flops = 1e12     # 算力星快 10×
```

## SatLynk 仿真参数

```python
# Sweep 实验: 星座密度从 12 到 100
density_sweep = [12, 20, 40, 60, 80, 100]

# 每种密度运行:
n_capture_events = 10     # 10 次拍摄事件，随机时刻
blocks_per_image = 16
block_size_bytes = 6_000_000
inference_flops_per_block = 2e9
result_size_bytes = 10_000
model_weight_bytes = 200_000_000

# AoI target
target_peak_aoi_s = 60  # 论文的目标值
```

## Baseline 对比预期

| 指标 | 静态拓扑 (论文假设) | SatLynk (Contact Plan) |
|------|-------------------|----------------------|
| Peak AoI @ 20 sats | ~15s | ~40-80s |
| Peak AoI < 60s 需要的密度 | 20×20=400 sats | ~800-1200 sats |
| 分发失败率 | 0% | 10-30% (邻居不可达) |
| 能耗可见性 | 无 | 精确到每块推理 |
| **乐观偏差** | — | **AoI 被低估 2-5×** |

## 验证目标

1. 量化 **静态拓扑假设导致的 AoI 低估幅度**（2024 论文的结论需要修正）
2. 真实 Contact Plan 下的 "密度→AoI" 曲线 vs 理想化曲线的偏移
3. **相变点右移**：达到 target AoI < 60s 需要更多卫星
4. intra-plane (永久链路) vs inter-plane (间歇链路) 的 AoI 贡献差异
5. 能耗约束对推理可用性的影响（地影中的邻居无法帮忙）
