# Case 6: 星座联邦学习 — 模型聚合的通信调度

## 科学背景

星座卫星各自采集地球观测数据，协作训练共享模型（联邦学习），不下传原始数据。
核心挑战：模型梯度/参数聚合需要星间通信，但 ISL 是间歇性的——同面内永久可达，
跨面只在交叉点附近短暂可用。

现有工具（FLySTacK 2024）用统计模型建模通信（"平均每轨道可通信 X 分钟"），
而非精确 Contact Plan。SatLynk 可以回答：给定真实 Contact Plan，最快几轮
能完成一次全局聚合？

## 参数

| 属性 | 值 |
|------|---|
| 星座 | 20 颗 EO 卫星, Walker(20/4/1), 550km 53° |
| 模型 | ResNet-50 for 地物分类, ~100 MB |
| 梯度压缩 | 10× → 每轮上传 10 MB / 星 |
| intra-plane ISL | 永久可达, 1 Gbps |
| inter-plane ISL | 每轨道 ~5 min 窗口, 50 Mbps |
| 本地训练 | 30s / round (100 TOPS) |
| 聚合策略 | Ring-AllReduce / Hierarchical / Gossip |

## 验证目标

1. 不同聚合策略在真实 Contact Plan 下的 time-to-convergence
2. 静态模型（假设链路永在）的乐观偏差
3. 能耗预算对可训练轮次的限制
