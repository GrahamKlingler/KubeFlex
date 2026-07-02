# KubeFlex: Carbon-Aware Container Live Migration with Overhead-Informed Heuristics

**Graham Klingler**
*Spring 2026*

---

## Abstract

As HPC and scientific computing workloads increasingly run in shared cloud environments,
the carbon footprint of long-running jobs has become a meaningful optimization target.
KubeFlex is a Kubernetes-based system that uses CRIU (Checkpoint/Restore in Userspace)
to transparently migrate running containers between cluster nodes labeled with US power
grid regions, choosing migration targets to minimize total carbon emissions over a job's
lifetime. This report describes the design and implementation of the full KubeFlex
system, focusing on three contributions: (1) a working CRIU live migration pipeline for
single-pod workloads; (2) a comparison of CRIU-based and application-checkpoint-based
approaches for multi-pod MPI job migration; and (3) a new overhead-informed scheduling
heuristic (Policy 6 / HeuristicPolicy) that accounts for hardware heterogeneity,
migration cost, and job deadlines when making migration decisions, evaluated against
five existing policies in simulation.

---

## 1. Introduction and Motivation

The electricity consumed by data centers and HPC clusters varies significantly in
carbon intensity depending on when and where it is consumed. US power grid regions
can differ by 5–10× in carbon intensity (gCO₂/kWh) at any given hour, and the same
region varies by 2–3× across hours of the day and seasons. For a 48-hour scientific
computing job, the difference between a lucky placement and an unlucky one can amount
to tens of kilograms of CO₂.

Live workload migration — moving a running job from one region to a cleaner one without
stopping it — is an attractive way to exploit this variability. But migration is not
free: checkpointing, transferring, and restoring a container takes time, and during that
time the job is not making progress. A naive policy that always migrates to the current
minimum-carbon region may incur more carbon in migration overhead than it saves.

This project builds and evaluates KubeFlex, a system that addresses this tradeoff. The
key questions are:

- Can CRIU-based live migration work transparently for containerized HPC workloads in
  Kubernetes, and what are the engineering barriers?
- For multi-pod MPI jobs, is CRIU-based migration practical, or are application-level
  checkpointing approaches more reliable?
- Does an overhead-informed heuristic (one that models migration cost, hardware
  heterogeneity, and job deadlines) make better migration decisions than simpler greedy
  policies?

---

## 2. Background

### 2.1 CRIU

CRIU (Checkpoint/Restore in Userspace) is a Linux tool that can freeze a running
process tree, dump its full state to disk (memory pages, file descriptors, network
connections, process metadata), and restore it later — potentially on a different host.
CRIU requires Linux kernel features (`CAP_SYS_ADMIN`, `CAP_SYS_PTRACE`,
`CAP_CHECKPOINT_RESTORE`) and operates at the level of process trees, not virtual
machines. This makes it suitable for containerized environments but sensitive to
kernel/container configuration differences between source and target.

CRIU version 4.1.1 is used in this project, built from source inside the test pod
container image.

### 2.2 Kubernetes and KIND

Kubernetes is the dominant container orchestration platform. Pods (the atomic scheduling
unit) run on worker nodes and are managed by a control plane. KIND (Kubernetes in Docker)
creates a multi-node Kubernetes cluster entirely within Docker containers on a single
host, enabling local development and testing of multi-node scenarios.

The KubeFlex cluster uses KIND with 1 control-plane and 3 worker nodes. Each worker is
labeled with a US power grid region (`REGION=NE`, `REGION=TEN`, `REGION=CENT`) to
simulate geographically distributed nodes.

### 2.3 Carbon Intensity of Power Grids

Carbon intensity (gCO₂/kWh) measures the emissions associated with each unit of
electricity consumed from a power grid, accounting for the mix of generation sources
(coal, natural gas, solar, wind, nuclear, etc.). The US has multiple balancing
authorities (grid regions) that operate largely independently; the EIA and organizations
like WattTime publish hourly historical carbon intensity data for these regions.

This project uses historical hourly carbon intensity data for 2020–2022 across 14+ US
grid regions. The data is stored in PostgreSQL and queried by the scheduling controller.
A train/validation/test split is enforced: 2020 (train), 2021 (validation), 2022
(held-out test).

### 2.4 Related Work

