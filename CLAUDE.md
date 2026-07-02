# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What is KubeFlex

KubeFlex is a carbon-aware container live migration system for Kubernetes. It uses CRIU (Checkpoint/Restore in Userspace) to migrate running containers between KIND cluster nodes, choosing target regions based on forecasted carbon intensity from US power grid data. The system runs on a local KIND cluster with 1 control-plane and 3 worker nodes, each labeled with a power grid region (NE, TEN, CENT).

## Common Commands

### Cluster and deployment

```bash
# Full deploy: cluster + database + services
cd src && bash run.sh --include-cluster --include-db --policy 5 --time 1609459200

# Deploy without recreating cluster/db (just redeploy services)
cd src && bash run.sh --policy 4 --time 1609459200

# Tear down everything
cd src && bash delete.sh --include-cluster --include-db

# Update container images after code changes
cd src && bash update.sh
```

### Testing

```bash
# Run a migration test
cd src && bash test.sh --migration

# Generate carbon forecast
cd src && bash test.sh --forecast 48

# Run expected simulation (no cluster needed, fast iteration)
python3 src/tests/carbon-single-pod/run_carbon_migration_test.py \
  --expected --expected-completion 2880 --expected-migration 5 \
  --policy 5 --scheduler-time 1609459200 --source-region NE \
  --forecast-cache data/carbon-single-pod/best_run/forecast_cache.json

# Graph results from a test run
python3 src/tests/carbon-single-pod/graph_results.py data/carbon-single-pod/<run_dir>
```

### Docker image builds

Images are built from `src/build/Dockerfile.*` files. Key images:
- `python-controller` (Dockerfile.main) — controller service
- `python-migrate` (Dockerfile.migrate) — migration service with CRIU/crictl/kubectl
- `migrator` (Dockerfile.migrator) — daemon pods on each worker node
- `python-metadata` (Dockerfile.metadata) — carbon forecast HTTP service
- `testpod` (Dockerfile.testpod) — test workload with CRIU 4.1.1

Python requirements are in `src/build/{main,migrate,data,upload_data}_req.txt`.

### Port forwarding (for local debugging)

```bash
kubectl port-forward -n monitor svc/metadata-service 8008:8008   # carbon forecasts
kubectl port-forward -n test-namespace svc/migration-service 8000:8000  # migration API
```

## Architecture

### Component interaction flow

```
Controller (monitor ns) --[HTTP]--> Migration Service (test-namespace ns)
    |                                      |
    |--[HTTP]--> Metadata Service:8008     |--[exec]--> Migrator Pods (per worker)
    |            (sidecar in DB pod)       |                |
    |                                      |            CRIU dump/restore
    |--[k8s API]--> Pod discovery          |
                    Node labeling          |--[kubectl cp]--> Checkpoint transfer
                                           |
PostgreSQL:5432 <-- carbon intensity data (2020-2022, hourly, 14 US regions)
```

### Scheduling policies

1. **Policy 1** — Initial placement only, no migrations
2. **Policy 2** — Migrate to minimum-carbon region every hour
3. **Policy 3** — Forecast-based: sum intensity over expected duration, pick lowest total
4. **Policy 4** — Adaptive: forecast with migration cost threshold and volatility-based recheck
5. **Policy 5** — Always-best: migrate whenever next hour has a lower-carbon region

### Migration workflow

Controller discovers pods → selects target region per policy → calls Migration Service REST API → Migration Service coordinates with Migrator pod on source node → CRIU checkpoint → transfer checkpoint to target node via kubectl cp → CRIU restore on target → delete original pod. Pods use counter-based naming (`pod-name`, `pod-name-1`, `pod-name-2`, ...).

### Expected simulation mode

`run_carbon_migration_test.py --expected` runs policy logic against forecast data without a live cluster. It simulates hour-by-hour decisions and outputs CSV files compatible with `graph_results.py`. Uses `--use-hw` flag to factor in per-region hardware power consumption (`HW_VALS` dict in the script). When `--use-hw` is set, all carbon values (cumulative, baseline, migration events) are scaled by `power_per_core`.

### Key configuration (env vars / ConfigMap)

