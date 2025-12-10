# KubeFlex: Carbon-Aware Container Live Migration System

KubeFlex is a Kubernetes-based container live migration system designed to enable seamless, carbon-aware migration of running containers between nodes in a KIND (Kubernetes in Docker) cluster. The system uses CRIU (Checkpoint/Restore in Userspace) to perform live migrations without service interruption, while optimizing for carbon intensity based on regional power grid data.


## Migration Flow

1. **Discovery**: Identify source container and target node using Kubernetes API
2. **Mount Analysis**: Discover container mount paths and external bind mounts
3. **Target Pod Creation**: Create target pod with counter-based naming (e.g., `test-pod-1`, `test-pod-2`)
4. **CRIU Checkpoint**: Create complete container checkpoint using `criu dump` with external mount handling
5. **Data Transfer**: Transfer checkpoint data and script data between nodes via kubectl cp
6. **CRIU Restore**: Restore container state using `criu restore` with matching mount configuration
7. **Pod Deletion**: Optionally delete original pod after successful migration
8. **Verification**: Verify migration success and cleanup resources

**For detailed documentation on each directory:**
- **Source Code**: 
  - [`src/README.md`](src/README.md) - Usage guide, shell commands, and quick start
  - [`src/ARCHITECTURE.md`](src/ARCHITECTURE.md) - Architecture, design choices, modules, and limitations
- **Data Directory**: See [`data/README.md`](data/README.md) for data structure, processing, and analysis tools

## 🔌 Module Interfaces

### Controller Module (`controller/controller/main.py`)

**Class**: `KubeFlexController`

**Key Methods**:
- `__init__(scheduler_time: Optional[float], scheduling_policy: int)` - Initialize controller with scheduler time and policy
- `initialize() -> bool` - Initialize connections and start scheduler
- `migrate_pod(namespace: str, pod: str, target_node: str, delete_original: bool) -> Dict` - Migrate a pod to target node
- `hourly_migration_check()` - Periodic migration check based on scheduling policy
- `get_minimum_region_from_metadata() -> Optional[str]` - Get minimum carbon region
- `get_optimal_region_for_pod_forecast(pod_name: str, namespace: str) -> Optional[str]` - Forecast-based region selection
- `run_migration_test(namespace: str, log_duration: int) -> Dict` - Run migration test workflow

**Scheduling Policies**:
1. **Policy 1**: Initial placement only - Assign pods to lowest region at runtime, no migrations
2. **Policy 2**: Hourly migration - Automatically migrate all pods to minimum region every hour
3. **Policy 3**: Forecast-based - Compare forecasts for all regions over `EXPECTED_DURATION` and migrate to region with lowest total carbon intensity

**Environment Variables**:
- `SCHEDULING_POLICY`: Scheduling policy (1, 2, or 3)
- `SCHEDULER_TIME`: Unix timestamp for scheduler clock
- `MIGRATION_SERVICE_URL`: URL of migration service
- `CARBON_SERVER_URL`: URL of metadata service

### Migration Service (`controller/migrator/migrate_service.py`)

**FastAPI Application**: REST API for pod migration

**Endpoints**:
- `GET /` - Root endpoint with service info
- `GET /health` - Health check
- `GET /info` - Service information and available endpoints
- `POST /live-migrate` - Perform CRIU-based migration

**Request Model** (`MigrateRequest`):
```python
{
    "namespace": str,
    "pod": str,
    "source_node": str,
    "target_node": str,
    "target_region": Optional[str],  # Region label for target node
    "delete_original": bool,  # Whether to delete original pod after migration
    "debug": bool
}
```

**Response Model**:
```python
{
    "success": bool,
    "source_pod": str,
    "target_pod": str,  # Counter-based name (e.g., "test-pod-1")
    "source_node": str,
    "target_node": str,
    "migration_complete": bool,
    "steps_completed": List[str],
    "errors": List[str],
    "warnings": List[str]
}
```

### Live Migration Module (`controller/migrator/live_migration.py`)

**Function**: `criu_migrate_pod()`

