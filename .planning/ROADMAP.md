# Roadmap: KubeFlex Heuristic Extension

## Overview

The thesis extends KubeFlex's existing carbon-aware migration system with a new overhead-informed scheduling heuristic (Policy 6) and a rigorous evaluation framework. Work proceeds in five phases: hardware and data foundations first, then empirical overhead measurement on the live cluster, then the full heuristic implementation in simulation, then the evaluation harness and results, and finally controller integration and cluster validation. Distributed migration (v2) is deferred until heuristic work is complete.

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [ ] **Phase 1: Hardware Foundation & Data Split** - Establish static hardware lookup and train/val/test data discipline before any code depends on them
- [ ] **Phase 2: Empirical Overhead Collection** - Measure real checkpoint/transfer/restore costs on KIND cluster to ground estimation functions in data
- [ ] **Phase 3: HeuristicPolicy in Simulation** - Implement overhead estimation functions and Policy 6 fully operable in expected-simulation mode
- [ ] **Phase 4: Evaluation Harness & Simulation Results** - Multi-policy comparison framework, ablation study, sensitivity analysis, and complete simulation results
- [ ] **Phase 5: Controller Integration & Cluster Validation** - Integrate Policy 6 into live controller and validate against real KIND cluster migrations

## Phase Details

### Phase 1: Hardware Foundation & Data Split
**Goal**: Hardware heterogeneity data is codified and the carbon dataset is partitioned before any estimation or evaluation code touches it
**Depends on**: Nothing (first phase)
**Requirements**: HEUR-01, HEUR-09
**Success Criteria** (what must be TRUE):
  1. `hardware.py` contains a complete HW_TABLE mapping NE, TEN, and CENT regions to cores and wattage-per-core values sourced from Nautilus data
  2. Carbon data is documented as split into train (2020), validation (2021), and held-out test (2022) periods, with a clear record of which timestamps are permissible for development
  3. Job runtime estimation (remaining hours from expected duration) is implemented and callable by Policy 6
  4. The hardware lookup can be imported and queried in a Python REPL with no errors
**Plans:** 3 plans

Plans:
- [x] 01-01-PLAN.md — Create heuristics package with hardware lookup (HEUR-01) and data split enforcement
- [x] 01-02-PLAN.md — Implement runtime estimation (HEUR-09) and replace HW_VALS in simulation harness
- [x] 01-03-PLAN.md — Collect real clock speed data for CENT/NE from Nautilus cluster (D-04) and update hardware.py

### Phase 2: Empirical Overhead Collection
**Goal**: Real checkpoint/transfer/restore timing data exists from 10+ live migrations so estimation functions have empirical grounding
**Depends on**: Phase 1
**Requirements**: EVAL-05, EVAL-07
**Success Criteria** (what must be TRUE):
  1. At least 10 live migrations are executed and timed on the KIND cluster with structured output (CSV or JSON) recording checkpoint duration, transfer duration, restore duration, and app size
  2. Migration cost component breakdown (checkpoint vs transfer vs restore) is visualized and documented
  3. Raw measurement data is committed to `data/` and reviewable without re-running the cluster
**Plans:** 3 plans

Plans:
- [x] 02-01-PLAN.md — Instrument live_migration.py with timing and create workload YAML templates
- [x] 02-02-PLAN.md — Create benchmark harness for 54-migration matrix with CSV/JSON output
- [x] 02-03-PLAN.md — Create visualization script for overhead component breakdown (EVAL-07)

### Phase 3: HeuristicPolicy in Simulation
**Goal**: Policy 6 is fully implemented as a standalone module and runs correctly in expected-simulation mode, producing decisions visible in CSV output
**Depends on**: Phase 2
**Requirements**: HEUR-02, HEUR-03, HEUR-04, HEUR-05, HEUR-06, HEUR-07, HEUR-08, INFR-01, INFR-03
**Success Criteria** (what must be TRUE):
  1. `heuristics/overhead.py` provides callable checkpoint, transfer, and restore cost estimation functions calibrated against Phase 2 empirical data
  2. `heuristics/policy_heuristic.py` contains a `HeuristicPolicy` class implementing stay-vs-migrate comparison, deadline gate, and forecast-based destination evaluation
  3. Running `run_carbon_migration_test.py --expected --policy 6` completes without error and produces `carbon_log.csv` and `migration_events.csv`
  4. Periodic re-evaluation fires correctly across simulated hours (observable in migration_events output)
  5. Deadline gate demonstrably prevents migration when `time_left + mig_time > deadline` (verifiable by inspecting a simulation run near deadline)
**Plans**: TBD

### Phase 4: Evaluation Harness & Simulation Results
**Goal**: A rigorous multi-policy evaluation framework exists and produces complete simulation results covering all policies, ablation variants, and sensitivity analyses on development-period data
**Depends on**: Phase 3
**Requirements**: HEUR-10, HEUR-11, EVAL-01, EVAL-02, EVAL-03, EVAL-06, EVAL-08, INFR-04, INFR-05
**Success Criteria** (what must be TRUE):
  1. `evaluate_policies.py` runs all 6 policies (Policies 1-5 existing, Policy 6 new) across 10+ starting timestamps and writes a unified results CSV
  2. `graph_results.py` (extended) produces a comparison graph showing carbon savings % and migration count for all policies side-by-side
  3. Ablation study produces results for all 8 heuristic variants (with/without hardware weighting, overhead estimation, deadline awareness) and they are graphed
  4. Forecast horizon sensitivity analysis covers H from 1h to 48h and shows how savings vary with horizon
  5. Noisy-forecast evaluation at multiple sigma levels is included in results
  6. All simulation results use only train (2020) and validation (2021) data — 2022 test data remains untouched
**Plans**: TBD

### Phase 5: Controller Integration & Cluster Validation
**Goal**: Policy 6 runs in the live KubeFlex controller on the KIND cluster and cluster results validate or challenge simulation findings
**Depends on**: Phase 4
**Requirements**: INFR-02, EVAL-04
**Success Criteria** (what must be TRUE):
  1. `controller/main.py` includes an `elif scheduling_policy == 6:` branch that invokes `HeuristicPolicy` and the live controller deploys without errors using `--policy 6`
  2. At least one full cluster test run completes with Policy 6 active and produces `carbon_log.csv` and `migration_events.csv` comparable to simulation output
  3. Cluster results are committed to `data/` alongside simulation results for thesis comparison
**Plans**: TBD

## Progress

**Execution Order:**
Phases execute in numeric order: 1 -> 2 -> 3 -> 4 -> 5

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Hardware Foundation & Data Split | 0/3 | Planning complete | - |
| 2. Empirical Overhead Collection | 0/3 | Planning complete | - |
| 3. HeuristicPolicy in Simulation | 0/? | Not started | - |
| 4. Evaluation Harness & Simulation Results | 0/? | Not started | - |
| 5. Controller Integration & Cluster Validation | 0/? | Not started | - |
