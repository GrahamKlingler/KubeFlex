#!/usr/bin/env python3
"""Unit tests for overhead benchmark CSV schema validation.

Validates that a benchmark output CSV (overhead_raw.csv) produced by
run_overhead_benchmark.py contains the correct columns and well-formed data.

Usage (self-test mode — no CSV argument required):
    python3 test_csv_schema.py

Usage (validate a real benchmark output):
    python3 test_csv_schema.py data/overhead-benchmark/run_20240101_120000/overhead_raw.csv
"""

import csv
import sys
from pathlib import Path


REQUIRED_FIELDS = {
    "run_id", "migration_num", "workload",
    "source_region", "target_region", "repetition",
    "checkpoint_ms", "transfer_ms", "restore_ms", "total_ms",
    "success", "timestamp_utc",
}

VALID_WORKLOADS = {"sysbench_cpu", "sysbench_memory", "memcount"}
VALID_REGIONS = {"NE", "TEN", "CENT"}


def test_csv_has_required_fields(csv_path):
    """Verify CSV header contains all required fields."""
    with open(csv_path) as f:
        reader = csv.DictReader(f)
        fields = set(reader.fieldnames or [])
    missing = REQUIRED_FIELDS - fields
    assert not missing, f"Missing fields: {missing}"
    print(f"  Header fields: {sorted(fields)}")


def test_total_ms_equals_sum_of_phases(csv_path):
    """For successful rows, total_ms should equal checkpoint_ms + transfer_ms + restore_ms."""
    with open(csv_path) as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader):
            if row["success"] != "true":
                continue
            # Skip rows with empty timing fields (partial failures)
            if not row["checkpoint_ms"] or not row["transfer_ms"] or not row["restore_ms"]:
                continue
            ckpt = float(row["checkpoint_ms"])
            xfer = float(row["transfer_ms"])
            rest = float(row["restore_ms"])
            total = float(row["total_ms"])
            expected = ckpt + xfer + rest
            assert abs(total - expected) < 0.1, (
                f"Row {i}: total_ms={total} != sum={expected} "
                f"(checkpoint={ckpt}, transfer={xfer}, restore={rest})"
            )


def test_valid_workload_names(csv_path):
    """Verify workload column contains only known workload names."""
    with open(csv_path) as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader):
            assert row["workload"] in VALID_WORKLOADS, (
                f"Row {i}: unknown workload '{row['workload']}'"
            )


def test_valid_regions(csv_path):
    """Verify source_region and target_region contain valid region names."""
    with open(csv_path) as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader):
            assert row["source_region"] in VALID_REGIONS, (
                f"Row {i}: invalid source_region '{row['source_region']}'"
            )
            assert row["target_region"] in VALID_REGIONS, (
                f"Row {i}: invalid target_region '{row['target_region']}'"
            )
            assert row["source_region"] != row["target_region"], (
                f"Row {i}: source and target region are the same ('{row['source_region']}')"
            )


def _write_sample_csv(path):
    """Write a minimal valid sample CSV for self-test mode."""
    import io

    # One successful row (all phases present) and one failure row (empty timings)
    sample_rows = [
        {
            "run_id": "20240101_120000",
            "migration_num": "1",
            "workload": "sysbench_cpu",
            "source_region": "NE",
            "target_region": "TEN",
            "repetition": "1",
            "checkpoint_ms": "4821.37",
            "transfer_ms": "1234.56",
            "restore_ms": "789.01",
            "total_ms": "6844.94",
            "success": "true",
            "timestamp_utc": "2024-01-01T12:00:05+00:00",
        },
        {
            "run_id": "20240101_120000",
            "migration_num": "2",
            "workload": "sysbench_memory",
            "source_region": "TEN",
            "target_region": "CENT",
            "repetition": "1",
            "checkpoint_ms": "3100.00",
            "transfer_ms": "900.00",
            "restore_ms": "600.00",
            "total_ms": "4600.00",
            "success": "true",
            "timestamp_utc": "2024-01-01T12:01:00+00:00",
        },
        {
            "run_id": "20240101_120000",
            "migration_num": "3",
            "workload": "memcount",
            "source_region": "CENT",
            "target_region": "NE",
            "repetition": "2",
            "checkpoint_ms": "",
            "transfer_ms": "",
            "restore_ms": "",
            "total_ms": "",
            "success": "false",
            "timestamp_utc": "2024-01-01T12:02:00+00:00",
        },
    ]

    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=sorted(REQUIRED_FIELDS))
        writer.writeheader()
        writer.writerows(sample_rows)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        # Self-test mode: generate a sample CSV and validate it
        sample_path = Path(__file__).parent / "_sample_test.csv"
        _write_sample_csv(sample_path)
        csv_path = sample_path
        cleanup = True
    else:
        csv_path = Path(sys.argv[1])
        cleanup = False

    if not csv_path.exists():
        print(f"ERROR: CSV file not found: {csv_path}")
        sys.exit(1)

    tests = [
        test_csv_has_required_fields,
        test_total_ms_equals_sum_of_phases,
        test_valid_workload_names,
        test_valid_regions,
    ]

    for test in tests:
        try:
            test(csv_path)
            print(f"PASS: {test.__name__}")
        except Exception as e:
            print(f"FAIL: {test.__name__} -- {e}")
            if cleanup and sample_path.exists():
                sample_path.unlink()
            sys.exit(1)

    print(f"\nAll {len(tests)} schema tests passed.")

    if cleanup and sample_path.exists():
        sample_path.unlink()
