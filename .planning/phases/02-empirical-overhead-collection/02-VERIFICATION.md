---
phase: 02-empirical-overhead-collection
verified: 2026-04-20T03:40:39Z
status: gaps_found
score: 2/3
overrides_applied: 0
gaps:
  - truth: "Raw measurement data is committed to data/ and reviewable without re-running the cluster"
    status: failed
    reason: "data/overhead-benchmark/ directory exists on disk with 3 completed runs (including 54-migration run_20260420_030700 with all charts) but is entirely untracked by git — no commit has ever added any file under data/overhead-benchmark/"
    artifacts:
      - path: "data/overhead-benchmark/run_20260420_030700/overhead_raw.csv"
        issue: "File exists on disk (54 rows, all successful) but untracked — git ls-files shows no overhead-benchmark files"
      - path: "data/overhead-benchmark/run_20260420_030700/overhead_metadata.json"
        issue: "File exists on disk but untracked"
      - path: "data/overhead-benchmark/run_20260420_030700/stacked_bar_overhead.png"
        issue: "File exists on disk but untracked"
      - path: "data/overhead-benchmark/run_20260420_030700/boxplot_distributions.png"
        issue: "File exists on disk but untracked"
      - path: "data/overhead-benchmark/run_20260420_030700/summary_stats.csv"
        issue: "File exists on disk but untracked"
    missing:
      - "Run: git add data/overhead-benchmark/run_20260420_030700/ && git commit -m 'data(02): commit empirical overhead benchmark results (54 migrations, 3 workloads)'"
human_verification:
  - test: "Review generated charts for thesis quality"
    expected: "Stacked bar chart clearly shows checkpoint/transfer/restore proportions per migration with labeled axes. Box plots show plausible distribution whiskers with no obvious artifacts. Summary stats table has accurate mean/median/std values appropriate for CRIU on KIND."
    why_human: "Visual quality and chart adequacy for thesis presentation cannot be assessed programmatically. Plan 02-03 Task 2 explicitly requires human sign-off on chart quality before this plan is complete."
---

# Phase 02: Empirical Overhead Collection — Verification Report

**Phase Goal:** Real checkpoint/transfer/restore timing data exists from 10+ live migrations so estimation functions have empirical grounding
**Verified:** 2026-04-20T03:40:39Z
**Status:** gaps_found
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths (from ROADMAP.md Success Criteria)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | At least 10 live migrations executed and timed with structured CSV/JSON output recording checkpoint, transfer, restore durations | VERIFIED | `data/overhead-benchmark/run_20260420_030700/overhead_raw.csv` — 54 rows, all `success=="success"`, with `checkpoint_ms`, `transfer_ms`, `restore_ms`, `total_ms` fields. Harness ran full 3-workload x 6-region-pair x 3-rep matrix. |
| 2 | Migration cost component breakdown (checkpoint vs transfer vs restore) is visualized and documented | VERIFIED | `data/overhead-benchmark/run_20260420_030700/` contains `stacked_bar_overhead.png`, `boxplot_distributions.png`, and `summary_stats.csv`. `graph_overhead.py --validate` exits 0. Running `graph_overhead.py run_20260420_030700` produces all 3 output types against real data. |
| 3 | Raw measurement data is committed to `data/` and reviewable without re-running the cluster | FAILED | `data/overhead-benchmark/` is entirely untracked. `git status` shows `?? data/overhead-benchmark/` and `git ls-files data/` contains zero overhead-benchmark entries. Data exists on disk but is not accessible to anyone cloning the repository. |

**Score:** 2/3 truths verified

### Plan Must-Haves (from PLAN frontmatter across plans 01, 02, 03)

#### Plan 02-01 Must-Haves

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Each live migration emits three structured JSON timing log lines (checkpoint_complete, transfer_complete, restore_complete) with duration_ms via the existing logger | VERIFIED | `live_migration.py` contains exactly 3 event types, 6 `time.perf_counter()` calls, 3 `json.dumps` calls, all 3 duration_ms entries. AST parse clean. |
| 2 | Three workload pod YAML templates exist and can be applied to any KIND worker node via nodeSelector | VERIFIED | All 3 files exist. Content confirmed: `sysbench cpu`, `sysbench memory`, `bytearray` commands. All have `kubernetes.io/hostname` nodeSelector, `namespace: test-namespace`, `restartPolicy: Never`, `privileged: true`, `CHECKPOINT_RESTORE` capability, `checkpoint-volume` hostPath. |