- `SCHEDULING_POLICY` (1-5), `SCHEDULER_TIME` (unix timestamp) — set via `scheduler-config` ConfigMap in both `monitor` and `test-namespace`
- `CHECK_INTERVAL_SECONDS`, `SIM_HOURS_PER_CHECK` — control simulation speed
- `MIGRATION_SERVICE_URL`, `CARBON_SERVER_URL` — service endpoints
- `DB_HOST=db-service`, `DB_PORT=5432`, `DB_NAME=sfarokhi`, `DB_USER=sfarokhi`

### Namespaces

- `monitor` — controller deployment, RBAC
- `test-namespace` — test pods, migration service, migrator pods

### Deployment order (handled by run.sh)

KIND cluster → metrics-server → RBAC → PostgreSQL + metadata sidecar → db-upload job → migrator pods → migration service → controller → test pods

## Codebase Layout

- `src/controller/controller/main.py` — `KubeFlexController` class, all 5 policy implementations, APScheduler-based hourly checks
- `src/controller/migrator/migrate_service.py` — FastAPI REST service (`POST /live-migrate`)
- `src/controller/migrator/live_migration.py` — CRIU checkpoint/restore logic, `CriuMigrationTracker`
- `src/controller/db/db.py` — PostgreSQL queries, PL/pgSQL carbon forecast functions
- `src/controller/db/metadata.py` — HTTP server on port 8008 serving carbon forecasts
- `src/manifests/` — Kubernetes YAML (cluster.yml, controller.yml, storage.yml, etc.)
- `src/build/` — Dockerfiles and requirements.txt files
- `src/tests/` — Test workloads (sysbench, MPI, carbon-single-pod simulation harness)
- `data/` — Test run outputs (carbon_log.csv, migration_events.csv, results.csv, forecast_cache.json)

## Constraints

- CRIU live migration only works on Linux (KIND on macOS can run the cluster but not actual CRIU operations)
- Worker nodes are hardcoded as `kind-worker`, `kind-worker2`, `kind-worker3` with regions NE, TEN, CENT
- Carbon data covers 2020-01-01 to 2022-12-31; scheduler-time must fall in this range
- Migration pods require privileged security context with SYS_ADMIN, SYS_PTRACE, CHECKPOINT_RESTORE capabilities

<!-- GSD:project-start source:PROJECT.md -->
## Project

**KubeFlex**

KubeFlex is a carbon-aware container live migration system for Kubernetes, being extended with advanced migration heuristics and distributed workload migration for a thesis. The system uses CRIU to checkpoint/restore running containers between KIND cluster nodes, choosing target regions based on forecasted carbon intensity from US power grid data. The next phase of work focuses on smarter migration decisions that account for hardware heterogeneity, job deadlines, checkpoint/restore overhead, and runtime estimates — and on enabling migration of multi-node distributed workloads regardless of their networking library.

**Core Value:** Prove that carbon-aware migration heuristics — informed by hardware specs, job deadlines, and migration overhead — reduce total carbon emissions compared to naive scheduling policies, validated through both simulation and cluster experiments.

### Constraints

- **Platform**: CRIU only works on Linux; KIND on macOS can run cluster but not actual CRIU operations
- **Data range**: Carbon data covers 2020-01-01 to 2022-12-31; scheduler-time must fall in this range
- **Cluster topology**: 3 worker nodes hardcoded as kind-worker, kind-worker2, kind-worker3 with regions NE, TEN, CENT
- **Security**: Migration pods require privileged security context (SYS_ADMIN, SYS_PTRACE, CHECKPOINT_RESTORE)
- **Stack**: Python 3.9 in containers, FastAPI, PostgreSQL, APScheduler — maintain consistency with existing codebase
<!-- GSD:project-end -->

<!-- GSD:stack-start source:codebase/STACK.md -->
## Technology Stack

