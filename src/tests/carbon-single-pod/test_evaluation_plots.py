#!/usr/bin/env python3
"""
Tests for evaluation_plots.py — Phase 4 plotter.

RED tests (written before implementation) covering the behavioral contracts
in 04-04-PLAN.md.
"""

import csv
import os
import sys
import tempfile
from pathlib import Path

# Add the test directory to path so we can import evaluation_plots.
sys.path.insert(0, str(Path(__file__).parent))


def test_importable_and_callables():
    """Test 1: All required callables exist."""
    import evaluation_plots  # noqa: F401  (will fail until created)
    assert callable(evaluation_plots.plot_savings_comparison)
    assert callable(evaluation_plots.plot_ablation)
    assert callable(evaluation_plots.plot_horizon)
    assert callable(evaluation_plots.load_results)
    assert callable(evaluation_plots.main)


def test_constants_match_research_md():
    """Test 5: POLICY_COLORS[6] == '#4CAF50', ABLATION_AXES[0] == (0, 0, 0)."""
    import evaluation_plots
    assert evaluation_plots.POLICY_COLORS[6] == "#4CAF50", (
        f"Expected #4CAF50, got {evaluation_plots.POLICY_COLORS[6]}")
    assert evaluation_plots.ABLATION_AXES[0] == (0, 0, 0), (
        f"Expected (0, 0, 0), got {evaluation_plots.ABLATION_AXES[0]}")
    assert evaluation_plots.HORIZON_VALUES == (1, 2, 4, 8, 12, 24, 48), (
        f"HORIZON_VALUES mismatch: {evaluation_plots.HORIZON_VALUES}")


def test_no_impl_imports():
    """Test 7: File has no imports from evaluate_policies, _simulation_core, etc."""
    src = Path(__file__).parent / "evaluation_plots.py"
    if not src.exists():
        raise AssertionError("evaluation_plots.py does not exist yet")
    with open(src) as f:
        lines = f.readlines()
    for line in lines:
        if line.strip().startswith("#"):
            continue
        for forbidden in ("evaluate_policies", "_simulation_core", "heuristics", "controller"):
            if f"from {forbidden}" in line or f"import {forbidden}" in line:
                raise AssertionError(
                    f"Forbidden import from '{forbidden}' found in: {line.strip()}")


def test_dpi_bbox_in_source():
    """Test 6: All three plot helpers use dpi=150 and bbox_inches='tight'."""
    src = Path(__file__).parent / "evaluation_plots.py"
    if not src.exists():
        raise AssertionError("evaluation_plots.py does not exist yet")
    with open(src) as f:
        content = f.read()
    count = content.count('dpi=150, bbox_inches="tight"')
    assert count >= 3, f"Expected >=3 savefig calls with dpi=150, bbox_inches='tight', found {count}"


def _make_results_csv(tmp_dir, rows):
    """Write a minimal results.csv for smoke testing."""
    path = Path(tmp_dir) / "results.csv"
    fields = [
        "policy", "source_region", "start_ts", "start_datetime",
        "hw_weighting", "overhead_cost", "deadline_gate",
        "ablation_id", "lookahead_hours",
        "app_size_mb", "expected_completion_min", "deadline_multiplier",
        "total_carbon_gco2", "baseline_carbon_gco2", "savings_pct",
        "migration_count", "completed_hours", "sweep_kind",
    ]
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for row in rows:
            w.writerow(row)
    return path


def _base_row(**kwargs):
    row = {
        "policy": "6", "source_region": "NE", "start_ts": "1577836800",
        "start_datetime": "2020-01-01T00:00:00+00:00",
        "hw_weighting": "False", "overhead_cost": "False", "deadline_gate": "False",
        "ablation_id": "HW0_OH0_DL0", "lookahead_hours": "24",
        "app_size_mb": "64.0", "expected_completion_min": "2880",
        "deadline_multiplier": "1.5",
        "total_carbon_gco2": "50000.0", "baseline_carbon_gco2": "60000.0",
        "savings_pct": "16.67",
        "migration_count": "2", "completed_hours": "48",
        "sweep_kind": "main",
    }
    row.update(kwargs)
    return row


def test_comparison_plot_produces_png():
    """Test 3 partial: --kind comparison produces comparison.png."""
    import matplotlib
    matplotlib.use("Agg")  # non-interactive backend
    import evaluation_plots

    with tempfile.TemporaryDirectory() as tmp:
        rows = [_base_row(policy=str(p), sweep_kind="main") for p in range(1, 7)]
        csv_path = _make_results_csv(tmp, rows)
        out_path = Path(tmp) / "comparison.png"
        evaluation_plots.plot_savings_comparison(csv_path, out_path)
        assert out_path.exists(), "comparison.png was not created"


