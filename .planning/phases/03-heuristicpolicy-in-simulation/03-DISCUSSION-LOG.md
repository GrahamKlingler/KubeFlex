# Phase 3: HeuristicPolicy in Simulation - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-04-19
**Phase:** 03-heuristicpolicy-in-simulation
**Areas discussed:** Overhead estimation calibration, Migration carbon cost, Simulation integration, Re-evaluation & deadline

---

## Overhead Estimation Calibration

### Q1: How should estimation functions handle workload variance?

| Option | Description | Selected |
|--------|-------------|----------|
| Aggregate model | Use all_workloads summary stats (mean/median across all 54 migrations). Simpler. | |
| Size-based model | Parameterize by app_size. Fit linear relationship from Phase 2 data. | ✓ |
| You decide | Claude picks based on data and pseudocode. | |

**User's choice:** Size-based model
**Notes:** Aligns with heuristic.txt function signatures that accept app_size parameter.

### Q2: How should app_size be provided in simulation mode?

| Option | Description | Selected |
|--------|-------------|----------|
| CLI argument | Add --app-size-mb flag. Simple and explicit. | ✓ |
| Derived from workload type | Map workload names to approximate sizes. | |
| You decide | Claude picks. | |

**User's choice:** CLI argument (after discussing dynamic approach)
**Notes:** User asked about dynamic node-reported workload size. Clarified that live cluster can query container memory (Phase 5), but simulation mode needs CLI arg since no running container exists. Two-layered approach agreed: CLI arg for sim, real queries for live.

### Q3: Model fitting approach?

| Option | Description | Selected |
|--------|-------------|----------|
| Linear fit | overhead = a*size + b from 3 workload data points. | ✓ |
| Fixed lookup table | Map known sizes to measured overheads directly. | |
| You decide | Claude picks. | |

**User's choice:** Linear fit

### Q4: Account for hardware differences in overhead estimation?

| Option | Description | Selected |
|--------|-------------|----------|
| Include HW scaling | Scale by hardware capability ratio. Matches pseudocode. | ✓ |
| Ignore HW differences | Same overhead regardless of hardware. | |
| You decide | Claude picks. | |

**User's choice:** Include HW scaling

### Q5: Handle thin data (3 data points for linear fit)?

| Option | Description | Selected |
|--------|-------------|----------|
| Document limitation | Note as future work. Sufficient for thesis. | ✓ |
| Generate more data | Run additional benchmarks before fitting. | |

**User's choice:** Document limitation

---

## Migration Carbon Cost

### Q1: How to handle transfer phase's carbon cost?

| Option | Description | Selected |
|--------|-------------|----------|
| Hardware wattage only | Use hw.wattage * intensity for all 3 phases. | |
| Include network estimate | Estimate network power (~10-20W per NIC). | |
| Skip migration carbon | Only compare running carbon. | |

**User's choice:** Other — Include network estimate but with option to disable it
**Notes:** User wants ablation capability for Phase 4.

### Q2: Where should the network power toggle live?

| Option | Description | Selected |
|--------|-------------|----------|
| HeuristicPolicy constructor arg | include_network_power=True by default. | |
| CLI flag on simulation | --include-network-power flag. | |
| Both | CLI flag feeds into constructor. | ✓ |

**User's choice:** Both

### Q3: Which carbon intensity during migration window?

| Option | Description | Selected |
|--------|-------------|----------|
| Current hour intensity | Use intensity at current simulation hour for all phases. | ✓ |
| Weighted avg src/dest | Average source and destination intensity. | |

**User's choice:** Current hour intensity, with clarification: checkpoint uses source HW values, restore uses dest HW values.

### Q4: Default network power value?

| Option | Description | Selected |
|--------|-------------|----------|
| 15W default | Conservative middle estimate for 10GbE NIC. | ✓ |
| You decide | Claude picks defensible value. | |
| Configurable constant | Easy-to-change module constant. | |

**User's choice:** 15W default

---

## Simulation Integration

### Q1: How should Policy 6 integrate into simulation harness?

| Option | Description | Selected |
|--------|-------------|----------|
| Separate class call | HeuristicPolicy class, dispatcher delegates. | |
| Inline like others | Add elif block in simulate_policy_decision(). | |
| Refactor all policies | Extract all policies into separate classes. | ✓ |

**User's choice:** Refactor all policies
**Notes:** Scope expansion beyond INFR-01. Follow-up confirmed user wants this in Phase 3 (not deferred to Phase 4).

### Q2: Include full refactor in Phase 3 scope?

| Option | Description | Selected |
|--------|-------------|----------|
| Include in Phase 3 | Extract all 5 existing policies alongside Policy 6. | ✓ |
| Defer to Phase 4 | Only add HeuristicPolicy now. | |

**User's choice:** Include in Phase 3

### Q3: CLI args scope?

| Option | Description | Selected |
|--------|-------------|----------|
| Policy-6-only | Only used when --policy 6. | ✓ |
| General flags | Available for all policies. | |

**User's choice:** Policy-6-only

### Q4: Should policies share a common base class?

| Option | Description | Selected |
|--------|-------------|----------|
| Abstract base class | BasePolicy with abstract decide(). | ✓ |
| Duck typing | Same signature, no formal base. | |
| You decide | Claude picks. | |

**User's choice:** Abstract base class

### Q5: Where should refactored policy classes live?

| Option | Description | Selected |
|--------|-------------|----------|
| All in heuristics/ | base.py, policies.py, policy_heuristic.py | ✓ |
| Policies 1-5 stay inline | Only Policy 6 in heuristics/. | |
| You decide | Claude picks. | |

**User's choice:** All in heuristics/

---

## Re-evaluation & Deadline

### Q1: How should re-evaluation work?

| Option | Description | Selected |
|--------|-------------|----------|
| Same hourly check | Existing simulation loop satisfies HEUR-07. | ✓ |
| Adaptive frequency | More frequent near deadline or high volatility. | |
| You decide | Claude determines. | |

**User's choice:** Same hourly check

### Q2: How should deadline be specified?

| Option | Description | Selected |
|--------|-------------|----------|
| CLI arg --deadline-hours | Deadline as hours from start. | |
| Absolute timestamp | Unix timestamp. | |
| Relative to expected-completion | Multiplier of expected_completion. | ✓ |

**User's choice:** Relative to expected-completion

### Q3: Default deadline multiplier?

| Option | Description | Selected |
|--------|-------------|----------|
| 1.5x | 50% buffer. Common SLA pattern. | ✓ |
| 2.0x | 100% buffer. Very generous. | |
| No default, required arg | Force user to specify. | |

**User's choice:** 1.5x

### Q4: What happens when deadline gate blocks migration?

| Option | Description | Selected |
|--------|-------------|----------|
| Log in migration_events.csv | 'skipped' event with reason='deadline_gate'. | ✓ |
| Silent skip | No special logging. | |
| Both CSV + console | Maximum visibility. | |

**User's choice:** Log in migration_events.csv

---

## Claude's Discretion

- Linear regression fitting methodology for 3-workload overhead data
- `BasePolicy.decide()` exact parameter list beyond core ones
- Mapping Phase 2 workload names to approximate app_size values for the linear fit

## Deferred Ideas

None — discussion stayed within phase scope
