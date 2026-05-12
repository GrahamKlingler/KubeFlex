#!/usr/bin/env python3
"""Gantt-style per-policy runtime-breakdown plotter (quick task 260512-j87).

Complementary view to ``sweep_overhead_crossover.py``: instead of aggregating
many runs into mean-carbon-vs-overhead curves, this script zooms into specific
48-hour simulation traces and (in Task 2 of the plan) visualizes — per policy —
what the pod is doing at each hour of the simulation:

  - running on the BANC grid (one color)
  - running on the CISO grid (another color)
  - in the middle of a migration (split into ckpt / send / restore phases)

This file currently contains the Task 1 data-producing core (no matplotlib
imports yet): ``simulate_with_decisions`` and ``synthesize_phase_durations``.
Task 2 adds the per-cell plotter, the CLI, and the runs_summary.csv writer.

Design notes:

  - DO NOT modify ``_simulation_core.py``. We capture per-hour migration
    decisions via the LOCKED wrapper approach: monkey-patch
    ``_simulation_core._simulate_policy_decision`` inside a ``try/finally``
    block for the duration of one ``simulate_one_run`` call. This is the same
    technique used by ``sweep_overhead_crossover.scaled_overhead``.

  - Phase split synthesis runs OUTSIDE the simulation. We use the *original*
    (unpatched) ``heuristics.overhead.{ckpt,send,restore}_overhead`` helpers
    and scale their (ckpt:send:restore) ratio proportionally to match the
    simulated overhead (e.g. 30 min). We do NOT import / use
    ``sweep_overhead_crossover.scaled_overhead`` because that patches Policy
    6's *internal* estimator and we do not want to affect policy decisions
    here — we're only visualizing.

  - Carbon-accounting note: for sub-60-min overhead (cooldown=0) the sim's
    minute-granular lump-sum source charge at the decision hour is consistent
    with the visualized "30 min of the 60-min hour is migration phases on
    source" model. For >60-min overhead the visualization extrapolates phase
    durations across hour boundaries while the sim still charges only at the
    decision hour's source intensity. The locked overhead here is 30 min so
    we do not exercise that regime; the plot caption notes the disclaimer.
"""

import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

# Project import shim (mirror sweep_overhead_crossover.py lines 99-102 so we
# can import the same controller-package modules without installing them).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "controller"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _simulation_core import RunConfig, simulate_one_run  # noqa: E402
import _simulation_core as sc  # noqa: E402
from evaluate_policies import (  # noqa: E402
    DEFAULT_REGIONS_TREE_DIR,
    build_intensity_lookup_from_regions_tree,
)
from heuristics.hardware import HW_TABLE  # noqa: E402
from heuristics.overhead import (  # noqa: E402
    ckpt_overhead,
    send_overhead,
    restore_overhead,
)
from sweep_overhead_crossover import (  # noqa: E402
    ANCHOR_APP_SIZE_MB,
    _build_two_grid_lookup,
)


# ── Constants (LOCKED by CONTEXT.md) ──────────────────────────────────

# 4 seasonal anchors (one per quarter) at 00:00 UTC, in 2020.
SEASONAL_STARTS_2020: Tuple[int, ...] = tuple(
    int(datetime(2020, m, d, tzinfo=timezone.utc).timestamp())
    for m, d in ((1, 16), (4, 16), (7, 17), (10, 16))
)

# Single overhead value mid-range; sub-hour so phase breakdown is interesting.
OVERHEAD_MIN_DEFAULT: int = 30


# ── Task 1: Data-producing core ──────────────────────────────────────

def simulate_with_decisions(intensity_lookup, cfg: RunConfig) -> Dict[str, Any]:
    """Run ``simulate_one_run`` while capturing per-hour migration decisions.

    Wraps ``_simulation_core._simulate_policy_decision`` via module-attribute
    monkey-patch inside a ``try/finally`` so the original function is restored
    even if the simulation raises. On every accepted migration decision
    (``should_migrate=True`` AND ``target_grid is not None``) we record::

        {"hour": int(elapsed_hours),
         "source_grid": current_grid,   # grid pod was on BEFORE the migration
         "target_grid": target_grid}

    Self-consistency assertions guarantee the captured event list aligns with
    the sim's ``migration_count`` and ``dest_grids_visited`` fields. A
    mismatch would indicate sim-core drift and is surfaced loudly.

    Args:
        intensity_lookup: ``{(grid, ts): intensity}`` (typically a two-grid
            subset produced by ``_build_two_grid_lookup``).
        cfg: ``RunConfig`` for the single simulation.

    Returns:
        The unmodified ``simulate_one_run`` return dict, plus a new key
        ``migration_events: List[Dict[str, Any]]``.
    """
    events: List[Dict[str, Any]] = []
    orig = sc._simulate_policy_decision

    def wrapped(
        policy_obj,
        intensity_lookup_,
        grids,
        current_grid,
        sim_timestamp,
        expected_duration_hours=1,
        elapsed_hours=0.0,
        **kwargs,
    ):
        decision = orig(
            policy_obj,
            intensity_lookup_,
            grids,
            current_grid,
            sim_timestamp,
            expected_duration_hours,
            elapsed_hours=elapsed_hours,
            **kwargs,
        )
        should_migrate, target = decision
        if should_migrate and target:
            events.append({
                "hour": int(elapsed_hours),
                "source_grid": current_grid,
                "target_grid": target,
            })
        return decision

    sc._simulate_policy_decision = wrapped
    try:
        out = simulate_one_run(intensity_lookup, cfg)
    finally:
        sc._simulate_policy_decision = orig

    # Self-consistency: events list MUST align with the sim's own bookkeeping.
    # If either assertion fires, sim-core drift has occurred — surface loudly.
    assert len(events) == out["migration_count"], (
        f"[BREAKDOWN] events={len(events)} != migration_count="
        f"{out['migration_count']} for cfg={cfg}"
    )
    assert [e["target_grid"] for e in events] == list(out["dest_grids_visited"]), (
        f"[BREAKDOWN] events targets={[e['target_grid'] for e in events]} "
        f"!= dest_grids_visited={out['dest_grids_visited']} for cfg={cfg}"
    )

    out = dict(out)  # avoid mutating the sim's return value
    out["migration_events"] = events
    return out