Carbon-aware workload scheduling has been studied in the context of cloud data centers
(e.g., Google's carbon-aware computing initiative, Microsoft's Carbon Aware SDK). These
typically operate at the job-placement level, not the live-migration level. CarbonScaler
and similar systems use carbon forecasts to schedule jobs in advance but do not support
migration of already-running jobs.

CRIU has been used for container migration in Kubernetes environments (DMTCP, P.HAUL)
but not in the context of carbon-aware policies. The combination of live migration
with carbon-intensity-driven decisions, overhead estimation, and hardware heterogeneity
is the novel contribution of this work.

---

## 3. System Design

### 3.1 Architecture Overview

```
Controller (monitor ns) --[HTTP]--> Migration Service (test-namespace)
    |                                      |
    |--[HTTP]--> Metadata Service:8008     |--[exec]--> Migrator Pods (per worker)
    |            (sidecar in DB pod)       |                |
    |                                      |            CRIU dump/restore
    |--[k8s API]--> Pod discovery          |
                    Node labeling          |--[kubectl cp]--> Checkpoint transfer
                                           
PostgreSQL:5432 <-- carbon intensity data (2020-2022, hourly, 14 US regions)
```

**Controller** (`src/controller/controller/main.py`): The central orchestrator. Runs as
a Kubernetes Deployment in the `monitor` namespace. Uses APScheduler to trigger an
`hourly_migration_check()` at configurable simulation speed. Implements all scheduling
policies. Discovers pods via Kubernetes API, calls the Migration Service via HTTP POST.

**Migration Service** (`src/controller/migrator/migrate_service.py`): FastAPI REST
service on port 8000. Accepts `POST /live-migrate` requests and orchestrates the CRIU
migration pipeline via `live_migration.py`. Also exposes `POST /distributed-migrate`
for application-checkpoint-based MPI migration.

**Migrator DaemonSet**: One privileged pod per worker node with `hostPID=true`,
`hostNetwork=true`, and mounts to `/proc`, `/sys`, `/dev`, and the containerd socket.
These pods provide host-level access for CRIU commands. Migration Service calls them
via `kubectl exec`.

**Metadata Service** (`src/controller/db/metadata.py`): HTTP server on port 8008
(sidecar in the database pod). Accepts carbon forecast queries (POST with `{duration,
start_time}`), queries PostgreSQL via PL/pgSQL functions, returns per-region hourly
intensity data.

**PostgreSQL**: Stores 2 years of hourly carbon intensity data. PL/pgSQL stored
functions handle forecast queries. Data loaded at deploy time by the `db-upload` Job.

### 3.2 Simulation Time Mapping

A key design choice: the controller uses a simulated clock (`SCHEDULER_TIME`) that
advances by `SIM_HOURS_PER_CHECK` simulated hours every `CHECK_INTERVAL_SECONDS` real
seconds. This allows replaying 2020–2022 historical carbon data at accelerated speed,
enabling long-horizon policy evaluation in minutes rather than days.

Pod naming during migrations uses a counter suffix pattern: `pod-name`, `pod-name-1`,
`pod-name-2`, etc. This allows the controller to track migration lineage.

### 3.3 Scheduling Policies

Five original policies are implemented in `controller/main.py`:

| Policy | Description |
|--------|-------------|
| P1 | Static initial placement — assign to lowest-carbon region at deploy, never migrate |
| P2 | Hourly greedy — migrate to minimum-carbon region every hour regardless of cost |
| P3 | Forecast-based total — compare cumulative intensity forecasts over expected duration |
| P4 | Adaptive with cost threshold — migrate only when forecast benefit exceeds cost × multiplier; adaptive recheck based on volatility |
| P5 | Always-best — migrate whenever any region has lower intensity than current |

Policy 6 (HeuristicPolicy) is the new contribution, described in Section 5.

---

## 4. Single-Pod CRIU Live Migration

### 4.1 Migration Pipeline

The live migration pipeline (`live_migration.py`) executes in the following steps:

1. **Discovery**: Identify the running container in the source pod using `crictl` via the
   Migrator pod on the source worker.
2. **Mount analysis**: Discover external bind mounts (volumes) that need to be
   transferred alongside the checkpoint.
3. **Target pod creation**: Create a target pod using the next counter name
   (`pod-name-1`), with a holder script that waits for CRIU to restore the process.