## Languages
- Python 3.9 - All application code (controller, migration service, metadata service, DB operations, tests)
- Bash - Deployment scripts, cluster management, installation
- PL/pgSQL - Database stored functions for carbon intensity queries (`src/controller/db/db.py` defines them inline)
- YAML - Kubernetes manifests, KIND cluster config
## Runtime
- Python 3.9 (pinned in all Dockerfiles: `FROM python:3.9-slim`)
- Local development venv uses Python 3.13.3 (`pyvenv.cfg`)
- Linux containers (Ubuntu 22.04 for testpod image)
- Docker (Docker Desktop 4.48.0+ on macOS, Docker Engine on Linux)
- containerd with crictl v1.28.0 (inside migration containers)
- CRIU 4.1.1 (built from source in `src/build/Dockerfile.testpod`)
- KIND (Kubernetes in Docker) v0.27.0 - local cluster with 1 control-plane + 3 workers
- kubectl v1.33.1
- pip (no lockfiles, requirements specified in plain `.txt` files)
- No `pyproject.toml`, `setup.py`, or `poetry.lock`
## Frameworks
- FastAPI 3.0.0 - Migration service REST API (`src/controller/migrator/migrate_service.py`)
- uvicorn - ASGI server for FastAPI
- http.server (stdlib) - Metadata HTTP service (`src/controller/db/metadata.py`)
- APScheduler - Background job scheduling in controller (`src/controller/controller/main.py`)
- kubernetes (Python client) - Pod discovery, node labeling, in-cluster/kubeconfig auth
- psycopg2-binary - PostgreSQL driver (used in `src/controller/db/db.py`, `src/controller/db/upload_data.py`)
- pandas - CSV-to-PostgreSQL data loading (`src/controller/db/upload_data.py`)
- matplotlib - Test result graphing (`src/tests/carbon-single-pod/graph_results.py`)
- numpy - Numerical operations in graphing and test harness
- plotly - Interactive graphs in metadata service (`src/controller/db/metadata.py`)
- No test framework (pytest, unittest) - tests are script-based simulation harnesses
- No CI/CD pipeline detected
## Key Dependencies
- `requests` - HTTP calls to migration and metadata services
- `psycopg2-binary` - PostgreSQL connection
- `kubernetes` - K8s API client
- `prettytable` - Console output formatting
- `apscheduler` - Scheduled carbon checks
- `pytz` - Timezone handling for carbon data
- `numpy` - Numerical calculations
- `matplotlib` - Visualization
- `fastapi` - REST API framework
- `uvicorn` - ASGI server
- `pydantic` - Request/response validation
- `kubernetes` - K8s API client
- `paramiko` - SSH client (available but primary method is kubectl exec/cp)
- `psutil` - Process utilities
- `grpcio`, `grpcio-tools` - gRPC support (for containerd/CRI communication)
- `requests` - HTTP client
- `psycopg2-binary` - PostgreSQL connection
- `prettytable` - Console formatting
- `requests`, `numpy`, `matplotlib`, `pytz`, `psycopg2-binary`, `kubernetes`, `prettytable`, `plotly`
- `psycopg2-binary` - PostgreSQL driver
- `pandas` - CSV parsing and bulk insert
- `tqdm` - Progress bars for data upload
- `pytz` - Timezone handling
## Docker Images
| Image Name | Dockerfile | Base | Purpose |
|---|---|---|---|
| `python-controller` | `src/build/Dockerfile.main` | `python:3.9-slim` | Controller service |
| `python-migrate` | `src/build/Dockerfile.migrate` | `python:3.9-slim` | Migration service with CRIU/crictl/kubectl |
| `migrator` | `src/build/Dockerfile.migrator` | `python:3.9-slim` | Daemon pods on worker nodes |
| `python-metadata` | `src/build/Dockerfile.metadata` | `python:3.9-slim` | Carbon forecast HTTP service |
| `testpod` | `src/build/Dockerfile.testpod` | `ubuntu:22.04` | Test workload with CRIU 4.1.1 |
| `python-db-upload` | Not in repo (referenced in manifests) | Unknown | CSV data upload job |
| `postgres:15` | Official image | - | PostgreSQL database |
- Docker Hub: `salamander1223/*` (referenced in `src/manifests/storage.yml`)
- Local KIND loading for development builds
## Configuration
- `SCHEDULING_POLICY` (1-5) - Carbon scheduling algorithm
- `SCHEDULER_TIME` (Unix timestamp) - Simulation start time
- `CHECK_INTERVAL_SECONDS`, `SIM_HOURS_PER_CHECK` - Simulation speed
- `MIGRATION_SERVICE_URL` - default `http://python-migrate-service:8000/live-migrate`
- `CARBON_SERVER_URL` - default `http://metadata-service:8008`
- `DB_HOST` (default: `db-service`), `DB_PORT` (5432), `DB_NAME` (`sfarokhi`), `DB_USER` (`sfarokhi`), `DB_PASSWORD`
- No build config files (tsconfig, webpack, etc.) - pure Python with pip
- Docker build context is `src/` directory
- `src/build/Dockerfile.*` - all Dockerfiles
- `src/build/*_req.txt` - all requirements files
## System-Level Dependencies (in containers)
- `docker.io`, `containerd`, `criu` (apt packages)
- `crictl` v1.28.0 (CRI tools for container inspection)
- `kubectl` (latest stable, installed at build time)
- `jq`, `openssh-client`, `procps`, `psmisc`
- CRIU v4.1.1 (built from source with checkpoint_restore capability)
- `tini` (PID 1 init process)
- `iproute2`, `nftables`, `libnl-3-200`, `libcap2`
## Platform Requirements
- macOS or Linux (Windows requires WSL2)
- Docker Desktop 4.48.0+ (macOS) or Docker Engine (Linux)
- kubectl >= 1.32.0 (recommended 1.33.1)
- KIND >= 0.27.0
- Python >= 3.9
- `install-requirements.sh` automates installation of all prerequisites
- Linux only (CRIU requires Linux kernel features)
- KIND cluster with 4 nodes (1 control-plane + 3 workers)
- Privileged containers with `SYS_ADMIN`, `SYS_PTRACE`, `CHECKPOINT_RESTORE` capabilities
<!-- GSD:stack-end -->

