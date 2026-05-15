#!/usr/bin/env python3
"""Unit tests for heuristics.sysbench (260515-jav).

Covers the empirical-perf loader API surface:
  - load_sysbench: only Succeeded records are returned; >=198 entries total
    across all hostnames (data census from CONTEXT.md).
  - perf_by_hostname: known-value spot-check (k8s-igrok-04 at threads=1).
  - perf_by_grid: aggregates CISO (positive median) and returns None for grids
    absent from sysbench data (BANC).
  - perf_ratio: silent 1.0 fallback when either endpoint is missing; rate-
    limited single-warning per (src,dst,by_grid) per process.

Mirrors the project's runner pattern (no pytest, hand-rolled tests list).
"""

import logging
import sys
from pathlib import Path

# Add controller package to import path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "controller"))

from heuristics.sysbench import (  # noqa: E402
    SysbenchPerf,
    load_sysbench,
    perf_by_hostname,
    perf_by_grid,
    perf_ratio,
)
import heuristics.sysbench as sysbench_mod  # noqa: E402


# ── Test functions ────────────────────────────────────────────────


def test_load_sysbench_returns_succeeded_only():
    """load_sysbench() returns >=198 successful records, no None events_per_second."""
    data = load_sysbench()
    assert isinstance(data, dict), f"Expected dict, got {type(data)}"
    total = sum(len(v) for v in data.values())
    assert total >= 198, (
        f"Expected >=198 successful sysbench records, got {total}"
    )
    # Every record must be a SysbenchPerf with a positive events_per_second
    for host, recs in data.items():
        for rec in recs:
            assert isinstance(rec, SysbenchPerf), (
                f"Expected SysbenchPerf, got {type(rec)} for host={host}"
            )
            assert rec.events_per_second is not None, (
                f"Record for {host} has None events_per_second (should be filtered)"
            )
            assert rec.events_per_second > 0, (
                f"Record for {host} has non-positive events_per_second={rec.events_per_second}"
            )


def test_perf_by_hostname_known_value():
    """perf_by_hostname('k8s-igrok-04...', 1) returns ~598.28 events/sec."""
    val = perf_by_hostname("k8s-igrok-04.calit2.optiputer.net", threads=1)
    assert val is not None, (
        "Expected non-None perf for k8s-igrok-04 at threads=1 "
        "(verified record 1 of sysbench_results.jsonl)"
    )
    assert abs(val - 598.28) < 5.0, (
        f"Expected ~598.28 events/sec for k8s-igrok-04 t=1, got {val}"
    )
    # Unknown hostname must return None
    assert perf_by_hostname("not-a-host.example", threads=1) is None, (
        "Expected None for unknown hostname"
    )


def test_perf_by_grid_ciso_positive_and_banc_none():
    """perf_by_grid('CISO',1) > 0 and perf_by_grid('BANC',1) is None."""
    ciso = perf_by_grid("CISO", threads=1)
    assert ciso is not None and ciso > 0, (
        f"Expected positive median for CISO at threads=1, got {ciso}"
    )
    banc = perf_by_grid("BANC", threads=1)
    assert banc is None, (
        f"Expected None for BANC (absent from sysbench), got {banc}"
    )


def test_perf_ratio_fallback_returns_one_and_warns_once():
    """perf_ratio with missing endpoint returns 1.0 and warns at most once."""
    # Reset the per-process rate-limit set so this test is deterministic
    # whether or not earlier tests already tripped the same key.
    sysbench_mod._FALLBACK_WARNED.clear()

    # Capture warnings on the sysbench module logger
    captured = []

    class _ListHandler(logging.Handler):
        def emit(self, record):  # noqa: D401
            captured.append(record)

    handler = _ListHandler(level=logging.WARNING)
    logger = logging.getLogger("heuristics.sysbench")
    prev_level = logger.level
    logger.addHandler(handler)
    logger.setLevel(logging.WARNING)
    try:
        r1 = perf_ratio("BANC", "AECI", by_grid=True)
        r2 = perf_ratio("BANC", "AECI", by_grid=True)
    finally:
        logger.removeHandler(handler)
        logger.setLevel(prev_level)

    assert r1 == 1.0, f"Expected 1.0 fallback for missing BANC, got {r1}"
    assert r2 == 1.0, f"Expected 1.0 fallback (2nd call), got {r2}"
    # Exactly one warning across both calls (rate-limited)
    warns = [rec for rec in captured if rec.levelno == logging.WARNING]
    assert len(warns) == 1, (
        f"Expected exactly one rate-limited warning for (BANC, AECI, True), got "
        f"{len(warns)}: {[r.getMessage() for r in warns]}"
    )

    # Sanity: real grid pair returns a non-1.0 ratio in (0.5, 2.0).
    sysbench_mod._FALLBACK_WARNED.clear()
    ratio = perf_ratio("CISO", "MISO", by_grid=True)
    assert 0.5 < ratio < 2.0, (
        f"CISO/MISO ratio should be a single-digit value in (0.5, 2.0); got {ratio}"
    )


# ── Runner ────────────────────────────────────────────────────────


def main():
    tests = [
        test_load_sysbench_returns_succeeded_only,
        test_perf_by_hostname_known_value,
        test_perf_by_grid_ciso_positive_and_banc_none,
        test_perf_ratio_fallback_returns_one_and_warns_once,
    ]
    passed = 0
    failed = 0
    print(f"Running {len(tests)} sysbench tests...")
    for test in tests:
        try:
            test()
            print(f"  PASS: {test.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"  FAIL: {test.__name__}: {e}")
            failed += 1
        except Exception as e:
            import traceback
            print(f"  ERROR: {test.__name__}: {e}")
            traceback.print_exc()
            failed += 1

    print()
    print(f"Results: {passed} passed, {failed} failed, {passed + failed} total")
    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