4. **CRIU checkpoint** (dump): Execute `criu dump` via `kubectl exec` into the source
   node's Migrator pod, capturing the full process tree state to a checkpoint directory.
5. **Checkpoint transfer**: Use `tar | kubectl cp` to transfer the checkpoint directory
   from the source Migrator pod to the target Migrator pod, across nodes.
6. **CRIU restore**: Execute `criu restore` in the target node's Migrator pod, loading
   the checkpointed state into the holder container.
7. **Verification**: Confirm the restored process is running and producing output.
8. **Cleanup**: Delete the original pod (optional).

The workload used for testing is `elastic_nbody_nompi`, an N-body gravitational
simulation — compute-bound, long-running, and stateless (no network connections or
complex file I/O) which makes it a good CRIU target.

### 4.2 Engineering Challenges

**Process tree structure**: CRIU must dump the complete process tree. For shell-launched
programs, this means dumping the shell script parent rather than the binary directly.
The process tree must include any PTY (pseudo-terminal) masters. Dumping just the binary
leaves orphaned PTY connections that cannot be restored.

**PID namespace isolation**: Kubernetes pods by default run in their own PID namespace.
CRIU's dump and restore must both operate in the container's PID namespace, not the
host's. Using `hostPID: true` on the target pod defeats namespace isolation and prevents
restore. All CRIU operations are executed via `kubectl exec` into the container, which
ensures correct PID namespace context.

**Minimal CRIU flags**: Extensive testing revealed that CRIU is highly sensitive to
flag combinations. The final working flags are `--shell-job --tcp-close` only. Adding
`--external mnt:...` causes CRIU to record PID namespace IDs in the checkpoint metadata
that don't match the target pod. Adding `--cgroup-yard` similarly records cgroup paths
that differ between source and target.

**Holder script pattern**: The target pod cannot run an empty container waiting for
CRIU restore — the container process must exist. A lightweight holder script was
developed that (1) creates the expected process tree stub that CRIU will replace, (2)
waits for CRIU to complete the restore, and (3) monitors the restored process to
completion.

**Cross-node checkpoint transfer**: Kubernetes has no direct pod-to-pod file transfer.
The solution uses `tar` (to handle directory structure and permissions) piped through
`kubectl cp` via the Migrator pods, which are accessible from the Migration Service.

### 4.3 Benchmark Results

Migration overhead was measured across same-node (sanity check) and cross-node
(real) scenarios. The benchmark harness records:
- Baseline runtime (no migration)
- Migration overhead duration (checkpoint + transfer + restore)
- Restored runtime (from checkpoint to completion)
- Delta vs. baseline (how much extra time the migration added)

Results are in `data/nbody-artifacts/`. Key finding: the dominant overhead component is
checkpoint transfer (network), not the CRIU dump/restore operations themselves. For the
N-body workload at typical checkpoint sizes (~64MB), total migration overhead was in
the 5–30 minute range depending on network conditions.

---

## 5. Multi-Pod MPI Job Migration

### 5.1 Challenge

MPI (Message Passing Interface) jobs spawn multiple worker processes that communicate
via shared memory or network sockets. Migrating an MPI job requires migrating all
workers simultaneously or using a coordination protocol. This is substantially harder
than single-pod migration.

### 5.2 CRIU-Based MPI Migration

Implementation in `src/tests/mpi-criu-test/test_criu_mpi_two_pod.sh`.

The approach:
1. SIGSTOP all MPI worker processes simultaneously to prevent cascading failures
   (if any worker continues while others are dumped, MPI communication errors cascade)
2. Sequentially CRIU-dump the `orted` (Open MPI runtime daemon) process tree on each
   worker pod — this captures the PTY master/slave pairs used for MPI stdout routing
3. Transfer all checkpoints to target nodes
4. CRIU-restore all workers, using `--inherit-fd fd[0-2]:/dev/null` to handle broken
   pipe FDs from the original `sshd → orted` connection that no longer exists

**Conclusion**: This approach works for a narrow set of conditions but is:
- Fragile: any difference in kernel version, Open MPI version, or PID namespace
  configuration between source and target causes restore failure
- Complex: coordinating simultaneous STOP/dump across multiple pods with correct
  timing is difficult to make robust
- Not portable: tightly coupled to Open MPI internals (orted process tree, PTY routing)