#### Plan 02-02 Must-Haves

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Benchmark harness drives migrations through /live-migrate REST API and collects per-phase timing from kubectl logs | VERIFIED | `run_overhead_benchmark.py` (561 lines) contains `requests.post`, `live-migrate`, `kubectl logs`, `--since=60s` log extraction. All 54 migrations in run_3 produced timing data. |
| 2 | Each migration produces one CSV row with checkpoint_ms, transfer_ms, restore_ms, total_ms, workload, source_region, target_region, repetition | VERIFIED | CSV schema confirmed: all 12 fields present. `test_csv_schema.py` passes all 4 tests against real run data. |
| 3 | Harness iterates all 54 combinations (3 workloads x 6 region pairs x 3 repetitions) | VERIFIED | `REGION_PAIRS` has 6 entries, `WORKLOADS` has 3 entries, default `--repetitions 3`. Run_3 CSV has exactly 54 rows. |
| 4 | CSV rows written incrementally (append mode) so partial runs are recoverable | VERIFIED | Code confirmed: `open(csv_path, "a")` with `DictWriter`. |
| 5 | JSON metadata file captures run configuration alongside all migration records | VERIFIED | `overhead_metadata.json` present with `run_id`, `config`, `total_migrations`, `migrations` array. |

#### Plan 02-03 Must-Haves

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Visualization script reads overhead_raw.csv and produces three chart types: stacked bar chart, box plots, and summary statistics table | VERIFIED | `graph_overhead.py` (390 lines) produces all 3 types. `--validate` exits 0. Real-data run produces `stacked_bar_overhead.png`, `boxplot_distributions.png`, `summary_stats.csv`. |
| 2 | Stacked bar chart shows checkpoint/transfer/restore proportions per migration | VERIFIED | `ax.bar(..., bottom=...)` pattern confirmed with colors `#2196F3`, `#FF9800`, `#4CAF50`. |
| 3 | Box plots show timing distributions grouped by workload and/or region pair | VERIFIED | `ax.boxplot` with `patch_artist=True` confirmed. Subplots per workload. |
| 4 | Summary statistics table includes mean, median, std, min, max, p25, p75 per (workload x phase) | VERIFIED | `np.mean`, `np.median`, `np.std`, `np.percentile(arr, 25/75)` all present. `summary_stats.csv` has correct columns. |
| 5 | Human verifies that generated charts are thesis-quality | NEEDS HUMAN | Plan 02-03 Task 2 is a blocking human-verify gate. The SUMMARY notes "awaiting human review." |

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `src/controller/migrator/live_migration.py` | Timing instrumentation with time.perf_counter | VERIFIED | 6 perf_counter calls, 3 json.dumps events, AST clean |
| `src/tests/overhead-benchmark/workloads/sysbench-cpu.yml` | Sysbench CPU workload pod template | VERIFIED | Contains `sysbench cpu`, correct securityContext |
| `src/tests/overhead-benchmark/workloads/sysbench-memory.yml` | Sysbench memory workload pod template | VERIFIED | Contains `sysbench memory`, correct securityContext |
| `src/tests/overhead-benchmark/workloads/memcount.yml` | Custom memory-counter workload (64 MB after fix) | VERIFIED | Contains `bytearray`, 128Mi/256Mi memory limits |
| `src/tests/overhead-benchmark/run_overhead_benchmark.py` | Main benchmark harness (min 200 lines) | VERIFIED | 561 lines, all key components present |
| `src/tests/overhead-benchmark/test_csv_schema.py` | CSV schema validation (min 40 lines) | VERIFIED | 178 lines, all 4 tests pass in self-test mode |
| `src/tests/overhead-benchmark/graph_overhead.py` | Visualization script (min 150 lines) | VERIFIED | 390 lines, --validate exits 0 |
| `data/overhead-benchmark/run_*/overhead_raw.csv` | Committed benchmark data | FAILED | Data exists on disk (3 runs, best has 54 rows) but entirely untracked in git |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `live_migration.py` | kubectl logs | `logger.info(json.dumps({event, duration_ms, ...}))` | VERIFIED | Pattern `json.dumps.*event.*duration_ms` confirmed at lines 1449-1453, 1467-1471, 1488-1492 |
| `run_overhead_benchmark.py` | `http://localhost:8000/live-migrate` | `requests.post` with MigrateRequest JSON body | VERIFIED | `requests.post` and `live-migrate` both present |
| `run_overhead_benchmark.py` | kubectl logs | `subprocess via kubectl()` with `--since=60s` | VERIFIED (deviation) | Uses `--since=60s` instead of planned `--since-time` due to clock skew between host and KIND nodes — documented in fix commit cd6dbfd |
| `graph_overhead.py` | `data/overhead-benchmark/*/overhead_raw.csv` | `csv.DictReader` loading | VERIFIED | `DictReader` present; confirmed working against real run data |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|---------------|--------|--------------------|--------|
| `graph_overhead.py` | `rows` (list of migration dicts) | `load_overhead_csv(csv_path)` reads real CSV | Yes — confirmed: 54 rows from run_3, all with numeric timing values | FLOWING |
| `run_overhead_benchmark.py` | `timings` dict | `extract_timing_from_logs()` parses kubectl logs after real CRIU migrations | Yes — confirmed: 54 successful rows with real checkpoint/transfer/restore values in data | FLOWING |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| CSV schema test passes self-test | `python3 test_csv_schema.py` | All 4 schema tests passed | PASS |
| Visualization --validate mode | `python3 graph_overhead.py --validate` | Validation passed; 2 PNGs + 1 CSV generated | PASS |
| Visualization on real data | `python3 graph_overhead.py data/overhead-benchmark/run_20260420_030700` | 54 records loaded; 2 PNGs + 1 CSV produced with real timing values | PASS |
| Timing instrumentation AST parse | `python3 -c "import ast; ast.parse(open('live_migration.py').read())"` | OK | PASS |

