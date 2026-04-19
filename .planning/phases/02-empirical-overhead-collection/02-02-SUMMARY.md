---
phase: 02-empirical-overhead-collection
plan: 02
subsystem: overhead-benchmark
tags: [benchmark, timing, csv, validation, criu, migration]
dependency_graph:
  requires:
    - timing-instrumentation-in-live_migration (from 02-01)
    - workload-pod-yaml-templates (from 02-01)
  provides:
    - benchmark-harness-run_overhead_benchmark
    - csv-schema-validation-test
  affects:
    - src/tests/overhead-benchmark/run_overhead_benchmark.py
    - src/tests/overhead-benchmark/test_csv_schema.py
tech_stack:
  added: []
  patterns:
    - requests.post with 300s timeout for synchronous migration API calls
    - kubectl --since-time=ISO8601 for log filtering (avoids cross-migration contamination)
    - csv.DictWriter in append mode for incremental write-per-migration recovery
    - signal.signal(SIGINT/SIGTERM) handler to flush JSON metadata on interrupt
    - plain-function test runner matching test_hardware.py pattern (no pytest)
key_files:
  created:
    - src/tests/overhead-benchmark/run_overhead_benchmark.py
    - src/tests/overhead-benchmark/test_csv_schema.py
  modified: []
decisions:
  - "Log filtering uses --since-time with ISO8601 timestamp captured just before each migration POST to prevent cross-run contamination (RESEARCH.md Pitfall 1)"
  - "Checkpoint directory cleanup runs before each migration on all three worker nodes via kubectl exec to migrator pods (RESEARCH.md Pitfall 2)"
  - "Migration service pod name resolved dynamically via kubectl get pod -l app=python-migrate to handle pod restarts (RESEARCH.md Open Question 2)"
  - "CSV append mode ensures partial runs are recoverable if harness is interrupted mid-run"
  - "SIGINT/SIGTERM signal handler flushes overhead_metadata.json before exit so interrupted runs produce usable output"
metrics:
  duration: ~6 minutes
  completed: "2026-04-18"
  tasks_completed: 2
  tasks_total: 2
  files_created: 2
  files_modified: 0
---

# Phase 02 Plan 02: Benchmark Harness and CSV Schema Validation Summary

54-migration CRIU overhead benchmark harness (`run_overhead_benchmark.py`) and offline CSV schema validator (`test_csv_schema.py`) created; harness drives all workload/region-pair/repetition combinations via REST API, extracts per-phase timing from kubectl logs, and writes structured CSV+JSON output to `data/overhead-benchmark/`.

## Tasks Completed

| Task | Name | Commit | Key Files |
|------|------|--------|-----------|
| 1 | Create benchmark harness run_overhead_benchmark.py | eb37002 | src/tests/overhead-benchmark/run_overhead_benchmark.py |
| 2 | Create CSV schema validation test | d0e2889 | src/tests/overhead-benchmark/test_csv_schema.py |

## What Was Built

### Task 1: Benchmark Harness (`run_overhead_benchmark.py`, 562 lines)

The main benchmark driver that orchestrates all 54 migrations (3 workloads x 6 region pairs x 3 repetitions per D-06). Key design elements:

**Migration loop:** Nested over `WORKLOADS`, `REGION_PAIRS`, and repetition count. Each iteration:
1. Cleans up leftover workload pods and CRIU checkpoint directories on all three worker nodes
2. Deploys workload YAML template with nodeSelector sed-replaced to target source node
3. Waits for pod Ready state (up to 120s)
4. Sleeps 5s for workload initialization (critical for memcount 256 MB allocation)
5. Captures ISO8601 timestamp for `--since-time` log filter
6. POSTs to `/live-migrate` with 300s timeout
7. Sleeps 2s for log flush, then extracts timing from kubectl logs
8. Writes CSV row in append mode immediately (recoverable partial runs)

**Pitfall mitigations applied:**
- Pitfall 1 (log contamination): `--since-time` with per-migration timestamp
- Pitfall 2 (checkpoint dir collision): `kubectl exec -n monitor migrator-{node} -- rm -rf /tmp/checkpoints/migration_checkpoint` before each migration
- Pitfall 3 (pod naming counter): Delete all pods by label and by explicit name (base + suffixes 0-9) before each migration

**Metadata JSON:** Written at end of run (and on SIGINT/SIGTERM). Contains run config, total/successful/failed counts, and full `migrations` array. Output structure: `data/overhead-benchmark/run_YYYYMMDD_HHMMSS/{overhead_raw.csv,overhead_metadata.json}`.

**Error handling:** Broad `try/except Exception` around each migration iteration. On failure: writes a failure row with empty timing fields and `success=false`, then continues to next migration. Never crashes the main loop.

### Task 2: CSV Schema Validator (`test_csv_schema.py`, 178 lines)

Four offline validation tests following the `test_hardware.py` pattern exactly (plain functions, no pytest, `__main__` runner):

- `test_csv_has_required_fields` — checks all 12 CSV columns present in header
- `test_total_ms_equals_sum_of_phases` — for successful rows, `total_ms == checkpoint_ms + transfer_ms + restore_ms` (tolerance 0.1 ms)
- `test_valid_workload_names` — workload column contains only `sysbench_cpu`, `sysbench_memory`, `memcount`
- `test_valid_regions` — source/target regions are valid NE/TEN/CENT and not equal

Self-test mode (no CLI argument): generates a 3-row sample CSV with 2 successful and 1 failure row, runs all tests against it, then deletes the sample file. All 4 tests pass in self-test mode.

## Deviations from Plan

None — plan executed exactly as written.

## Known Stubs

None — harness drives real REST API calls and real kubectl operations. All timing collection paths are wired to the instrumented `live_migration.py` from plan 02-01.

## Threat Flags

No new threat surface beyond what was documented in the plan's threat model:
- T-02-04 (YAML nodeSelector replacement): Only replaces `kind-worker` with known constants from `REGION_TO_NODE` dict — no user input injected into kubectl commands
- T-02-05 (CSV/JSON output): Output contains no secrets, only benchmark metrics
- T-02-06 (54 sequential migrations): Cleanup between migrations prevents resource accumulation; signal handler allows safe early termination

## Self-Check: PASSED

- `src/tests/overhead-benchmark/run_overhead_benchmark.py` exists (562 lines >= 200 minimum)
- `src/tests/overhead-benchmark/test_csv_schema.py` exists (178 lines >= 40 minimum)
- Commit eb37002 verified in git log (Task 1)
- Commit d0e2889 verified in git log (Task 2)
- AST parse check passes: `python3 -c "import ast; ast.parse(open(...).read())"` exits 0
- Schema test self-test passes: `python3 test_csv_schema.py` exits 0 with "All 4 schema tests passed"
- `requests.post` call targeting `/live-migrate` confirmed present
- `--since-time` log filtering confirmed present
- CSV append mode (`"a"`) confirmed present
- `overhead_metadata.json` write confirmed present
