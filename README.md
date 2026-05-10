# OASIS — Orbital Agent Scheduling & Inference Simulator

天基智能体任务调度离散事件仿真器。

## Quick Start

```bash
# Zero-dependency toy case verification
python -m oasis.scenarios.toy_case_pure

# Full simulation integration test (requires numpy)
python -m oasis.tests.test_integration

# 5-satellite Walker scenario
python -m oasis.tests.test_walker_5sat

# Export viz JSON (for 3D playback frontend)
python -m oasis.tests.test_viz_export
# → outputs oasis/viz/toy_case_export.json
```

## Viz Export Usage

```python
from oasis.core.simulator import Simulator, SimConfig

sim = Simulator(config)
sim.set_satellites(sats)
sim.set_contact_plan(plan)

# Enable recording BEFORE run()
viz = sim.enable_viz_recording(position_interval_s=1.0)
viz.scenario_name = "my_scenario"

sim.add_task(task)
sim.run()

# Export JSON for 3D visualization frontend
viz.export_to_file("output.json")
# or: json_str = viz.export_json()
```

## Project Structure

```
oasis/
├── core/engine.py           # Custom DES event loop
├── orbital/constellation.py # Orbit propagation & constellation generation
├── network/contact_plan.py  # Contact window precomputation
├── task/dag.py              # Task DAG data structures
├── scheduler/interface.py   # Scheduler protocol + Nearest-First baseline
├── scenarios/
│   ├── toy_case_pure.py     # 3-sat relay verification (no deps)
│   └── toy_case.py          # Full simulation version
└── pyproject.toml
```

## Phase 1 Status

- [x] DES engine (custom event loop with adaptive skip)
- [x] Orbital propagation (Keplerian circular)
- [x] Contact Plan computation
- [x] Task DAG data structures
- [x] Scheduler interface + Nearest-First baseline
- [x] Toy case analytical verification ✓
- [ ] Full DES-driven toy case simulation
- [ ] Oracle MILP baseline
- [ ] 5-satellite Walker scenario
- [ ] Energy model integration

## Design Documents

See `/workspace/shared/OASIS-模拟器设计方案.md` and appendices A-F.