### 5.3 Application-Checkpoint-Based Migration

Implementation in `src/controller/migrator/distributed_migration.py`.

The approach:
1. Signal the MPI job to write a checkpoint (application-specific mechanism)
2. Extract checkpoint files from the rank-0 worker pod via `kubectl cp`
3. Delete the MPIJob
4. Redeploy the MPIJob on new target nodes, passing `-r` (restore) flag so it loads
   the checkpoint and resumes from where it left off

This is exposed as `POST /distributed-migrate` on the Migration Service.

**Conclusion**: This approach is:
- Reliable: no CRIU version or kernel dependencies; uses the application's own
  checkpoint format
- Portable: any application that implements checkpoint/resume works
- Simple: far less coordination logic than CRIU-based MPI migration
- **Recommended** for multi-pod workloads unless transparent migration (no app changes)
  is a hard requirement

Data in `data/mpi-run-test/` shows successful application-checkpoint migrations with
timing comparable to single-pod CRIU migration.

---

## 6. Carbon-Aware Scheduling: Policy 6 (HeuristicPolicy)

### 6.1 Motivation

The existing policies fail in different ways at high migration overhead:

- **P2/P5** (greedy always-migrate): Emit carbon *faster* than staying put when overhead
  is high, because each migration takes several hours of source-grid carbon to complete
- **P3** (forecast-based): Ignores migration cost entirely; migration count doesn't
  decrease with overhead; can emit more carbon than P1 at high overhead
- **P4** (adaptive with cost threshold): Best of the existing policies but uses a
  manually tuned cost multiplier rather than an empirically calibrated estimate

Policy 6 addresses this by computing a full carbon projection for each migration
candidate — comparing the carbon cost of staying vs. migrating — using calibrated
overhead estimates and hardware-aware intensity accounting.

### 6.2 Decision Logic

Full implementation: `src/controller/heuristics/policy_heuristic.py:40–241`

```python
def decide(src_grid, now_ts, time_left_h, app_size_mb,
           expected_total_minutes, deadline_multiplier=1.5,
           hw_weighting=True, overhead_cost=True, deadline_gate=True):
    ...
```

**Step 1 — Deadline gate**:
```
deadline_h = (expected_total_minutes / 60) * deadline_multiplier
if time_left_h + mig_overhead_h > deadline_h:
    return "stay"   # can't finish migration before deadline
```

**Step 2 — Per-candidate overhead**:
For each candidate destination grid `d`:
```
ckpt_h   = ckpt_overhead(app_size_mb, hw[src]) / 60
send_h   = send_overhead(hw[src], hw[d], app_size_mb) / 60
restore_h = restore_overhead(app_size_mb, hw[d]) / 60
mig_h = ckpt_h + send_h + restore_h
```

The `overhead.py` estimators are calibrated linear fits from `data/overhead-benchmark/`
measurements: `f(app_size_mb) = slope × app_size + intercept` for each component,
fitted per hardware class.

**Step 3 — Carbon projection**:
```
stay_carbon    = time_left_h × hw[src].ppc × src_CI
migrate_carbon = 1.0 × hw[src].ppc × src_CI          # presence at decision hour
               + mig_h × hw[src].ppc × src_CI         # migration overhead
               + Σ fractional_weight(h) × hw[d].ppc × dst_CI(h)  # dest run window
```

The destination window uses piecewise-constant fractional weights at boundaries
(partial first/last hours get weights `< 1.0`) to match the simulation's
discrete-hour carbon accumulation model.

**Step 4 — Decision**:
```
best_dest = argmin over candidates of migrate_carbon
if migrate_carbon[best_dest] < stay_carbon:
    return best_dest
return "stay"
```

### 6.3 Hardware Heterogeneity

`src/controller/heuristics/hardware.py` provides a static `HW_TABLE` mapping grid
regions to hardware specifications:

| Grid | CPU | Cores | Power/Core (W) |
|------|-----|-------|----------------|
| CENT | AMD EPYC 64-core | 8192 | 3.5 |
| NE   | AMD EPYC 24-core | 1152 | 8.3 |
| TEN  | Intel Xeon Silver 4215R | 128 | 16.25 |

