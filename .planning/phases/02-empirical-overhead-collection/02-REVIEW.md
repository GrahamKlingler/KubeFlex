---
phase: 02-empirical-overhead-collection
reviewed: 2026-04-18T00:00:00Z
depth: standard
files_reviewed: 7
files_reviewed_list:
  - src/controller/migrator/live_migration.py
  - src/tests/overhead-benchmark/graph_overhead.py
  - src/tests/overhead-benchmark/run_overhead_benchmark.py
  - src/tests/overhead-benchmark/test_csv_schema.py
  - src/tests/overhead-benchmark/workloads/memcount.yml
  - src/tests/overhead-benchmark/workloads/sysbench-cpu.yml
  - src/tests/overhead-benchmark/workloads/sysbench-memory.yml
findings:
  critical: 0
  warning: 5
  info: 5
  total: 10
status: issues_found
---

# Phase 02: Code Review Report

**Reviewed:** 2026-04-18
**Depth:** standard
**Files Reviewed:** 7
**Status:** issues_found

## Summary

Reviewed the empirical overhead collection phase additions: the benchmark driver (`run_overhead_benchmark.py`), graph/stats script (`graph_overhead.py`), CSV schema test (`test_csv_schema.py`), three workload pod manifests, and the already-deployed `live_migration.py` migration engine.

The benchmark driver has a logic bug that causes the final successful-migration count in both the terminal summary and the metadata JSON to always report 0, even when migrations succeed. The workload pod manifests use `hostPath.type: Directory` which will fail pod scheduling on any node where `/tmp/checkpoints` does not already exist. A bare `except:` clause in `live_migration.py` can swallow `SystemExit` and `KeyboardInterrupt`. Additionally, the checkpoint transfer in `live_migration.py` uses `subprocess.run` without a timeout, meaning a large checkpoint could hang the migration indefinitely.

No security vulnerabilities were found. No source files were modified.

---

## Warnings

### WR-01: Successful migration count always reports 0 in summary and metadata JSON

**File:** `src/tests/overhead-benchmark/run_overhead_benchmark.py:499,525,333`

**Issue:** The CSV row is written with `"success": str(success).lower()` where `success` comes from `resp_json.get("status", "failed")`. The migration service returns `"status": "success"`, so the CSV field contains the string `"success"`. However, the final count at line 525 and the `write_metadata_json` check at line 333 both compare with `== "true"`:

```python
# line 499 — writes "success" to the row
"success": str(success).lower(),

# line 525 — checks for "true" but CSV contains "success"
successful = sum(1 for r in all_rows if str(r.get("success", "")).lower() == "true")
```

Both the logged summary (`[BENCHMARK] Run complete: 0/54 migrations successful`) and the `overhead_metadata.json` `"successful"` field will always be 0, making the output misleading.

**Fix:** Normalize the success flag to a boolean string at write time, or fix the counting predicate to match the written value:

```python
# Option A — normalize at write time
success_str = "true" if success == "success" else "false"
row = {
    ...
    "success": success_str,
    ...
}

# Option B — fix the counting predicate to match what is actually written
successful = sum(
    1 for r in all_rows
    if str(r.get("success", "")).lower() in ("true", "success")
)
```

The same fix must be applied in `write_metadata_json` (line 333) and in `graph_overhead.py` line 49 (which already accepts both "true" and "success", so it is correct as-is). Choose Option A for consistency — it makes the CSV self-describing and aligns with what `test_csv_schema.py` expects (`"true"/"false"`).

---

### WR-02: Workload pods use `hostPath.type: Directory` — pod scheduling fails if `/tmp/checkpoints` does not exist

**File:** `src/tests/overhead-benchmark/workloads/memcount.yml:42`, `src/tests/overhead-benchmark/workloads/sysbench-cpu.yml:48`, `src/tests/overhead-benchmark/workloads/sysbench-memory.yml:48`

**Issue:** All three workload manifests declare the checkpoint volume as:

```yaml
- name: checkpoint-volume
  hostPath:
    path: /tmp/checkpoints
    type: Directory
```

`type: Directory` requires the directory to already exist on the target node at scheduling time. If the KIND worker node has not yet had a migration run (or was freshly started), `/tmp/checkpoints` will not exist and Kubernetes will refuse to schedule the pod with a `FailedMount` error. The target pod created by `create_target_pod_only` in `live_migration.py` correctly uses `type: DirectoryOrCreate`, but the source workload pods do not.

**Fix:** Change `type: Directory` to `type: DirectoryOrCreate` in all three workload manifests, or pre-create the directory in the benchmark's `cleanup_workload_pods` function:

```yaml
# In all three workload YAMLs — change:
    hostPath:
      path: /tmp/checkpoints
      type: Directory
# To:
    hostPath:
      path: /tmp/checkpoints
      type: DirectoryOrCreate
```

---

### WR-03: Checkpoint transfer uses `subprocess.run` without timeout — migration can hang indefinitely

**File:** `src/controller/migrator/live_migration.py:1232-1235`

**Issue:** The two `kubectl cp` calls that transfer the checkpoint tar between nodes use `check=True` but no `timeout` parameter:

```python
cmd = f"kubectl cp monitor/migrator-{self.source_node}:/tmp/migration_checkpoint.tar {temp_file}"
subprocess.run(cmd, shell=True, check=True)  # no timeout

cmd = f"kubectl cp {temp_file} monitor/migrator-{self.target_node}:/tmp/migration_checkpoint.tar"
subprocess.run(cmd, shell=True, check=True)  # no timeout
```

A large checkpoint or a network hiccup will cause the migration service to block here forever, holding the FastAPI request open and preventing any subsequent migrations.

