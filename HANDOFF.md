# KubeFlex — Project Handoff

This document is for the student or group taking over this project. It covers what was
built, what was found, what remains, and how to continue.

---

## What This Project Is

KubeFlex is a carbon-aware container live migration system for Kubernetes. The core idea:
containers running long HPC-style jobs can be transparently checkpointed mid-execution
(using CRIU), transferred to a node in a region with cleaner electricity, and restored
without the application knowing anything happened. The goal is to reduce the total carbon
footprint of compute-intensive jobs by chasing lower-carbon grid regions over time.

The system runs on a local KIND (Kubernetes in Docker) cluster with 3 worker nodes, each
labeled with a US power grid region. It replays historical carbon intensity data
(2020–2022, hourly, 14+ US regions) to simulate multi-region deployments at accelerated
speed.

---

## What Was Built (This Contribution)

This branch extends the original KubeFlex system (Policies 1–5) with a new
overhead-informed heuristic scheduling policy (**Policy 6 / HeuristicPolicy**) and a
rigorous simulation evaluation framework. Work covers three research threads:

### Thread 1: Single-Pod CRIU Live Migration

A live migration pipeline was implemented and benchmarked:

- Running containers (N-body gravitational simulation) are checkpointed mid-execution
  using CRIU 4.1.1, transferred between KIND nodes via `kubectl cp`, and restored on
  the target node
- Key engineering challenges solved: process tree dumping through shell parent, PID
  namespace matching across pods, minimal CRIU flags (adding `--external mnt` or
  `--cgroup-yard` breaks cross-pod restore), holder-script pattern for target pod
  creation
- Same-node and cross-node benchmark results in `data/nbody-artifacts/` and
  `data/carbon-single-pod/`

### Thread 2: Multi-Pod MPI Migration

Two approaches were implemented and compared:

**CRIU-based** (`src/tests/mpi-criu-test/`):
- Coordinated CRIU dump of `orted` process trees across multiple worker pods
- Requires SIGSTOP all workers before sequential dumps; must dump `orted` (not the
  binary) to capture PTY master/slave pairs; restore uses `--inherit-fd` for broken pipe
  FDs
- Conclusion: too fragile and tightly coupled to MPI runtime internals

**Application-checkpoint-based** (`src/controller/migrator/distributed_migration.py`):
- Uses the application's own checkpoint/restart capability
- Extract checkpoint from rank-0, delete MPIJob, redeploy with `-r` (restore) flag
- Much simpler, portable, works with any app that implements checkpoint/resume
- This is the recommended approach; data in `data/mpi-run-test/`

### Thread 3: Carbon-Aware Scheduling — Policy 6 (HeuristicPolicy)

The main thesis contribution. Implementation lives in `src/controller/heuristics/`.

**The problem with Policies 1–5**: They either never migrate (Policy 1), migrate
greedily every hour ignoring overhead cost (Policy 2/5), or use forecast without
accounting for hardware heterogeneity or migration overhead (Policies 3/4). Policy 6
addresses all of these.

**What Policy 6 does** (`policy_heuristic.py:40–241`):

Each hour, `decide(src_grid, now_ts, time_left_h, app_size_mb, ...)` returns either
"stay" or a destination grid. The decision flow:

1. **Deadline gate** (HEUR-08): If `time_left_h + migration_overhead_h > deadline_h`,
   refuse to migrate. No point starting a migration that can't finish before the job ends.

2. **Per-candidate overhead estimation** (`overhead.py`): For each candidate destination,
   compute `ckpt_overhead(app_size_mb, src_hw) + send_overhead(...) + restore_overhead(...)`.
   These are calibrated linear fits from empirical `data/overhead-benchmark/` measurements.

3. **Carbon projection** (stay vs. migrate for each dest):
   - Stay carbon: `time_left_h × src_HW × src_CI`
   - Migrate carbon: `presence_at_decision × src_CI + mig_overhead × src_CI + dest_window × dst_HW × dst_CI`
   - Hardware weighting (`hw_weighting` toggle): multiplies intensity by `power_per_core`
     from `hardware.py`

4. **Lookahead**: Forecast horizon defaults to `(expected_total_min/60) × deadline_multiplier`,
   derived so the window covers the full expected job lifetime

5. **Three ablation toggles** (`--no-hw`, `--no-overhead`, `--no-deadline`): for
   controlled comparison in the evaluation

