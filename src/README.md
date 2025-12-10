# KubeFlex Source Code

This directory contains the source code for the KubeFlex carbon-aware container live migration system. For architecture details and design choices, see [`ARCHITECTURE.md`](ARCHITECTURE.md).

## 📁 Directory Structure

```
src/
├── controller/                 # Main application code
│   ├── controller/
│   │   └── main.py             # KubeFlexController - main orchestration
│   ├── migrator/
│   │   ├── migrate_service.py  # FastAPI migration service
│   │   └── live_migration.py   # CRIU-based migration logic
│   ├── db/
│   │   ├── db.py               # Database utilities and queries
│   │   ├── metadata.py         # HTTP metadata service
│   │   └── upload_data.py      # Data upload job
│   └── utils/
│       └── live_migration.py   # Legacy migration utilities
├── manifests/                  # Kubernetes manifests
├── build/                      # Build configurations and Dockerfiles
├── sample_data/                # Sample data for testing
├── run.sh                      # Main deployment script
├── delete.sh                   # Cleanup script
├── test.sh                     # Testing script
└── update.sh                   # Update script
```

## 🚀 Quick Start

### Prerequisites

- Docker Desktop 4.0.0+
- Kubernetes (via KIND) v1.27.0+
- kubectl v1.27.0+
- Python 3.9+
- **Linux host system** (required for CRIU functionality)

### Deploy Everything

```bash
cd src
./run.sh --all --include-cluster --include-db --policy 3
```

This will:
1. Create a KIND cluster with 3 worker nodes
2. Deploy PostgreSQL database
3. Deploy all services (controller, migration service, metadata service)
4. Configure scheduling policy 3 (forecast-based)

## 📋 Shell Commands Reference

### Deployment Script (`run.sh`)

Deploy the KubeFlex system with various options.

**Usage**:
```bash
./run.sh [OPTIONS]
```