**Fix:** Add an explicit timeout. For a KIND cluster with a 256 MB checkpoint ceiling, 120 seconds is a reasonable upper bound:

```python
subprocess.run(cmd, shell=True, check=True, timeout=120)
```

---

### WR-04: Bare `except:` in `load_kubernetes_config` swallows `SystemExit` and `KeyboardInterrupt`

**File:** `src/controller/migrator/live_migration.py:39`

**Issue:** The first `except:` clause is a bare catch that swallows all exceptions, including `SystemExit` and `KeyboardInterrupt`:

```python
try:
    config.load_incluster_config()
    ...
except:          # catches SystemExit, KeyboardInterrupt, etc.
    try:
        config.load_kube_config()
```

If `load_incluster_config` raises `SystemExit` or `KeyboardInterrupt` (e.g., during a graceful shutdown), those signals are silently swallowed and the code falls through to try `load_kube_config` instead. This is the established pattern in the codebase (CLAUDE.md notes broad `except Exception` at boundaries), but a bare `except:` is broader than necessary.

**Fix:** Catch the specific config exception the kubernetes library raises on failure:

```python
from kubernetes.config.config_exception import ConfigException

try:
    config.load_incluster_config()
except ConfigException:
    try:
        config.load_kube_config()
    except Exception as e:
        logger.error(f"Failed to load Kubernetes configuration: {e}")
        return False
return True
```

---

### WR-05: `perform_migration` silently discards the exception on failure

**File:** `src/controller/migrator/live_migration.py:1521-1523`

**Issue:** The top-level `except` block in `perform_migration` returns `False` but does not log the exception or its traceback:

```python
except Exception as e:
    # self._log_state(f"Migration failed: {e}", "ERROR")
    return False
```

The commented-out `_log_state` call means migration failures produce no logged error message from this function. Callers that get `False` back have no context about what went wrong without scrolling back through all earlier log lines.

**Fix:** Uncomment or replace the log call:

```python
except Exception as e:
    logger.error(f"[CRIU_MIGRATION] perform_migration raised exception: {e}")
    import traceback
    logger.error(f"[CRIU_MIGRATION] Traceback: {traceback.format_exc()}")
    return False
```

---

## Info

### IN-01: `datetime.utcnow()` is deprecated in Python 3.12+

**File:** `src/tests/overhead-benchmark/run_overhead_benchmark.py:383`

**Issue:** `datetime.utcnow()` is deprecated since Python 3.12 and will be removed in a future version. The rest of the file already uses `datetime.now(timezone.utc)` (e.g., line 356).

**Fix:**
```python
# Change:
run_id = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
# To:
run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
```

---

### IN-02: Misleading comment in `extract_timing_from_logs` — "Using last 3" does nothing

**File:** `src/tests/overhead-benchmark/run_overhead_benchmark.py:266-269`

**Issue:** The comment claims "Keep only the last occurrence of each event type if duplicates exist — dict assignment naturally keeps the last value," but since the dict key is the event name and a `dict` can only hold one value per key, duplicate events are already overwritten in the loop. The `len(timings) > 3` check can therefore never be true (there are only 3 distinct event keys). The warning and comment are dead logic.

**Fix:** Remove the dead branch or clarify the intent:

```python
# Remove:
if len(timings) > 3:
    logger.warning(f"[TIMING] Found {len(timings)} timing events (expected 3) — possible log contamination. Using last 3.")
    # Keep only the last occurrence of each event type if duplicates exist
    # (dict assignment naturally keeps the last value in the loop above)
```

---

### IN-03: Sample data in `graph_overhead.py` uses hyphenated workload names inconsistent with benchmark output

**File:** `src/tests/overhead-benchmark/graph_overhead.py:293`

**Issue:** The `_make_sample_rows` validation helper uses `"sysbench-cpu"` (hyphen) as a workload name, but `run_overhead_benchmark.py` writes the WORKLOADS dict key `"sysbench_cpu"` (underscore) to the CSV. Running `--validate` will produce charts with workload labels that do not match what a real benchmark run produces. This will not cause a crash but creates a silent inconsistency between the validation path and the production path.

**Fix:** Update the sample data workload names to match the keys defined in `WORKLOADS`:

```python
# Change:
workloads = ["sysbench-cpu", "memcount"]
# To:
workloads = ["sysbench_cpu", "sysbench_memory", "memcount"]
```

---

### IN-04: `get_migrate_pod_name` looks in `monitor` namespace but migration service is deployed in `test-namespace`

**File:** `src/tests/overhead-benchmark/run_overhead_benchmark.py:113-114`

**Issue:** The function queries for pods with label `name=python-migrate-service` in the `monitor` namespace. Per CLAUDE.md: "test-namespace — test pods, migration service, migrator pods." The migration service is deployed in `test-namespace`, not `monitor`. If `monitor` is incorrect, this function always returns `None` and the benchmark exits immediately at line 420.

**Fix:** Verify the actual namespace of the migration service pod. If it is `test-namespace`, change line 114:

```python
"-n", "test-namespace",   # was: "monitor"
```

(Note: the comment on line 112 also says "The migration service always runs in the 'monitor' namespace" — update the docstring if the namespace changes.)

---

### IN-05: Step numbering gap in benchmark loop comments

**File:** `src/tests/overhead-benchmark/run_overhead_benchmark.py:478`

**Issue:** The migration loop comments jump from "Step 5" (line 464) directly to "Step 7" (line 478), with no "Step 6." This is a cosmetic inconsistency but can confuse future readers.

**Fix:** Renumber sequentially: change "Step 7" to "Step 6" and "Step 8" to "Step 7."

---

_Reviewed: 2026-04-18_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