def test_ablation_plot_produces_png():
    """Ablation plot produces ablation.png when ablation rows present."""
    import matplotlib
    matplotlib.use("Agg")
    import evaluation_plots

    with tempfile.TemporaryDirectory() as tmp:
        # 8 ablation cells
        rows = []
        for hw in (0, 1):
            for oh in (0, 1):
                for dl in (0, 1):
                    rows.append(_base_row(
                        sweep_kind="ablation",
                        hw_weighting=str(bool(hw)),
                        overhead_cost=str(bool(oh)),
                        deadline_gate=str(bool(dl)),
                        ablation_id=f"HW{hw}_OH{oh}_DL{dl}",
                    ))
        csv_path = _make_results_csv(tmp, rows)
        out_path = Path(tmp) / "ablation.png"
        evaluation_plots.plot_ablation(csv_path, out_path)
        assert out_path.exists(), "ablation.png was not created"


def test_horizon_plot_produces_png():
    """Horizon plot produces horizon.png when horizon rows present."""
    import matplotlib
    matplotlib.use("Agg")
    import evaluation_plots

    with tempfile.TemporaryDirectory() as tmp:
        rows = []
        # Policy 6 horizon sweep
        for lh in (1, 2, 4, 8, 12, 24, 48):
            rows.append(_base_row(
                sweep_kind="horizon", policy="6", lookahead_hours=str(lh),
            ))
        # Policy 1-5 baselines (empty lookahead_hours)
        for p in range(1, 6):
            rows.append(_base_row(
                sweep_kind="horizon", policy=str(p), lookahead_hours="",
                savings_pct=str(p * 2.0),
            ))
        csv_path = _make_results_csv(tmp, rows)
        out_path = Path(tmp) / "horizon.png"
        evaluation_plots.plot_horizon(csv_path, out_path)
        assert out_path.exists(), "horizon.png was not created"


def test_missing_ablation_rows_no_crash():
    """Test 4: Empty ablation input logs warning to stderr and does not raise."""
    import io
    import matplotlib
    matplotlib.use("Agg")
    import evaluation_plots

    with tempfile.TemporaryDirectory() as tmp:
        # Only main rows, no ablation rows
        rows = [_base_row(policy="1", sweep_kind="main")]
        csv_path = _make_results_csv(tmp, rows)
        out_path = Path(tmp) / "ablation.png"

        old_stderr = sys.stderr
        sys.stderr = io.StringIO()
        try:
            evaluation_plots.plot_ablation(csv_path, out_path)
            stderr_output = sys.stderr.getvalue()
        finally:
            sys.stderr = old_stderr

        assert not out_path.exists(), "ablation.png should NOT be created for empty input"
        assert "No ablation rows" in stderr_output, (
            f"Expected '[PLOT] No ablation rows' warning in stderr, got: {stderr_output!r}")


def test_load_results_filter():
    """load_results returns filtered rows by sweep_kind."""
    import evaluation_plots

    with tempfile.TemporaryDirectory() as tmp:
        rows = [
            _base_row(sweep_kind="main"),
            _base_row(sweep_kind="ablation"),
            _base_row(sweep_kind="horizon"),
        ]
        csv_path = _make_results_csv(tmp, rows)

        main_rows = evaluation_plots.load_results(csv_path, sweep_kind="main")
        assert len(main_rows) == 1
        assert main_rows[0]["sweep_kind"] == "main"

        all_rows = evaluation_plots.load_results(csv_path)
        assert len(all_rows) == 3


if __name__ == "__main__":
    # Minimal runner — project has no pytest installed
    import traceback

    tests = [
        test_importable_and_callables,
        test_constants_match_research_md,
        test_no_impl_imports,
        test_dpi_bbox_in_source,
        test_comparison_plot_produces_png,
        test_ablation_plot_produces_png,
        test_horizon_plot_produces_png,
        test_missing_ablation_rows_no_crash,
        test_load_results_filter,
    ]

    passed = 0
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  PASS: {t.__name__}")
            passed += 1
        except Exception as exc:
            print(f"  FAIL: {t.__name__}: {exc}")
            traceback.print_exc()
            failed += 1

    print(f"\nResults: {passed} passed, {failed} failed, {passed + failed} total")
    sys.exit(0 if failed == 0 else 1)