### Requirements Coverage

| Requirement | Source Plans | Description | Status | Evidence |
|-------------|-------------|-------------|--------|---------|
| EVAL-05 | 02-01, 02-02 | Empirical overhead measurements from 10+ live migrations for model calibration | SATISFIED | 54 migrations executed, timed, and stored in CSV with per-phase durations |
| EVAL-07 | 02-01, 02-03 | Migration cost component breakdown (checkpoint vs transfer vs restore) | SATISFIED | `graph_overhead.py` produces stacked bars, box plots, and summary statistics table showing all three components |

### Anti-Patterns Found

| File | Location | Pattern | Severity | Impact |
|------|----------|---------|----------|--------|
| `run_overhead_benchmark.py` | Lines 333, 525 | `success == "true"` but CSV stores `"success"` — metadata `successful` count always 0 | Warning | Misleading metadata JSON (always shows `"successful": 0`) but CSV timing data is accurate; Phase 3 calibration uses raw timing values not this count |
| `workloads/sysbench-cpu.yml`, `sysbench-memory.yml`, `memcount.yml` | `volumes` section | `hostPath.type: Directory` — pod fails to schedule if `/tmp/checkpoints` doesn't exist on node | Warning | Mitigated by cleanup function pre-creating dir; run_3 produced all 54 rows, confirming it didn't block data collection in practice |

No blocker anti-patterns were found. Timing data in the CSV files is numerically correct.

### Human Verification Required

#### 1. Chart Quality Review for Thesis Presentation

**Test:** Open the following files from `data/overhead-benchmark/run_20260420_030700/` and review visually:
  - `stacked_bar_overhead.png` — expect colored stacked bars (blue/orange/green) per migration with labeled axes
  - `boxplot_distributions.png` — expect box plots with whiskers for Checkpoint/Transfer/Restore phases per workload type
  - (Optionally) run `python3 src/tests/overhead-benchmark/graph_overhead.py data/overhead-benchmark/run_20260420_030700` to regenerate if needed

**Expected:** Charts are clear, axes are labeled, legends are legible, figure sizes are appropriate for thesis inclusion. Summary statistics table (printed to stdout) shows plausible values: checkpoint ~700-1200ms, transfer ~600-900ms, restore ~400-650ms for KIND on a local machine.

**Why human:** Visual chart quality and thesis-adequacy cannot be assessed programmatically. Plan 02-03 Task 2 is a `checkpoint:human-verify` gate that requires explicit sign-off.

### Gaps Summary

**One gap blocks SC#3:** The benchmark data exists on disk in `data/overhead-benchmark/` (3 run directories, including a complete 54-migration run with visualization charts) but has never been committed to git. The ROADMAP requires data to be "committed to `data/` and reviewable without re-running the cluster." This fails — someone cloning the repo sees no benchmark data at all.

**Fix is a single commit:**
```
git add data/overhead-benchmark/run_20260420_030700/
git commit -m "data(02): commit empirical overhead benchmark results (54 migrations, 3 workloads x 6 pairs x 3 reps)"
```

The two earlier partial runs (`run_20260420_000557` with 35 successes and `run_20260420_030456` with 5 rows) need not be committed — committing only the complete run_3 satisfies SC#3. The visualization charts in run_3 simultaneously satisfy SC#2 once committed.

---

_Verified: 2026-04-20T03:40:39Z_
_Verifier: Claude (gsd-verifier)_
