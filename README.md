# SatLynk

A simulator for satellite on Low Earth Orbit — **OASIS** (Orbital Agent Scheduling & Inference Simulator)

## Overview

面向天基智能体任务调度的离散事件仿真器，验证卫星星座中 AI 推理任务的调度问题。

**核心场景**：天格计划探测卫星观测伽马射线暴 → 请求天基计算卫星（三体计算星座）运行 2B 模型推理。

## Quick Start

```bash
# 运行天格 GRB 场景 (3 探测 + 4 计算星)
python -m oasis.scenarios.tiange_grb

# 运行 2800 星全规模场景
python -m oasis.scenarios.tiange_2800

# 生成 3D 可视化
python -m oasis.viz.generate_tiange
# → 打开 site/index.html

# 运行测试
python -m oasis.tests.test_integration
python -m oasis.tests.test_phase2
```

## Architecture

```
oasis/
├── core/           # DES 引擎 + Simulator 集成类
├── orbital/        # 轨道传播 + Walker 星座生成 + 地影模型
├── network/        # Contact Plan 预计算
├── task/           # Task DAG + 权重缓存 (C4 约束)
├── scheduler/      # 调度器接口 + Nearest-First baseline
├── energy/         # 电池动力学 + 光伏 + 功耗模式
├── metrics/        # 仿真指标收集
├── viz/            # Three.js 3D 前端生成
├── scenarios/      # 场景脚本
└── tests/          # 集成测试
```

## Key Results

| 场景 | 计算星数 | 成功率 | 关键洞察 |
|------|---------|--------|---------|
| `tiange_grb` | 4 | 17% | C2 链路门控主导，稀疏星座无法保证实时性 |
| `tiange_2800` | 2800 | 92% | 星座密度是解决时空可达性的根本途径 |

## Dependencies

- Python 3.11+
- NumPy

可视化额外需要浏览器（Three.js 已内联，无需 npm install）。