**Options**:
- `--include-db`: Deploy the database and storage components (includes metadata service as sidecar)
- `--include-cluster`: Create the KIND cluster (if it doesn't exist)
- `--time TIMESTAMP`: Set scheduler time (Unix timestamp)
  - Valid range: 1577836800 (2020-01-01) to 1672527600 (2022-12-31)
- `--policy POLICY`: Set scheduling policy (1, 2, or 3)
  - `1` = Initial placement only (assign to lowest region at runtime)
  - `2` = Hourly migration (migrate all pods to minimum region every hour)
  - `3` = Forecast-based (compare forecasts for all regions over EXPECTED_DURATION)
- `--help`: Show help message

**Examples**:
```bash
# Deploy everything including database and cluster
./run.sh --all --include-db --include-cluster

# Deploy with specific scheduler time
./run.sh --include-db --time 1609459200

# Deploy with hourly migration policy
./run.sh --include-db --policy 2

# Deploy with scheduler time and forecast-based policy
./run.sh --include-db --time 1609459200 --policy 3

# Deploy only migration components (assumes cluster exists)
./run.sh --migrate
```

**What Gets Deployed**:
- By default: Metrics-server, Migration service, Migrators, Controller, Test pod
- With `--include-db`: Also deploys PostgreSQL database and metadata service
- With `--include-cluster`: Also creates KIND cluster

### Testing Script (`test.sh`)

Test migration functionality and carbon forecast generation.

**Usage**:
```bash
./test.sh [OPTIONS]
```

**Options**:
- `--migrate`: Run migration test
- `--pod POD_NAME`: Pod name to migrate (default: `test-pod`)
- `--source SOURCE_NODE`: Source node name (default: `kind-worker`)
- `--target TARGET_NODE`: Target node name (default: `kind-worker2`)
- `--namespace NAMESPACE`: Kubernetes namespace (default: `test-namespace`)
- `--forecast DURATION`: Generate carbon forecast for specified duration (hours)
- `--keep-pod`: Keep original pod after migration (default: true)
- `--delete-pod`: Delete original pod after migration
- `--help`: Show help message

**Examples**:
```bash
# Test migration
./test.sh --migrate --pod test-pod --source kind-worker --target kind-worker2

# Generate 24-hour carbon forecast
./test.sh --forecast 24

# Run both migration and forecast tests
./test.sh --migrate --forecast 24 --pod test-pod

# Test migration and delete original pod
./test.sh --migrate --pod test-pod --delete-pod
```

**Port Forwarding**:
The script automatically sets up port forwarding:
- Migration service: `localhost:8000`
- Metadata service: `localhost:8008`

Port forwarding is cleaned up automatically when the script exits.

### Cleanup Script (`delete.sh`)

Remove deployed resources from the cluster.

**Usage**:
```bash
./delete.sh [OPTIONS]
```

**Options**:
- `--include-db`: Delete the database and storage components
- `--include-cluster`: Delete the KIND cluster
- `--help`: Show help message

**Examples**:
```bash
# Delete all services (keep cluster and database)
./delete.sh

# Delete everything including database
./delete.sh --include-db

# Delete everything including cluster
./delete.sh --all --include-cluster
```

**What Gets Deleted**:
- By default: Metrics-server, Migration service, Migrators, Controller, Test pod
- With `--include-db`: Also deletes PostgreSQL database and metadata service
- With `--include-cluster`: Also deletes KIND cluster

### Update Script (`update.sh`)

Update existing deployments without recreating the cluster.

**Usage**:
```bash
./update.sh
```

This script updates:
- Docker images
- Service configurations
- Manifests

## 🔧 Common Workflows

### Initial Setup

```bash
# 1. Create cluster and deploy everything
cd src
./run.sh --all --include-cluster --include-db --policy 3

# 2. Verify deployment
kubectl get pods -n monitor
kubectl get pods -n test-namespace
```

### Test Migration

```bash
# 1. Port forward migration service (in one terminal)
kubectl port-forward -n monitor svc/python-migrate-service 8000:8000

# 2. Run migration test (in another terminal)
cd src
./test.sh --migrate --pod test-pod --source kind-worker --target kind-worker2
```

### Test Carbon Forecast

```bash
# 1. Port forward metadata service (in one terminal)
kubectl port-forward -n monitor svc/metadata-service 8008:8008

# 2. Generate forecast (in another terminal)
cd src
./test.sh --forecast 24
```

### Change Scheduling Policy

```bash
# 1. Delete current controller
kubectl delete deployment controller -n monitor

# 2. Redeploy with new policy
cd src
./run.sh --policy 2  # or 1 or 3
```

### Cleanup and Redeploy

```bash
# 1. Delete everything except cluster
cd src
./delete.sh

# 2. Redeploy
./run.sh --all --include-db --policy 3
```

## 🔍 Troubleshooting

### Check Service Status

```bash
# Check all pods
kubectl get pods -n monitor
kubectl get pods -n test-namespace

# Check service logs
kubectl logs -n monitor deployment/controller
kubectl logs -n monitor deployment/python-migrate-service
kubectl logs -n monitor deployment/metadata-service

# Check migrator pods
kubectl get pods -n monitor -l app=migrator
kubectl logs -n monitor -l app=migrator
```

### Check Cluster Status

```bash
# List nodes
kubectl get nodes

# Check node labels
kubectl get nodes --show-labels

# Check KIND cluster
kind get clusters
```

### Debug Migration Issues

```bash
# Check migration service logs
kubectl logs -n monitor deployment/python-migrate-service

# Check migrator pod logs on specific node
kubectl logs -n monitor -l app=migrator --field-selector spec.nodeName=kind-worker

# Exec into migrator pod
kubectl exec -it -n monitor $(kubectl get pod -n monitor -l app=migrator --field-selector spec.nodeName=kind-worker -o jsonpath='{.items[0].metadata.name}') -- /bin/bash
```

### Database Issues

```bash
# Check database pod
kubectl get pods -n monitor -l app=db

# Check database logs
kubectl logs -n monitor -l app=db

# Exec into database
kubectl exec -it -n monitor $(kubectl get pod -n monitor -l app=db -o jsonpath='{.items[0].metadata.name}') -- psql -U sfarokhi -d sfarokhi
```

## 📊 Environment Variables

### Controller

- `SCHEDULING_POLICY`: Scheduling policy (1, 2, or 3, default: 3)
- `SCHEDULER_TIME`: Unix timestamp for scheduler clock (default: current time, clamped to data range)
- `MIGRATION_SERVICE_URL`: URL of migration service (default: `http://python-migrate-service:8000/live-migrate`)
- `CARBON_SERVER_URL`: URL of metadata service (default: `http://metadata-service:8008`)

### Database

- `DB_HOST`: Database host (default: `db-service`)
- `DB_PORT`: Database port (default: `5432`)
- `DB_NAME`: Database name (default: `sfarokhi`)
- `DB_USER`: Database user (default: `sfarokhi`)
- `DB_PASSWORD`: Database password (default: `wordpass`)

### Migration Service

- `CHECKPOINT_DIR`: Directory for checkpoint storage (default: `/tmp/checkpoints`)
- `NAMESPACE`: Kubernetes namespace (default: `test-namespace`)

## 📚 Additional Resources

- **Architecture Documentation**: See [`ARCHITECTURE.md`](ARCHITECTURE.md) for detailed architecture, design choices, and limitations
- **Main README**: See [`../README.md`](../README.md) for project overview
- **Data Documentation**: See [`../data/README.md`](../data/README.md) for data structure and analysis tools

## 🆘 Getting Help

For issues or questions:
1. Check the troubleshooting section above
2. Review logs: `kubectl logs -n monitor <pod-name>`
3. Check architecture documentation: [`ARCHITECTURE.md`](ARCHITECTURE.md)
4. Review main README: [`../README.md`](../README.md)