def synthesize_phase_durations(
    src_hw,
    dst_hw,
    app_size_mb: float,
    total_min: float,
) -> Tuple[float, float, float]:
    """Return ``(ckpt_min, send_min, restore_min)`` summing to ``total_min``.

    Uses the *original* (unpatched) helpers from ``heuristics.overhead`` to
    compute baseline ckpt:send:restore ratios at ``app_size_mb`` for the given
    source/destination hardware, then scales proportionally so the three
    phases sum to exactly ``total_min``.

    Args:
        src_hw: ``HardwareSpec`` for the migration source grid.
        dst_hw: ``HardwareSpec`` for the migration destination grid.
        app_size_mb: Application checkpoint size in MB.
        total_min: Target total migration duration in minutes (e.g. 30).

    Returns:
        ``(ckpt_min, send_min, restore_min)`` — three positive floats summing
        to ``total_min`` (within fp tolerance). On degenerate input
        (``total_base <= 0``) returns equal thirds as a safe fallback.
    """
    ckpt_base_s = ckpt_overhead(app_size_mb, src_hw)
    send_base_s = send_overhead(src_hw, dst_hw, app_size_mb)
    rest_base_s = restore_overhead(app_size_mb, dst_hw)
    total_base_s = ckpt_base_s + send_base_s + rest_base_s
    if total_base_s <= 0.0:
        # Degenerate: split evenly so caller still sees positive phases.
        third = total_min / 3.0
        return (third, third, third)
    # Scale (baseline-seconds) -> (target-minutes): the ratio of seconds is
    # preserved, total is forced to ``total_min``.
    scale = total_min / total_base_s
    return (
        ckpt_base_s * scale,
        send_base_s * scale,
        rest_base_s * scale,
    )


# ── Smoke test (Task 1 acceptance) ───────────────────────────────────

def _smoke_test() -> None:
    """Task 1 smoke test: exercise simulate_with_decisions + synthesize_phase_durations.

    Run a single ``simulate_with_decisions`` for (start_ts=Jan 16, source=CISO,
    policy_id=2) with the BANC↔CISO two-grid lookup and assert the documented
    invariants. Print the events list and totals so the developer can
    eyeball-verify before Task 2.
    """
    print("[SMOKE] Loading full BANC+CISO intensity lookup...")
    full = build_intensity_lookup_from_regions_tree(
        Path(DEFAULT_REGIONS_TREE_DIR), allowed_grids=("BANC", "CISO"),
    )
    pair = _build_two_grid_lookup(full, "CISO", "BANC")
    cfg = RunConfig(
        start_ts=SEASONAL_STARTS_2020[0],  # 2020-01-16 00:00 UTC
        source_grid="CISO",
        policy_id=2,
        app_size_mb=ANCHOR_APP_SIZE_MB,
        expected_migration_min=OVERHEAD_MIN_DEFAULT,
        use_hw=True,
        sweep_kind="runtime_breakdown_smoke",
    )
    print(f"[SMOKE] simulate_with_decisions(cfg={cfg})")
    out = simulate_with_decisions(pair, cfg)

    assert out["migration_count"] > 0, (
        "[SMOKE] P2 CISO→BANC at Jan 16 should produce migrations; "
        f"got migration_count={out['migration_count']}"
    )
    assert len(out["migration_events"]) == out["migration_count"]
    for e in out["migration_events"]:
        assert e["target_grid"] in {"BANC", "CISO"}, (
            f"[SMOKE] bad target_grid in event {e}"
        )
        assert 0 <= e["hour"] < 48, f"[SMOKE] hour out of range in event {e}"

    ck, sn, rs = synthesize_phase_durations(
        HW_TABLE["CISO"], HW_TABLE["BANC"],
        ANCHOR_APP_SIZE_MB, float(OVERHEAD_MIN_DEFAULT),
    )
    assert ck > 0 and sn > 0 and rs > 0, (
        f"[SMOKE] phases must all be positive; got ({ck}, {sn}, {rs})"
    )
    assert abs((ck + sn + rs) - OVERHEAD_MIN_DEFAULT) < 1e-9, (
        f"[SMOKE] phases must sum to {OVERHEAD_MIN_DEFAULT}; "
        f"got ck={ck} sn={sn} rs={rs} sum={ck+sn+rs}"
    )

    print(f"[SMOKE] migration_count = {out['migration_count']}")
    print(f"[SMOKE] migration_events = {out['migration_events']}")
    print(f"[SMOKE] dest_grids_visited = {out['dest_grids_visited']}")
    print(f"[SMOKE] total_carbon_gco2 = {out['total_carbon_gco2']}")
    print(
        f"[SMOKE] phase_durations(CISO->BANC, 64MB, 30min): "
        f"ckpt={ck:.4f} min  send={sn:.4f} min  restore={rs:.4f} min  "
        f"sum={ck+sn+rs:.6f} min"
    )
    print("[SMOKE] all Task 1 assertions PASSED.")


if __name__ == "__main__":
    _smoke_test()