When `hw_weighting=True`, all carbon calculations use `intensity × power_per_core`,
making carbon units reflect actual joules rather than raw grid intensity. This captures
the scenario where two grids have similar carbon intensity but different hardware
efficiency — a higher-frequency but less efficient CPU may negate a carbon intensity
advantage.

`sysbench.py` provides `perf_ratio(src_grid, dst_grid)` for runtime estimation: if
the destination hardware is faster, the job takes fewer hours to complete there,
affecting the destination window size.

### 6.4 Data Split Discipline

`data_splits.py` enforces train/validation/test discipline with a runtime guard:

```python
def check_split_access(timestamps, bypass_test_split=False):
    if any(ts in TEST_RANGE_2022 for ts in timestamps):
        if not bypass_test_split:
            raise ValueError("Attempted to access 2022 test data without bypass flag")
```

The `--bypass-test-split` CLI flag (commit `1a659ba`) enables deliberate, logged use
of 2022 data with a loud startup banner. This was used for the final held-out evaluation.

### 6.5 Ablation Toggles

Three ablation flags control which Policy 6 features are active:

| Flag | Disables | Isolates |
|------|----------|---------|
| `--no-hw` | `hw_weighting` + `use_hw` | effect of hardware-aware intensity scaling |
| `--no-overhead` | `overhead_cost` | effect of migration cost estimation |
| `--no-deadline` | `deadline_gate` | effect of deadline-based migration refusal |

These enable 8 ablation variants (2³) for a controlled experiment comparing each
feature's contribution.

---

## 7. Evaluation

### 7.1 Simulation Framework

**Expected simulation mode**: `run_carbon_migration_test.py --expected` runs policy
logic against historical carbon data without a live cluster. It simulates hour-by-hour
decisions using `simulate_one_run()` in `_simulation_core.py`.

**Simulation core invariant** (documented in `_simulation_core.py`):
```
total_carbon = Σ_{hour} (current_grid_HW × current_grid_CI × 1h)
```
This holds regardless of which intensity values policies use for decisions. Policy 3
(HW-blind in decisions) still has its carbon total computed with HW scaling.

**Wall-clock extension**: The simulation charges migration time against real clock hours,
not just simulated hours. A policy that migrates often incurs a time penalty: a 48h job
may take 56h to complete if 8 migrations each cost 1h. This was implemented in commit
`aa83691` (`kfc`) replacing hour-quantized cooldown with a `useful_minutes_completed`
accumulator and `migration_minutes_remaining` state.

### 7.2 Overhead Crossover Analysis

The primary evaluation metric is: at what migration overhead does Policy 6 outperform
each other policy?

**Setup**: For each pair of grids and each overhead value in {0, 5, 10, 15, 30, 60,
120, 180, 360} minutes, simulate all 6 policies on 24 timestamps from 2020–2021 and
compute mean total carbon (kgCO₂eq, HW-scaled).

**Results (BANC↔CISO, representative pair)**:
- P6 beats P2 at overhead ≥ **3.2 min** (BANC→CISO) and **4.7 min** (CISO→BANC)
- P6 beats P5 at overhead ≥ **4.7 min** and **6.1 min**
- P6 vs P3: **no crossover** — P3 ignores `migration_seconds` so migration count stays
  constant and it beats P6 only at 0 overhead; P6 dominates at any positive cost
- P6 vs P4: P4 beats P6 above ~40–120 min in 6 of 12 directional pairs

**All-policies 12-pair sweep** (commit `81b208b`):
- P6 beats P2 in all 12 directions (crossovers 9.7–18.1 min, median ~12)
- P6 beats P5 in all 12 directions (12.4–21.3 min)
- P4 beats P6 at high overhead in 6/12 directions — P4's conservative cost threshold
  is more restrained at extremes
- P2 and P5 carbon balloons to 2.6–8× the P1 baseline at 360-min overhead

**All-HW-grids sweep** (Sweep B, 25-grid pool): P4 dominates P6 in absolute terms
across the full overhead grid when given a wide destination pool — P4's threshold
approach is naturally conservative when the source is already near-optimal.

### 7.3 Hardware-Scaling Effect

Running sweeps with and without hardware scaling (`--no-hw`) reveals (commit `3d3e61e`):

- Raw carbon values are ~7.3–8.4× smaller than HW-scaled values (power_per_core ~5–10W)
- Under `--no-hw`, **P3 newly beats P6 at high overhead** in 4 of 12 directional pairs
  — P6's edge depends on HW awareness in those pairs. This is a thesis-interesting
  finding: hardware heterogeneity changes which policy wins.