**Key findings from simulation**:

- Policy 6 outperforms Policies 2 and 5 (the "always migrate" policies) at overhead ≥ 3–12
  minutes across all 12 directional pairs tested (BANC↔CISO and 10 others). At 360-min
  overhead, P2/P5 emit 2.6–8× the carbon of P1 (no migration), while P6 stays near P1.
- Policy 4 (cost-threshold adaptive) sometimes beats Policy 6 at high overhead in scenarios
  where the source grid is already near-optimal — P4's conservative cost threshold outperforms
  P6's empirical estimate in those edge cases.
- **On held-out 2022 test data**: April window (SWPP source, 6-grid pool post-filter) —
  P6 wins outright across 0–360 min overhead. October window (ERCO source, 8 grids) —
  P6 loses to P4 above ~43.6 min overhead (source already near-optimal).
- Deadline gate validation (HEUR-08): at `deadline_multiplier=1.0` (zero slack), P6
  makes 0 migrations and is byte-identical to P1 in both test windows.
- The `scaled_overhead()` fix (commit `9fd523a`) was the key discovery: when the sweep
  harness charged 30-min migration overhead but Policy 6's internal estimator predicted
  only ~5 min (from the linear fit at 64MB anchor), P6 over-migrated. Wrapping the single-run
  tooling to patch P6's estimator with the sweep's actual overhead closed this gap.

**Hardware integration** (`hardware.py`, `sysbench.py`):
- Static hardware lookup (`HW_TABLE`) maps grid regions to `cores` and `power_per_core_w`
  sourced from Nautilus cluster data (`data/hardware/`)
- Sysbench-backed empirical runtime estimation: `perf_ratio(src_grid, dst_grid)` scales
  remaining job time by measured CPU performance ratio (198 records, 48 hostnames, 11 grids)

**Data split discipline** (`data_splits.py`):
- Train: 2020, Validation: 2021, Test (held-out): 2022
- `check_split_access()` raises on any attempt to use 2022 data without explicit
  `bypass_test_split=True` — enforces held-out discipline

---

## What Was Not Done (Remaining Work)

**Phase 5 — Controller Integration & Cluster Validation** was planned but not executed:

1. Wire Policy 6 into `src/controller/controller/main.py` with an
   `elif scheduling_policy == 6:` branch that calls `HeuristicPolicy.decide()`
2. Run at least one full cluster test with `--policy 6` producing `carbon_log.csv`
   and `migration_events.csv` comparable to simulation output
3. Compare cluster vs. simulation results in `data/`

**Phase 4 formal evaluation harness** (evaluate_policies.py, multi-policy boxplots,
ablation heatmap, horizon sensitivity analysis) was planned but only partially executed
through quick tasks. The framework modules exist but the full harness in
`src/tests/carbon-single-pod/evaluate_policies.py` and
`src/tests/carbon-single-pod/evaluation_plots.py` may need completion — check
`.planning/phases/04-*/` for plan details.

**Other deferred items**:
- Distributed CRIU migration (v2): true multi-pod CRIU migration without application
  checkpoint support — highly complex, deferred to a future version
- Real-time carbon API integration: replace historical PostgreSQL data with live
  WattTime/Electricity Maps API calls
- Multi-cloud deployment: extend beyond KIND to real cloud nodes across regions

---

## Key Files

```
src/controller/heuristics/
├── base.py               # BasePolicy ABC
├── hardware.py           # HW_TABLE: grid → cores, power_per_core_w
├── overhead.py           # ckpt/send/restore linear-fit cost estimators
├── policy_heuristic.py   # HeuristicPolicy (Policy 6) — main decision logic
├── policies.py           # Policy1–5 class wrappers
├── runtime.py            # Job runtime estimation functions
├── sysbench.py           # Empirical perf_ratio from sysbench data
└── data_splits.py        # Train/val/test split enforcement

src/tests/carbon-single-pod/
├── run_carbon_migration_test.py   # Main simulation entry point (--expected flag)
├── _simulation_core.py            # simulate_one_run() pure function
├── evaluate_policies.py           # Multi-policy evaluation orchestrator (Phase 4)
├── evaluation_plots.py            # Comparison plots (Phase 4)
├── sweep_overhead_crossover.py    # Overhead threshold sweep tool
├── plot_runtime_breakdown.py      # Gantt-style per-policy timeline visualization
└── graph_results.py               # Carbon log visualization

data/hardware/
├── hardware.csv          # Per-hostname hardware specs from Nautilus
├── hw_avg.csv            # Grid-averaged hardware table (what HW_TABLE loads)
└── sysbench_results.jsonl # CPU benchmark results (198 records)

data/overhead-benchmark/  # Empirical timing from live KIND migrations
data/quick/               # Sweep and Gantt outputs from research investigations
data/carbon-single-pod/   # Live cluster + expected-simulation policy comparison runs
```

