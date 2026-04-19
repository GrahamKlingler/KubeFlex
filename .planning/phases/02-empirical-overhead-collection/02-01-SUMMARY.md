---
phase: 02-empirical-overhead-collection
plan: 01
subsystem: migration-instrumentation
tags: [timing, instrumentation, workloads, benchmark, criu]
dependency_graph:
  requires: []
  provides:
    - timing-instrumentation-in-live_migration
    - workload-pod-yaml-templates
  affects:
    - src/controller/migrator/live_migration.py
    - src/tests/overhead-benchmark/workloads/
tech_stack:
  added: []
  patterns:
    - time.perf_counter() wrapping at call sites (not inside called methods)
    - logger.info(json.dumps({event, duration_ms, ...})) for structured log output
    - nodeSelector (not affinity) for deterministic KIND node placement
key_files:
  created:
    - src/tests/overhead-benchmark/workloads/sysbench-cpu.yml
    - src/tests/overhead-benchmark/workloads/sysbench-memory.yml
    - src/tests/overhead-benchmark/workloads/memcount.yml
  modified:
    - src/controller/migrator/live_migration.py
decisions:
  - "Timing wraps at perform_migration() call sites rather than inside each phase method (per RESEARCH.md anti-pattern warning) to keep phase methods single-responsibility"
  - "JSON log lines emitted via logger.info so they appear in kubectl logs output alongside existing migration log messages"
  - "nodeSelector uses kubernetes.io/hostname key for deterministic placement; benchmark harness will sed-replace the value per region pair"
  - "memcount uses salamander1223/testpod image (already in KIND) and allocates 256 MB via bytearray for a memory-resident CRIU-migratable workload"
metrics:
  duration: ~5 minutes
  completed: "2026-04-18"
  tasks_completed: 2
  tasks_total: 2
  files_created: 3
  files_modified: 1
---

# Phase 02 Plan 01: Migration Timing Instrumentation and Workload Templates Summary

Per-phase CRIU migration timing via `time.perf_counter()` added to `perform_migration()`, emitting three structured JSON log lines (`checkpoint_complete`, `transfer_complete`, `restore_complete`) with `duration_ms`; three workload pod YAML templates (sysbench-cpu, sysbench-memory, memcount) created with full CRIU securityContext and deterministic `nodeSelector`.

## Tasks Completed

| Task | Name | Commit | Key Files |
|------|------|--------|-----------|
| 1 | Add timing instrumentation to perform_migration() | 99e1293 | src/controller/migrator/live_migration.py |
| 2 | Create workload pod YAML templates for benchmark matrix | 5448ca6 | src/tests/overhead-benchmark/workloads/*.yml |

## What Was Built

### Task 1: Timing Instrumentation

Three timing blocks were added inside `perform_migration()` in `CriuMigrationTracker`:

- **Step 6 (checkpoint):** `time.perf_counter()` wraps `perform_criu_dump()`. On success, emits `checkpoint_complete` JSON with `duration_ms`, `source_node`, `target_node`, `source_pod`, `target_pod`.
- **Step 7 (transfer):** `time.perf_counter()` wraps `transfer_checkpoint_to_target()`. Emits `transfer_complete` JSON.
- **Step 9 (restore):** `time.perf_counter()` wraps `execute_criu_restore_in_target()`. Emits `restore_complete` JSON.

No new imports were needed (`time` and `json` were already imported at lines 15-17). Method signatures and return types of the three phase methods are unchanged. Control flow (exception raise on failure) is preserved.

### Task 2: Workload YAML Templates

Three pod templates created in `src/tests/overhead-benchmark/workloads/`:

- **sysbench-cpu.yml** — `grahamklingler26/sysbench-testpod:latest`, runs `sysbench cpu --cpu-max-prime=100000 --time=0 run` (runs indefinitely)
- **sysbench-memory.yml** — same image, runs `sysbench memory --memory-block-size=1K --memory-total-size=1000G --time=0 run`
- **memcount.yml** — `salamander1223/testpod:latest`, inline Python script allocating 256 MB via `bytearray` and writing counter values; memory request 384Mi/limit 512Mi

All three share:
- `namespace: test-namespace`, `restartPolicy: Never`
- `nodeSelector: {kubernetes.io/hostname: kind-worker}` (sed-replaceable for benchmark harness)
- Full CRIU securityContext: `privileged: true`, capabilities `[SYS_PTRACE, SYS_RESOURCE, NET_ADMIN, SYS_ADMIN, SYS_TIME, CHECKPOINT_RESTORE, SYS_CHROOT, SETPCAP, SETGID, SETUID]`, `seccompProfile: Unconfined`
- `checkpoint-volume` hostPath at `/tmp/checkpoints` and `script-data` emptyDir

## Deviations from Plan

None — plan executed exactly as written.

## Known Stubs

None — all instrumentation is wired to real CRIU migration operations. YAML templates reference real images already in use by the existing test suite.

## Threat Flags

No new threat surface beyond what was documented in the plan's threat model. Timing instrumentation runs inside the existing privileged migration pod (T-02-01, accepted). Workload YAMLs request identical privileges to the existing `src/tests/sysbench/sysbench.yml` (T-02-02, accepted). memcount memory is bounded at 512Mi (T-02-03, accepted).

## Self-Check: PASSED

All created files exist on disk. Both task commits (99e1293, 5448ca6) verified in git log. live_migration.py parses without AST errors. All three YAML templates contain expected content (validated with content checks).