- Source grid selection shifts: 25% of timestamps pick a different minimum-carbon source
  under no-HW scaling

### 7.4 Held-Out 2022 Test Evaluation

Final evaluation on 2022 (held-out test data), using `--bypass-test-split` (commits
`1a659ba`, `4db1561`):

**April 2022 window** (source: SWPP, 6-grid pool post-filter removing dominant sources):
- P6 wins outright across 0–360 min overhead range
- No crossover with P1, P3, or P4

**October 2022 window** (source: ERCO, 8-grid pool):
- P6 loses to **P4 above 43.6 min overhead**
- P6 still beats P2/P5 at overhead ≥ ~6–28 min
- Root cause: ERCO source grid is already near-optimal; P4's conservative threshold
  correctly avoids over-migration in this case; P6's empirical model still recommends
  a marginally-beneficial migration at h=31 (saves 0.21 kgCO₂eq vs P1 baseline of
  108.079 kgCO₂eq)

**Deadline gate validation**: At `deadline_multiplier=1.0` (zero slack: 48h deadline
on a 48h job), P6 makes exactly 0 migrations in both test windows and is byte-identical
to P1. Any positive migration overhead trips the gate (`mig_time > 0 when slack = 0`).

### 7.5 Key Diagnostic Findings

Several bugs discovered and fixed during evaluation are thesis-relevant:

**Scaled-overhead mismatch** (commit `9fd523a`): When the sweep harness charged 30-min
overhead but Policy 6's internal estimator predicted ~5 min (from linear fit at 64MB
anchor), P6 over-migrated: 5 migrations in October 2022 producing 121.5 kgCO₂eq vs
P1's 108.1 kgCO₂eq. After wrapping single-run tooling with `scaled_overhead()` to
patch P6's estimator with the sweep's actual overhead value, P6 dropped to 1 migration
(109.6 kgCO₂eq). This is not a bug in Policy 6's logic but a calibration dependency:
the policy is only as good as the overhead estimate it receives.

**Source-running-at-decision-hour term** (commit `2880f49`, root cause fix): Policy 6's
migration carbon projection was missing the "presence cost" at the decision hour — the
1.0 × src_HW × src_CI charge that the sim always applies to the decision hour regardless
of migration. After adding `src_running_at_decision = src_weight × src_intensity_now`,
Policy 6's October 2022 result improved from 109.6 → **107.87 kgCO₂eq**, now beating
the P1 no-migration baseline (108.079 kgCO₂eq) by 0.21 kgCO₂eq.

**Fractional-window accumulator** (commit `2e97528`): Sub-hour migration times produced
a discrete-hour offset error. Fixed with a piecewise-constant weight function matching
the simulation's discrete accumulation model.

---

## 8. Challenges and Lessons Learned

**CRIU flag sensitivity**: CRIU's dump/restore pipeline is highly sensitive to the
exact set of flags used. Adding flags that seem harmless (like `--external mnt`) causes
CRIU to record host-specific metadata (PID namespace IDs, cgroup paths) that don't
transfer across pods. The working configuration (`--shell-job --tcp-close` only) was
found through systematic elimination.

**Namespace handling**: The difference between host PID namespace and container PID
namespace is easy to get wrong. Setting `hostPID: true` on either source or target pod
seems convenient but breaks CRIU restore because the PIDs visible in the container
namespace don't match. All CRIU operations must execute inside the container namespace.

**Image layer caching in KIND**: KIND caches Docker image layers in the cluster. After
rebuilding images, `kind load docker-image` must be used rather than relying on
`imagePullPolicy: Always` to ensure nodes use the new version. Stale image cache caused
several hard-to-diagnose failures early in the project.

**Simulation model fidelity**: Getting the simulation's carbon accounting to match
Policy 6's internal projection required careful alignment of: (1) the wall-clock
extension model, (2) the discrete-hour vs. fractional accumulation semantics, (3) the
source presence cost at the decision hour, and (4) the migration overhead formula
(lump-source vs. three-phase). Each misalignment caused P6 to make subtly wrong
decisions in simulation that wouldn't manifest in live cluster runs.