<!-- GSD:conventions-start source:CONVENTIONS.md -->
## Conventions

## Naming Patterns
- Python modules: `snake_case.py` (e.g., `live_migration.py`, `migrate_service.py`, `upload_data.py`)
- Shell scripts: `snake_case.sh` (e.g., `run.sh`, `test.sh`, `delete.sh`, `update.sh`)
- Kubernetes manifests: `kebab-case.yml` or `single-word.yml` (e.g., `cluster.yml`, `controller.yml`, `python-migrate.yml`, `scheduler-config.yml`)
- Test scripts: `test_*.sh` or `run_*_test.sh` / `run_*_test.py`
- Dockerfiles: `Dockerfile.<suffix>` (e.g., `Dockerfile.main`, `Dockerfile.migrate`)
- Use `snake_case` for all functions and methods
- Prefix internal/private methods with underscore: `_extract_base_pod_name()`, `_get_next_pod_name()`, `_log_state()`
- DB query functions: `fetch_*` for database reads, `collect_*` for aggregated results
- Examples from `src/controller/controller/main.py`:
- Use `snake_case` for local variables and instance attributes
- Use `UPPER_CASE` for module-level constants: `NAMESPACE`, `POD_BASENAME`, `HW_VALS`, `METADATA_URL`
- Environment variable names: `UPPER_CASE` (e.g., `SCHEDULING_POLICY`, `SCHEDULER_TIME`, `CHECK_INTERVAL_SECONDS`)
- Use `PascalCase`: `KubeFlexController`, `CriuMigrationTracker`, `CarbonDataHandler`, `MigrateRequest`
- Pydantic models: `PascalCase` (e.g., `MigrateRequest`, `DistributedMigrateRequest`)
- Use `UPPER_CASE` for all shell script variables: `NAMESPACE`, `SOURCE_NODE`, `TARGET_NODE`, `SCHEDULING_POLICY`
- Port forward PIDs: `MIGRATION_PORT_FORWARD_PID`, `METADATA_PORT_FORWARD_PID`
- Pod names: `kebab-case` with numeric suffixes for migration chains (e.g., `test-pod`, `test-pod-1`, `test-pod-2`)
- Services: `kebab-case` (e.g., `python-migrate-service`, `metadata-service`, `db-service`)
- ConfigMaps: `kebab-case` (e.g., `scheduler-config`)
- Namespaces: `monitor` (control plane), `test-namespace` (workloads)
- Node labels: `REGION=NE`, `REGION=TEN`, `REGION=CENT` (uppercase key and value)
## Code Style
- No automated formatter configured (no `.prettierrc`, `.flake8`, `pyproject.toml` formatting config)
- Indentation: 4 spaces for Python, 2 spaces for YAML, mixed in bash (mostly 4)
- Line length: no enforced limit; lines up to ~130 characters are common
- No linter configuration files detected
- No CI pipeline enforcing lint rules
- Python files: `#!/usr/bin/env python3`
- Bash scripts: `#!/bin/bash` or `#!/usr/bin/env bash`
- Use `set -euo pipefail` at top of bash scripts (consistently applied in `src/test.sh`, `src/run.sh`, test scripts)
- Use `set -e` in simpler scripts like `src/run.sh`
## Import Organization
- Local imports require `sys.path.insert(0, str(Path(__file__).parent.parent))` because modules are deployed in containers without proper package installation
- Used in `src/controller/controller/main.py`, `src/controller/migrator/migrate_service.py`
- Example:
- `from db.db import *` is used in `src/controller/controller/main.py` -- this is the established pattern for the DB module
- No `pyproject.toml`, `setup.py`, or package configuration providing importable packages
- All inter-module imports use `sys.path` manipulation
## Error Handling
- Broad `try/except Exception as e` blocks at method boundaries
- Log errors with `logger.error()` before returning failure values
- Return `Dict` with `"success": bool` for operation results
- Use `import traceback` inside except blocks (imported lazily, not at top level) for detailed error logs
- Example from `src/controller/controller/main.py`:
- Raise `HTTPException(status_code=500, detail=...)` for failures
- Log with `logger.exception()` for full tracebacks
- Catch `ApiException` specifically, check `.status == 404` for not-found cases
- Treat 404 as "already gone" (not an error) in deletion operations
- `set -euo pipefail` at script top
- Colored log functions: `log_info()`, `log_success()`, `log_error()`, `log_warning()`
- Pattern: check return codes explicitly with `if ! command; then log_error ...; exit 1; fi`
## Logging
- Use uppercase bracketed tags to categorize log messages
- Tags indicate the subsystem: `[MIGRATION]`, `[DISCOVERY]`, `[METADATA]`, `[POLICY_3]`, `[POLICY_4]`, `[POLICY_5]`, `[HOURLY_CHECK]`, `[BREAKPOINT]`, `[RESCHEDULE]`, `[TIMING]`, `[NODE_SELECTION]`, `[CRIU_DUMP]`, `[CRIU_RESTORE]`, `[TRANSFER]`, `[VALIDATION]`, `[KUBECTL_EXEC]`, `[STATE]`, `[API]`, `[SERVER]`
- Separator lines with `"=" * 80` for major section boundaries
- `logger.info()` for normal operations and state changes
- `logger.warning()` for recoverable issues and fallbacks
- `logger.error()` for failures
- `logger.debug()` for verbose request details (rarely used)
- `logger.exception()` only in FastAPI error handlers
- Color-coded functions defined at top of each script:
## Comments
- All Python files have module-level docstrings describing purpose
- Example from `src/controller/migrator/live_migration.py`:
- Used extensively to explain Kubernetes/CRIU operations and policy logic
- Step-numbered comments in migration workflow: `# Step 1:`, `# Step 2:`, etc.
- Policy documentation inline: scheduling policy choices explained at point of use
- Comment block at top describing purpose and usage examples
- Particularly detailed in test scripts (see `src/tests/antibody-sim/test_criu_same_pod.sh`)
## Function Design
- Operations return `Dict` with `"success": bool` key plus details
- Query functions return `Optional[str]` or `Optional[Dict]` (None on failure)
- Boolean returns for validation/check functions
- Tuples for multi-value returns: `Tuple[bool, Optional[str]]` for (should_migrate, target_region)
- Namespace defaults: `namespace: str = "test-namespace"`
- Timeout defaults: `timeout: int = 300`
- Configuration from env vars with fallbacks: `os.getenv('KEY', 'default')`
- Constructor takes key config, env vars provide overrides
- Example from `KubeFlexController.__init__`:
## Module Design
- No `__all__` definitions in any module
- `__init__.py` files exist but are empty (in `src/controller/controller/`, `src/controller/db/`, `src/controller/migrator/`)
- Modules are imported directly by name after `sys.path` manipulation
- Each module is imported individually
- No re-export patterns
## Configuration Pattern
- `scheduler-config` ConfigMap provides `SCHEDULER_TIME` and `SCHEDULING_POLICY`
- Mounted as env vars in pod specs
- Shell scripts create/update ConfigMaps before deploying services
- Hardcoded in `src/controller/db/db.py` with env var overrides:
## API Design Patterns
- Pydantic models for request validation
- Version string in app metadata and responses: `"version": "3.0.0"`
- Health check at `/health`, info at `/info`, root at `/`
- Main operation endpoints: `POST /live-migrate`, `POST /distributed-migrate`
- Query endpoints: `GET /nodes`, `GET /pods/{namespace}`, `GET /migration-status/{pod_name}`
- Raw `http.server.HTTPServer` with `BaseHTTPRequestHandler` (no framework)
- JSON request/response via POST
- File serving via GET
- Port 8008
- Controller -> Migration Service: HTTP POST with JSON body
- Controller -> Metadata Service: HTTP POST with JSON body
- Migration Service -> Kubernetes API: Python client library
- All HTTP calls use `requests` library with explicit timeouts (30-300 seconds)
<!-- GSD:conventions-end -->