---

## How to Run the Simulation (No Cluster Required)

```bash
# Single expected-simulation run — Policy 6, 48h job starting 2020-01-16
python3 src/tests/carbon-single-pod/run_carbon_migration_test.py \
  --expected --expected-completion 2880 --expected-migration 5 \
  --policy 6 --scheduler-time 1609459200 --source-region NE \
  --forecast-cache data/carbon-single-pod/best_run/forecast_cache.json

# Policy 6 overhead crossover sweep — all 12 directional pairs
python3 src/tests/carbon-single-pod/sweep_overhead_crossover.py \
  --mode 6-pairs --overheads 0 5 10 15 30 60 120 180 360 \
  --output data/quick/my-sweep/

# Gantt runtime breakdown plot — BANC→CISO, 30-min overhead
python3 src/tests/carbon-single-pod/plot_runtime_breakdown.py \
  --mode pairwise --src-grid BANC --dst-grid CISO \
  --overhead-min 30 --output data/quick/my-gantt/
```

---

## How to Run the Live Cluster

**Requires Linux** (CRIU only works on Linux kernel; KIND on macOS runs the cluster but
cannot execute real CRIU operations).

See `setup_instructions.txt` for Ubuntu setup. Then:

```bash
# Full deploy (cluster + DB + services)
cd src && bash run.sh --include-cluster --include-db --policy 5 --time 1609459200

# Rebuild and push images after code changes
cd src && bash update.sh

# Run migration test
cd src && bash test.sh --migration
```

Docker images are on Docker Hub under `grahamklingler26/` — see `src/update.sh` for the
full list.

---

## Carbon Data

The PostgreSQL database is seeded from CSVs in `data/regions/` (526MB — gitignored, too
large for GitHub). To reproduce:

1. The original data source is EIA/WattTime historical hourly carbon intensity for
   US grid regions
2. `src/controller/db/upload_data.py` loads CSVs from `test_data/` into the `public.table`
   PostgreSQL table
3. The `db-upload` Kubernetes Job runs this automatically on `run.sh --include-db`

You'll need the raw CSV files to regenerate the database. Contact the original authors
or refer to the WattTime/EIA data pipeline for sourcing.

---

## Tests

```bash
# Run all unit tests for the heuristics module
python3 -m pytest src/tests/heuristics/ -v

# Quick smoke test of the simulation
python3 src/tests/carbon-single-pod/run_carbon_migration_test.py \
  --expected --smoke --policy 6 --scheduler-time 1609459200 --source-region NE
```

There are 27 regression tests (as of last commit) covering: P6 decision logic,
overhead estimators, data split enforcement, simulation core invariants, ablation
toggles, deadline gate, fractional-window accumulator, and sysbench loader.

---

## Repository Structure

```
src/
├── controller/
│   ├── controller/main.py     # KubeFlexController — all policy implementations
│   ├── heuristics/            # Policy 6 modules (new)
│   ├── migrator/              # FastAPI migration service + CRIU logic
│   └── db/                    # PostgreSQL queries + metadata HTTP server
├── manifests/                 # Kubernetes YAML
├── build/                     # Dockerfiles + requirements.txt
└── tests/                     # Test harnesses and simulation tools

data/
├── hardware/                  # Cluster hardware benchmarks
├── overhead-benchmark/        # Empirical migration timing
├── quick/                     # Research sweep outputs
├── carbon-single-pod/         # Policy comparison run data
├── mpi-run-test/              # MPI application-checkpoint data
└── mpi-criu-test/             # MPI CRIU attempt logs
```

---

## Contacts / References

- Original KubeFlex codebase: based on earlier work by Shahrbanoo Farokhi
- Thesis author: Graham Klingler (grahamklingler@gmail.com)
- Docker Hub: `grahamklingler26/`
- Carbon data: WattTime / EIA hourly grid intensity (2020–2022)
- CRIU: https://criu.org — version 4.1.1 required