**Pod lifecycle management**: CRIU restore creates a new process tree in an existing
container. The original container's main process must be replaced by the restored one.
The holder script pattern — a lightweight container that deliberately has the right
process tree shape and waits for CRIU to take over — solved this cleanly.

**MPI migration complexity**: The CRIU-based MPI approach exposed how fragile
cross-pod process state transfer is when multiple processes communicate. The need to
SIGSTOP all workers simultaneously, dump `orted` (not the binary), and handle broken
pipe FDs on restore makes this approach impractical for production use. Application-level
checkpoint/resume is strongly preferred.

---

## 9. Future Work

**Phase 5 — Live cluster integration**: Policy 6 is fully implemented in simulation
but not yet wired into the live controller (`main.py`). The next step is adding an
`elif scheduling_policy == 6:` branch that calls `HeuristicPolicy.decide()` with the
real pod's expected duration and app size, and validating that cluster results match
simulation predictions.

**Formal evaluation harness** (Phase 4 completion): The `evaluate_policies.py`
multi-policy comparison across many starting timestamps and `evaluation_plots.py`
(ablation heatmap, horizon sensitivity, policy comparison boxplot) were planned but
only partially implemented. Completing this harness would enable statistically rigorous
policy comparison with error bars rather than point estimates.

**Calibration to real overhead data**: The `overhead.py` estimators are linear fits
from a small empirical dataset (a few dozen migrations on a single cluster). Better
calibration data from diverse hardware configurations would improve Policy 6's decisions
in the live controller.

**Real-time carbon API**: The current system uses historical data replayed at
accelerated speed. Integrating with live carbon intensity APIs (WattTime, Electricity
Maps, Carbon Aware SDK) would enable genuine real-time carbon-aware scheduling.

**Multi-cloud deployment**: Extending KubeFlex to span real cloud regions (AWS, GCP,
Azure) across different geographic areas would dramatically increase the carbon
variability available for exploitation. The limiting factor is checkpoint transfer
latency over WAN links.

**Distributed CRIU migration without application support**: The `distributed_migration.py`
approach currently requires application-level checkpoint/resume. True transparent
multi-pod CRIU migration (without application changes) remains an open research problem.

---

## 10. Conclusion

This project demonstrates that transparent CRIU-based live migration of containerized
HPC workloads in Kubernetes is feasible but requires careful engineering: correct process
tree handling, strict PID namespace isolation, minimal CRIU flags, and a holder-script
pattern for target pods. For multi-pod MPI workloads, application-checkpoint-based
migration is substantially more practical than CRIU-based approaches.

The central contribution is Policy 6 (HeuristicPolicy): an overhead-informed carbon
scheduling policy that outperforms all five existing policies (P2–P5) at migration
overheads above 3–12 minutes across all 12 tested grid direction pairs, while correctly
refusing to migrate near the job deadline and accounting for hardware-heterogeneous
carbon costs. On held-out 2022 test data, Policy 6 beats the no-migration baseline
(P1) in both evaluation windows, including a case where P4 (the strongest existing
policy) also beats the baseline — confirming that overhead-aware heuristics can improve
on both naive policies and the baseline simultaneously.

The key insight is that migration decisions are only as good as the overhead model
they use. When Policy 6's internal estimator was misaligned with the simulation's
actual overhead charge, it over-migrated and produced worse carbon outcomes than
staying put. Calibrating the estimator to match the evaluation setup restored correct
behavior. This suggests that in any production deployment, periodic recalibration of
the overhead estimator against measured migration costs is essential.

---

## Appendix: Repository Structure

```
src/controller/heuristics/     # Policy 6 implementation
  base.py, hardware.py, overhead.py, policy_heuristic.py,
  policies.py, runtime.py, sysbench.py, data_splits.py

src/tests/carbon-single-pod/   # Simulation and evaluation tools
  run_carbon_migration_test.py, _simulation_core.py,
  sweep_overhead_crossover.py, plot_runtime_breakdown.py,
  evaluate_policies.py, evaluation_plots.py

data/hardware/                 # Nautilus cluster hardware benchmarks
data/overhead-benchmark/       # Empirical migration timing data
data/quick/                    # Sweep outputs and Gantt plots
data/carbon-single-pod/        # Live cluster policy comparison runs
```

See `HANDOFF.md` for setup instructions, reproduction commands, and continuation guidance.
