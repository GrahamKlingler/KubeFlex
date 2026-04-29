---
phase: 04-evaluation-harness-simulation-results
plan: "04"
subsystem: evaluation-plotter
tags:
  - kubeflex
  - python
  - evaluation
  - plotting
  - matplotlib
dependency_graph:
  requires:
    - 04-03  # evaluate_policies.py produces results.csv with sweep_kind column
  provides:
    - evaluation_plots.py (Phase 4 plotter: comparison/ablation/horizon PNGs)
    - data/evaluation/run_<ts>/{comparison,ablation,horizon}.png
  affects:
    - Thesis figures — three publication-ready PNG files from simulation sweep data
tech_stack:
  added:
    - src/tests/carbon-single-pod/evaluation_plots.py (new plotter module, 258 lines)
  patterns:
    - csv.DictReader filtered by sweep_kind (PATTERNS.md "CSV reader pattern")
    - int(row[col] == "True") boolean parsing for stringified Python bool columns
    - matplotlib non-interactive Agg backend in tests
    - TDD: RED (test_evaluation_plots.py committed before implementation), then GREEN
key_files:
  created:
    - src/tests/carbon-single-pod/evaluation_plots.py
    - src/tests/carbon-single-pod/test_evaluation_plots.py
  modified: []
decisions:
  - "Docstring reworded from 'from evaluate_policies.py...' to avoid false positive in no-impl-import grep test — docstring text starting with 'from ' was being matched by test regex checking import statements"
  - "test_no_impl_imports refined to check only lines starting with 'import ' or 'from ' (actual Python import syntax) rather than all non-comment lines — prevents docstring content from tripping the guard"
metrics:
  duration: "~15 minutes"
  completed: "2026-04-29"
  tasks_completed: 1
  tasks_total: 1
  files_created: 2
  files_modified: 0
---

# Phase 04 Plan 04: Evaluation Plots Summary

Pure-transform `evaluation_plots.py` plotter reading `results.csv` from `evaluate_policies.py` and producing three thesis-grade PNG figures: `comparison.png` (per-policy savings boxplot), `ablation.png` (8-cell HEUR-10 heatmap), `horizon.png` (HEUR-11 line plot with Policy 1-5 baselines).

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 RED | Add failing tests for evaluation_plots.py | 2bec262 | src/tests/carbon-single-pod/test_evaluation_plots.py (new, 9 tests) |
| 1 GREEN | Implement evaluation_plots.py | 0289751 | src/tests/carbon-single-pod/evaluation_plots.py (new, 258 lines) |

## What Was Built

### `evaluation_plots.py` (new module, 258 lines)

- `load_results(path, sweep_kind=None)` — csv.DictReader-based loader returning list of string-valued dicts, optionally filtered by `sweep_kind`
- `plot_savings_comparison(results_csv, out_path)` — matplotlib boxplot for P1-P6, filtered to `sweep_kind='main'`, using POLICY_COLORS palette; VERBATIM from RESEARCH.md lines 699-727
- `plot_ablation(results_csv, out_path)` — 8-cell RdYlGn heatmap over ABLATION_AXES, mean savings_pct per (HW,OH,DL) cell; VERBATIM from RESEARCH.md lines 739-767
- `plot_horizon(results_csv, out_path)` — Policy 6 line plot with HORIZON_VALUES x-axis (log2 scale) plus Policy 1-5 axhline references; derived from D-15
- `main()` — argparse with `run_dir` positional + `--kind {comparison,ablation,horizon,all}` (default `all`); writes PNGs into `run_dir`

### Test suite (9 tests, all GREEN)

```
Results: 9 passed, 0 failed, 9 total
```

### Smoke run output

End-to-end smoke against `data/evaluation/run_20260429_111344/` produced:
- `data/evaluation/run_20260429_111344/comparison.png` (46 KB)
- `data/evaluation/run_20260429_111344/ablation.png` (33 KB)
- `data/evaluation/run_20260429_111344/horizon.png` (47 KB)

### Requirement fulfillment

- INFR-05 (visualization): evaluation_plots.py is the Phase 4 visualization tool
- EVAL-03 (comparison graphs): three thesis-grade figures produced from ~195 smoke-run simulation rows

## TDD Gate Compliance

RED gate commit: `2bec262 test(04-04): add failing tests for evaluation_plots.py`
GREEN gate commit: `0289751 feat(04-04): implement evaluation_plots.py — Phase 4 plotter`
Gate sequence validated.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Docstring content tripped the no-impl-import test**

- **Found during:** Task 1 GREEN phase first test run
- **Issue:** The module docstring contained `"from evaluate_policies.py, _simulation_core.py, or any policy class."` — a line starting with `from `. The `test_no_impl_imports` test checking for forbidden imports matched this docstring line even when filtering non-comment lines, because the test used `grep -v '^#'` semantics rather than targeting actual Python import syntax.
- **Fix:** (a) Reworded the docstring line in `evaluation_plots.py` to avoid starting with `from evaluate_policies`. (b) Refined `test_no_impl_imports` in the test file to only check lines where `stripped.startswith("import ")` or `stripped.startswith("from ")` — actual Python import statement syntax.
- **Files modified:** `src/tests/carbon-single-pod/evaluation_plots.py`, `src/tests/carbon-single-pod/test_evaluation_plots.py`
- **Commit:** 0289751 (same GREEN commit)

### Notes on VERBATIM compliance

The boxplot and heatmap helpers were copied verbatim from RESEARCH.md as specified. The `labels=` parameter in `ax.boxplot()` triggers a `MatplotlibDeprecationWarning` in matplotlib 3.9+ (renamed to `tick_labels`), but the parameter remains supported through matplotlib 3.11. Since the plan explicitly required VERBATIM copying and the behavior is correct, the deprecation warning is noted but not fixed.

## Known Stubs

None — all plots are wired to real `results.csv` data from `evaluate_policies.py` smoke output.

## Threat Surface Scan

No new network endpoints, auth paths, file access patterns, or schema changes. `evaluation_plots.py` is a pure local script: reads CSVs from `data/evaluation/run_<ts>/`, writes PNGs to the same directory. No external I/O, no HTTP, no K8s API calls.

T-04-11 mitigated: each plot helper checks for empty rows and emits `[PLOT] No <kind> rows found — skipping <name>.png` to stderr before returning without writing the file.
T-04-12 mitigated: `int(row["hw_weighting"] == "True")` canonical parser used throughout `plot_ablation`.

## Self-Check: PASSED

- `src/tests/carbon-single-pod/evaluation_plots.py` exists: FOUND
- `src/tests/carbon-single-pod/test_evaluation_plots.py` exists: FOUND
- Commit 2bec262 (RED) exists: FOUND
- Commit 0289751 (GREEN) exists: FOUND
- 9/9 tests pass: VERIFIED
- Smoke run produces all 3 PNG files: VERIFIED
- No impl imports (grep -v '^#' ... | grep -cE 'from ...'): VERIFIED = 0
- dpi=150, bbox_inches="tight" used >=3 times: VERIFIED = 3
- POLICY_COLORS[6] == "#4CAF50": VERIFIED
- ABLATION_AXES[0] == (0, 0, 0): VERIFIED
- HORIZON_VALUES == (1, 2, 4, 8, 12, 24, 48): VERIFIED
- Line count >= 200: VERIFIED = 258