<!-- GSD:architecture-start source:ARCHITECTURE.md -->
## Architecture

## Pattern Overview
- Controller-Service-Worker architecture deployed on a local KIND cluster
- Carbon intensity data drives all scheduling decisions via PostgreSQL + PL/pgSQL functions
- CRIU (Checkpoint/Restore in Userspace) enables live container migration without downtime
- Simulated time system allows replaying historical carbon data (2020-2022) at accelerated rates
- Five scheduling policies of increasing sophistication (placement-only through adaptive forecast-aware)
## Layers
- Purpose: Decides WHEN and WHERE to migrate pods based on carbon intensity forecasts
- Location: `src/controller/controller/main.py` (class `KubeFlexController`)
- Contains: All 5 policy implementations, pod discovery, hourly migration scheduling via APScheduler
- Depends on: Metadata Service (HTTP), PostgreSQL (via db module), Kubernetes API
- Used by: Runs autonomously as a Kubernetes Deployment in `monitor` namespace
- Purpose: Performs the actual CRIU checkpoint/restore migration between nodes
- Location: `src/controller/migrator/live_migration.py` (class `CriuMigrationTracker`), `src/controller/migrator/distributed_migration.py`
- Contains: CRIU dump/restore orchestration, checkpoint transfer, target pod creation, mount discovery
- Depends on: Migrator daemon pods (kubectl exec), Kubernetes API, crictl, CRIU binary
- Used by: Migration Service (FastAPI)
- Purpose: Exposes migration capabilities as HTTP endpoints
- Location: `src/controller/migrator/migrate_service.py`
- Contains: FastAPI app with `/live-migrate` (CRIU-based) and `/distributed-migrate` (application-checkpoint-based) endpoints
- Depends on: `live_migration.py`, `distributed_migration.py`, Kubernetes API
- Used by: Controller (sends HTTP POST to `python-migrate-service:8000`)
- Purpose: Stores historical carbon intensity data and serves forecasts
- Location: `src/controller/db/db.py` (queries), `src/controller/db/metadata.py` (HTTP server), `src/controller/db/upload_data.py` (data loader)
- Contains: PL/pgSQL functions for min-intensity and per-region queries, HTTP server on port 8008
- Depends on: PostgreSQL 15, CSV data files in `src/sample_data/`
- Used by: Controller (HTTP to metadata service), Controller (direct psycopg2 for extended queries in Policy 4/5)
- Purpose: Daemon pods on each worker node providing host-level access for CRIU operations
- Location: `src/manifests/migrator.yml` (template with `{NODE_NAME}` placeholder)
- Contains: Privileged pods with hostPID, hostNetwork, mounts to /proc, /sys, /dev, containerd socket
- Depends on: KIND worker nodes
- Used by: Migration Execution Layer (via kubectl exec)
## Data Flow
- Simulation time tracked in `KubeFlexController.current_simulation_time` (Unix timestamp, advances hourly)
- Pod naming uses incrementing counters: `base-name`, `base-name-1`, `base-name-2`, etc.
- Migration state tracked per-migration in `CriuMigrationTracker.migration_state` dict
- Carbon data is historical (PostgreSQL), not real-time -- scheduler time determines query window
## Key Abstractions
- Purpose: Central orchestrator -- all scheduling intelligence lives here
- Pattern: Long-running process with APScheduler for periodic checks
- Key methods: `hourly_migration_check()`, `discover_pods_for_migration()`, `migrate_pod()`, policy-specific methods (`get_optimal_region_for_pod_forecast()`, `get_forecast_aware_migration_decision()`, `get_best_region_now()`)
- Purpose: Manages all steps of a single CRIU migration
- Pattern: Stateful tracker with step-by-step execution and error/warning accumulation
- Key methods: `perform_migration()`, `perform_criu_dump()`, `transfer_checkpoint_to_target()`, `execute_criu_restore_in_target()`, `create_target_pod_only()`
- Purpose: Encapsulate all PostgreSQL interactions
- Pattern: PL/pgSQL stored functions created on first use, results returned as pipe-delimited text arrays parsed in Python
- Key functions: `collect_carbon_forecast()`, `collect_region_forecast()`, `fetch_extended_region_data()`
- Purpose: HTTP interface to carbon forecast data
- Pattern: BaseHTTPRequestHandler serving POST (forecast queries) and GET (file retrieval)
- Accepts `{duration, start_time}` JSON body, returns structured forecast with min_forecast + per-region data
## Entry Points
- Location: `src/controller/controller/main.py` lines 1471-1609
- Triggers: Container startup via `python3 controller/main.py --namespace test-namespace --skip-migration`
- Responsibilities: Parses args/env, creates `KubeFlexController`, initializes DB + K8s connections, starts APScheduler, runs forever
- Location: `src/controller/migrator/migrate_service.py`
- Triggers: Container startup via `/start.sh` which launches uvicorn on port 8000
- Responsibilities: FastAPI server accepting migration requests at `/live-migrate` and `/distributed-migrate`
- Location: `src/controller/db/metadata.py` lines 358-367
- Triggers: Sidecar container in database pod, `python3 metadata.py`
- Responsibilities: HTTP server on port 8008, serves carbon forecast data from PostgreSQL
- Location: `src/controller/db/upload_data.py`
- Triggers: Kubernetes Job `db-upload` at deployment time
- Responsibilities: Loads CSV files from `test_data/` directory into PostgreSQL `public.table`
- Location: `src/run.sh`
- Triggers: Manual execution
- Responsibilities: Creates KIND cluster (optional), labels nodes with regions, deploys all manifests in order, waits for readiness
## Error Handling
- Controller methods catch all exceptions, log tracebacks, return empty/False/None -- never crash the main loop
- Migration tracker accumulates errors in `migration_state['errors']` list and returns success boolean
- Kubernetes API errors (404) handled specially (e.g., pod already deleted is OK)
- HTTP timeouts on migration requests: 300s for migration, 30s for metadata queries
- Stale pod cleanup runs before every hourly check to remove leftover pods from failed migrations
## Cross-Cutting Concerns
- `monitor` namespace: Controller deployment, migration service pod, migrator daemon pods, database pod (with metadata sidecar), RBAC resources
- `test-namespace` namespace: Test/workload pods that get migrated
## Deployment Architecture
```
```
```
```
<!-- GSD:architecture-end -->

<!-- GSD:skills-start source:skills/ -->
## Project Skills

No project skills found. Add skills to any of: `.claude/skills/`, `.agents/skills/`, `.cursor/skills/`, or `.github/skills/` with a `SKILL.md` index file.
<!-- GSD:skills-end -->

<!-- GSD:workflow-start source:GSD defaults -->
## GSD Workflow Enforcement

Before using Edit, Write, or other file-changing tools, start work through a GSD command so planning artifacts and execution context stay in sync.

Use these entry points:
- `/gsd-quick` for small fixes, doc updates, and ad-hoc tasks
- `/gsd-debug` for investigation and bug fixing
- `/gsd-execute-phase` for planned phase work

Do not make direct repo edits outside a GSD workflow unless the user explicitly asks to bypass it.
<!-- GSD:workflow-end -->

<!-- GSD:profile-start -->
## Developer Profile

> Profile not yet configured. Run `/gsd-profile-user` to generate your developer profile.
> This section is managed by `generate-claude-profile` -- do not edit manually.
<!-- GSD:profile-end -->