**Signature**:
```python
def criu_migrate_pod(
    source_pod: str,
    source_node: str,
    target_node: str,
    namespace: str,
    target_region: Optional[str] = None,
    delete_original: bool = True,
    checkpoint_dir: str = "/tmp/checkpoints"
) -> Dict
```

**Key Features**:
- Counter-based pod naming (e.g., `test-pod-1`, `test-pod-2`)
- Automatic base name extraction from existing pods
- CRIU dump/restore with external mount handling
- Automatic original pod deletion after successful migration
- Region label support for target pods

**Class**: `CriuMigrationTracker`

**Key Methods**:
- `perform_migration() -> bool` - Execute full migration workflow
- `build_criu_dump_command()` - Build CRIU dump command with mount discovery
- `build_criu_restore_command()` - Build CRIU restore command
- `create_target_pod_only()` - Create target pod with counter-based naming
- `perform_criu_dump()` - Execute CRIU dump on source container
- `execute_criu_restore_in_target()` - Execute CRIU restore in target pod
- `_delete_original_pod()` - Delete original pod after migration
- `_get_next_pod_name()` - Determine next pod name using counter

### Database Module (`controller/db/db.py`)

**Key Functions**:
- `connect_to_db(db_params: Dict) -> Connection` - Connect to PostgreSQL database
- `fetch_min_slope(conn, start_date, end_date)` - Fetch minimum carbon intensity records
- `fetch_region_slope(conn, start_date, end_date, source)` - Fetch region-specific records
- `collect_carbon_forecast(conn, start_date, end_date, scheduler_time)` - Collect carbon forecast data
- `table_exists(conn, table_name, schema)` - Check if table exists

**Database Configuration**:
- Host: `DB_HOST` (default: `db-service`)
- Port: `DB_PORT` (default: `5432`)
- Database: `DB_NAME` (default: `sfarokhi`)
- User: `DB_USER` (default: `sfarokhi`)
- Password: `DB_PASSWORD` (default: `wordpass`)

### Metadata Service (`controller/db/metadata.py`)

**HTTP Server**: Provides carbon intensity forecast data

**Endpoints**:
- `POST /` - Get combined minimum forecast with all region forecasts

**Request**:
```json
{
    "duration": 24  // Hours
}
```

**Response**:
```json
{
    "min_forecast": [
        {
            "source": "US-NE-ISNE",
            "datetime": "2021-01-01T00:00:00",
            "carbon_intensity_direct_avg": 123.45
        },
        ...
    ],
    "region_forecasts": {
        "US-NE-ISNE": [...],
        "US-TEN-TVA": [...],
        ...
    }
}
```

**Class**: `CarbonDataHandler`

**Key Methods**:
- `handle_combined_min_forecast(duration, storage_path)` - Generate combined forecast

### Data Upload Module (`controller/db/upload_data.py`)

**Function**: `main()`

**Purpose**: Upload carbon intensity CSV data to PostgreSQL database

**Usage**: Runs as Kubernetes Job to populate database with regional carbon data

## 🚀 Key Features

### Live Migration Capabilities
- **Complete State Preservation**: Full container state including memory, file system, and network connections
- **Mount Namespace Handling**: Intelligent discovery and handling of external bind mounts
- **Cross-Node Migration**: Seamless migration between KIND worker nodes
- **Process Continuity**: Maintain running processes and application state
- **Counter-Based Naming**: Automatic pod naming with incrementing counters (`test-pod-1`, `test-pod-2`, etc.)

### Carbon-Aware Scheduling
- **Real-Time Forecasts**: Query carbon intensity forecasts for multiple regions
- **Policy-Based Migration**: Three scheduling policies for different optimization strategies
- **Region Labeling**: Worker nodes labeled with regions (NE, TEN, CENT)
- **Forecast Comparison**: Compare total carbon intensity across regions over expected duration

### CRIU Integration
- **Process-Level Checkpointing**: Uses CRIU for complete process state capture
- **External Mount Support**: Handles Docker volumes and bind mounts during checkpoint/restore
- **Cgroup Yard Management**: Proper cgroup setup for CRIU operations
- **Container Runtime Integration**: Works with containerd via Kubernetes API

### KIND Cluster Optimization
- **Node-Specific Pods**: Migrator pods deployed on each KIND worker node with CRIU installed
- **Privileged Containers**: Full access to containerd socket, CRIU, and system resources
- **Host Path Volumes**: Checkpoint data sharing via host path volumes
- **Debug Pod Access**: Direct kubectl exec access to migrator pods for CRIU operations

## 🛠️ Technology Stack

- **Checkpoint/Restore**: CRIU (Checkpoint/Restore in Userspace)
- **Container Runtime**: containerd with Kubernetes API
- **Orchestration**: Kubernetes with KIND
- **Language**: Python 3.9+ with FastAPI
- **Database**: PostgreSQL for metadata storage
- **Scheduling**: APScheduler for periodic tasks
- **Monitoring**: Kubernetes metrics and structured logging
- **Build**: Docker containers with multi-stage builds

## 📋 Prerequisites

### Required Software Versions

- **Docker Desktop**: 4.0.0 or later
  - macOS: Download from [Docker Desktop for Mac](https://www.docker.com/products/docker-desktop)
  - Linux: Install Docker Engine 20.10+
  - Windows: Download from [Docker Desktop for Windows](https://www.docker.com/products/docker-desktop)

- **Kubernetes (via KIND)**: v1.27.0 or later
  - KIND version: v0.20.0 or later
  - Install: `brew install kind` (macOS) or download from [KIND releases](https://github.com/kubernetes-sigs/kind/releases)

- **kubectl**: v1.27.0 or later (must match Kubernetes version)
  - Install: `brew install kubectl` (macOS) or follow [kubectl installation guide](https://kubernetes.io/docs/tasks/tools/)

- **Python**: 3.9 or later
  - Install: `brew install python3` (macOS) or use system package manager

### System Requirements

- **RAM**: Minimum 8GB, recommended 16GB
- **CPU**: 4+ cores recommended
- **Disk**: 20GB+ free space for Docker images and checkpoints
- **OS**: 
  - **Linux (Ubuntu 20.04+)** - **Required for CRIU functionality**
  - macOS 10.15+ or Windows 10/11 with WSL2 - Can run KIND cluster, but CRIU migration requires Linux kernel
  - **Note**: CRIU only works on Linux systems. While KIND can run on macOS/Windows, the actual CRIU checkpoint/restore operations require a Linux kernel with sudo features (SYS_ADMIN capability, etc.)

## 🚀 Quick Start

### 1. Clone the Repository

```bash
git clone <repository-url>
cd KubeFlex
```

### 2. Build the Docker Images
**Note: you don't need to do this more than once, but you do need to use your own Docker profile**;
**Learn the basics here: [`Building Docker Images`](https://docs.docker.com/get-started/introduction/build-and-push-first-image/)**
```bash
./update.sh
```

### 3. Deploy the System

**Deploy everything (cluster, database, services)**:
```bash
cd src
./run.sh --all --include-cluster --include-db
```

**Deploy only migration components (assumes cluster exists)**:
```bash
cd src
./run.sh --migrate
```

**Deploy with specific scheduling policy**:
```bash
cd src
./run.sh --all --include-cluster --include-db --policy 3
```



### 5. Test Carbon Forecast & Migration

```bash# Port forward the metadata service
# Generate forecast
cd src
./test.sh --forecast 24
./test.sh --migration
```

## 🔧 Configuration

### Environment Variables

**Controller**:
- `SCHEDULING_POLICY`: Scheduling policy (1, 2, or 3, default: 3)
- `SCHEDULER_TIME`: Unix timestamp for scheduler clock (default: current time, clamped to data range)
- `MIGRATION_SERVICE_URL`: URL of migration service (default: `http://python-migrate-service:8000/live-migrate`)
- `CARBON_SERVER_URL`: URL of metadata service (default: `http://metadata-service:8008`)

**Database**:
- `DB_HOST`: Database host (default: `db-service`)
- `DB_PORT`: Database port (default: `5432`)
- `DB_NAME`: Database name (default: `sfarokhi`)
- `DB_USER`: Database user (default: `sfarokhi`)
- `DB_PASSWORD`: Database password (default: `wordpass`)

**Migration Service**:
- `CHECKPOINT_DIR`: Directory for checkpoint storage (default: `/tmp/checkpoints`)
- `NAMESPACE`: Kubernetes namespace (default: `test-namespace`)

### Scheduling Policies

Configure via `scheduler-config` ConfigMap or `--policy` flag:

1. **Policy 1 - Initial Placement Only**:
   - Assigns pods to lowest carbon region at runtime
   - No automatic migrations
   - Use case: Static workloads with known placement

2. **Policy 2 - Hourly Migration**:
   - Automatically migrates all pods to minimum region every hour
   - Simple and predictable
   - Use case: Always follow the current minimum

3. **Policy 3 - Forecast-Based** (Default):
   - Compares carbon forecasts for all regions over `EXPECTED_DURATION`
   - Migrates to region with lowest total carbon intensity
   - Use case: Optimize for long-running workloads

### CRIU Configuration

The system automatically configures CRIU for optimal migration:
- **Cgroup Yard**: Sets up `/cgroup-yard` for proper cgroup handling
- **External Mounts**: Automatically discovers and handles Docker volumes and bind mounts
- **Privileged Access**: Required capabilities for CRIU operations
- **Mount Namespace**: Intelligent mount point discovery and external mount mapping

### KIND Cluster Configuration

The system is optimized for KIND clusters with:
- 1 control-plane node
- 3 worker nodes (labeled as REGION=NE, REGION=TEN, REGION=CENT)
- Migrator pods with CRIU capabilities on each worker node
- Privileged containers for containerd socket access
- Host path volumes for checkpoint data sharing

## 📊 API Reference

### Migration Service API

**Base URL**: `http://python-migrate-service:8000`

#### `POST /live-migrate`

Perform CRIU-based pod migration.

**Request**:
```json
{
    "namespace": "test-namespace",
    "pod": "test-pod",
    "source_node": "kind-worker",
    "target_node": "kind-worker2",
    "target_region": "TEN",
    "delete_original": true,
    "debug": true
}
```

**Response**:
```json
{
    "success": true,
    "source_pod": "test-pod",
    "target_pod": "test-pod-1",
    "source_node": "kind-worker",
    "target_node": "kind-worker2",
    "namespace": "test-namespace",
    "migration_complete": true,
    "steps_completed": [
        "getting_node_information",
        "node_validation",
        "getting_source_container_info",
        "creating_target_pod",
        "performing_criu_dump",
        "transferring_checkpoint",
        "executing_criu_restore",
        "deleting_original_pod"
    ],
    "errors": [],
    "warnings": []
}
```

### Metadata Service API

**Base URL**: `http://metadata-service:8008`

#### `POST /`

Get combined carbon intensity forecast.

**Request**:
```json
{
    "duration": 24
}
```

**Response**:
```json
{
    "min_forecast": [
        {
            "source": "US-NE-ISNE",
            "datetime": "2021-01-01T00:00:00",
            "carbon_intensity_direct_avg": 123.45
        }
    ],
    "region_forecasts": {
        "US-NE-ISNE": [...],
        "US-TEN-TVA": [...],
        "US-CENT-SWPP": [...]
    }
}
```

## 📊 Monitoring and Observability

- **Structured Logging**: Comprehensive logging with state tracking and migration phases
- **CRIU Metrics**: Checkpoint creation, transfer, and restore statistics
- **Health Checks**: Service availability and readiness probes
- **Error Handling**: Detailed error reporting and recovery mechanisms
- **Migration State Tracking**: Real-time migration progress and status
- **Carbon Forecast Logging**: Forecast generation and region selection logging

## 🧪 Testing

### Run Migration Test

```bash
cd src
./test.sh --migrate --pod test-pod --source kind-worker --target kind-worker2
```

### Generate Carbon Forecast

```bash
cd src
./test.sh --forecast 24
```

### Run Full Test Suite

```bash
cd src
./test.sh --migrate --forecast 24 --pod test-pod
```

## 🔒 Security Considerations

- **Privileged Containers**: Required for containerd socket access and CRIU operations
- **RBAC**: Kubernetes role-based access control configured in `manifests/roles.yml`
- **Network Policies**: Secure inter-pod communication (can be added)
- **Resource Limits**: CPU and memory constraints defined in manifests
- **CRIU Capabilities**: SYS_ADMIN, CHECKPOINT_RESTORE, and other required capabilities

## 📈 Performance Characteristics

- **Migration Time**: Typically 10-30 seconds depending on container size and checkpoint data
- **Checkpoint Size**: Complete process state including memory pages and file descriptors
- **Resource Usage**: Low overhead during migration process with CRIU optimization
- **Scalability**: Supports multiple concurrent migrations with proper resource isolation
- **Forecast Query Time**: < 1 second for 24-hour forecasts
- **Data Range**: Historical data from 2020-01-01 to 2022-12-31 (hourly resolution)
- **Regional Coverage**: 14 major US power grid regions with 50+ sub-regions

## 🗑️ Cleanup

To remove all resources:

```bash
cd src
./delete.sh --all --include-cluster
```

To remove only services (keep cluster and database):

```bash
cd src
./delete.sh
```

## 📚 Documentation

This repository includes comprehensive documentation:

- **Main README** (`README.md`): This file - overview and quick start guide
- **Source Code README** (`src/README.md`): Usage guide, shell commands, and quick start
- **Architecture Documentation** (`src/ARCHITECTURE.md`): Detailed architecture, design choices, modules, limitations, and future work
- **Data Directory README** (`data/README.md`): Data structure, processing pipeline, benchmarking, and visualization tools

## ⚠️ Known Limitations

### System Limitations
- **KIND-Specific**: Designed for KIND clusters, may not work with production Kubernetes clusters
- **Historical Data**: Uses 2020-2022 carbon intensity data, no real-time integration
- **Fixed Node Configuration**: Assumes exactly 3 worker nodes with specific region labels
- **Single Namespace Focus**: Primarily tested with `test-namespace`

### Migration Limitations
- **CRIU Container Compatibility**: Migration currently only works with the specific testpod and its Docker image; not generic for arbitrary containers
- **CRIU Versioning**: CRIU versioning is sparsely supported and requires strict version/dependency management
- **Platform Requirements**: **CRIU only works on Linux systems - will not work on non-Linux machines** (macOS, Windows)
- **File Mounting**: Complex mount namespace handling with limitations on mount discovery and external mount migration
- **Network Limitations**: **TCP connections are not preserved** - active connections are lost during migration
- **State Preservation**: Some state may not be fully preserved; network connections are interrupted
- **Performance**: Migration time depends on container size (typically 10-30 seconds)

**Note**: Future iterations must address these CRIU-related limitations for broader applicability.

### Scheduling Limitations
- **Policy Constraints**: Only three predefined policies, no custom policy support
- **Forecast Accuracy**: Uses historical data, not real-time forecasts
- **Migration Cost**: Doesn't account for migration overhead in scheduling decisions

For detailed limitations and future work, see:
- [`src/ARCHITECTURE.md`](src/ARCHITECTURE.md#-shortcomings-and-limitations) - Architecture limitations and design constraints
- [`data/README.md`](data/README.md#-shortcomings-and-limitations) - Data limitations

## 🚀 Future Work

### Planned Enhancements
- Real-time carbon intensity data integration
- Support for production Kubernetes clusters
- Custom scheduling policy framework
- Enhanced migration performance and state preservation
- Multi-namespace and dynamic node support
- **CRIU Improvements**: Generic container migration support, TCP connection preservation, improved mount handling, better CRIU version management

For detailed future work plans, see:
- [`src/ARCHITECTURE.md`](src/ARCHITECTURE.md#-future-work) - Architecture and system enhancements
- [`data/README.md`](data/README.md#-future-work) - Data and analysis improvements

## 📚 Additional Resources

- [CRIU Documentation](https://criu.org/)
- [KIND Documentation](https://kind.sigs.k8s.io/)
- [Kubernetes API Documentation](https://kubernetes.io/docs/reference/)
- [FastAPI Documentation](https://fastapi.tiangolo.com/)

## 🤝 Contributing

Contributions are welcome! Please ensure:
- Code follows existing style and patterns
- Tests are added for new features
- Documentation is updated (including relevant README files)
- Migration compatibility is maintained

## 📄 License

[Add license information here]
