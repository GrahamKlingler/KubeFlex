# KubeFlex Architecture Documentation

This document describes the architecture, design choices, limitations, and future work for the KubeFlex carbon-aware container live migration system.

## 🏗️ System Architecture

### High-Level Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    KubeFlex System                          │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌─────────────────┐  ┌─────────────────┐  ┌──────────────┐ │
│  │   Controller    │  │ Migration       │  │  Database    │ │
│  │   Service       │  │ Service         │  │  Service     │ │
│  │                 │  │                 │  │              │ │
│  │ • Scheduling    │  │ • CRIU          │  │ • PostgreSQL │ │
│  │ • Policy        │  │ • Checkpoint    │  │ • Metadata   │ │
│  │ • Orchestration │  │ • Restore       │  │ • Queries    │ │
│  └─────────────────┘  └─────────────────┘  └──────────────┘ │
│                                                             │
│  ┌─────────────────┐                                        │
│  │  Metadata       │                                        │
│  │  Service        │                                        │
│  │                 │                                        │
│  │ • Forecasts     │                                        │
│  │ • Region Data   │                                        │
│  └─────────────────┘                                        │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    KIND Cluster                             │
├─────────────────────────────────────────────────────────────┤
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐       │
│  │ kind-worker  │  │ kind-worker2 │  │ kind-worker3 │       │
│  │ (REGION=NE)  │  │ (REGION=TEN) │  │ (REGION=CENT)│       │
│  │              │  │              │  │              │       │
│  │ ┌──────────┐ │  │ ┌──────────┐ │  │ ┌──────────┐ │       │
│  │ │Migrator  │ │  │ │Migrator  │ │  │ │Migrator  │ │       │
│  │ │Pod       │ │  │ │Pod       │ │  │ │Pod       │ │       │
│  │ │          │ │  │ │          │ │  │ │          │ │       │
│  │ │• ctr     │ │  │ │• ctr     │ │  │ │• ctr     │ │       │
│  │ │• crictl  │ │  │ │• crictl  │ │  │ │• crictl  │ │       │
│  │ │• CRIU    │ │  │ │• CRIU    │ │  │ │• CRIU    │ │       │
│  │ └──────────┘ │  │ └──────────┘ │  │ └──────────┘ │       │
│  └──────────────┘  └──────────────┘  └──────────────┘       │
└─────────────────────────────────────────────────────────────┘
```

### Component Interaction Flow

```
Controller (main.py)
    │
    ├─→ Queries Metadata Service (metadata.py)
    │       │
    │       └─→ Queries Database (db.py)
    │
    ├─→ Calls Migration Service (migrate_service.py)
    │       │
    │       └─→ Executes CRIU Migration (live_migration.py)
    │               │
    │               ├─→ Uses Migrator Pods on KIND nodes
    │               ├─→ Performs CRIU dump on source
    │               ├─→ Transfers checkpoint data
    │               └─→ Performs CRIU restore on target
    │
    └─→ Manages Scheduling Policies
            │
            ├─→ Policy 1: Initial placement only
            ├─→ Policy 2: Hourly migration
            └─→ Policy 3: Forecast-based migration
```

## 📊 System Modules

### 1. Controller Module (`controller/controller/main.py`)

**Class**: `KubeFlexController`

**Purpose**: Main orchestration and scheduling logic for carbon-aware pod migration

**Key Responsibilities**:
- Initialize connections to Kubernetes, database, and services
- Implement three scheduling policies
- Coordinate pod migrations based on carbon intensity
- Manage simulation time and real-time scheduling
- Track migration history and performance

**Key Methods**:
- `__init__(scheduler_time, scheduling_policy)`: Initialize controller
- `initialize()`: Set up connections and start scheduler
- `migrate_pod()`: Trigger pod migration to target node
- `hourly_migration_check()`: Periodic migration check
- `get_minimum_region_from_metadata()`: Get current minimum carbon region
- `get_optimal_region_for_pod_forecast()`: Forecast-based region selection
- `run_migration_test()`: Run migration test workflow

**Scheduling Policies**:
1. **Policy 1**: Initial placement only - Assign pods to lowest region at runtime
2. **Policy 2**: Hourly migration - Migrate all pods to minimum region every hour
3. **Policy 3**: Forecast-based - Compare forecasts and migrate to optimal region

**Dependencies**:
- `kubernetes`: Kubernetes API client
- `apscheduler`: Background job scheduling
- `requests`: HTTP client for service communication
- `pytz`: Timezone handling

### 2. Migration Service (`controller/migrator/migrate_service.py`)

**Purpose**: FastAPI REST API for pod migration requests

**Key Features**:
- RESTful API for migration operations
- Request validation using Pydantic models
- Integration with CRIU migration logic
- Health check and service information endpoints

**Endpoints**:
- `GET /`: Root endpoint with service info
- `GET /health`: Health check
- `GET /info`: Service information
- `POST /live-migrate`: Perform CRIU-based migration

**Request Model**:
```python
{
    "namespace": str,
    "pod": str,
    "source_node": str,
    "target_node": str,
    "target_pod": Optional[str],
    "target_region": Optional[str],
    "delete_original": bool,
    "debug": bool
}
```

**Dependencies**:
- `fastapi`: Web framework
- `uvicorn`: ASGI server
- `pydantic`: Data validation

### 3. Live Migration Module (`controller/migrator/live_migration.py`)

**Purpose**: CRIU-based container migration implementation

**Key Features**:
- Complete container state checkpointing using CRIU
- Cross-node migration in KIND clusters
- Mount namespace discovery and handling
- Counter-based pod naming (e.g., `test-pod-1`, `test-pod-2`)
- Automatic original pod deletion

**Class**: `CriuMigrationTracker`

**Key Methods**:
- `perform_migration()`: Execute full migration workflow
- `build_criu_dump_command()`: Build CRIU dump command with mounts
- `build_criu_restore_command()`: Build CRIU restore command
- `create_target_pod_only()`: Create target pod with counter naming
- `perform_criu_dump()`: Execute CRIU dump on source
- `execute_criu_restore_in_target()`: Execute CRIU restore on target
- `_delete_original_pod()`: Delete original pod after migration
- `_get_next_pod_name()`: Determine next pod name using counter

**Migration Flow**:
1. Discover source container and mounts
2. Create target pod with counter-based name
3. Perform CRIU dump on source container
4. Transfer checkpoint data to target node
5. Execute CRIU restore in target container
6. Delete original pod (if requested)
7. Verify migration success

**Dependencies**:
- `kubernetes`: Kubernetes API client
- `subprocess`: Execute commands in migrator pods
- `tarfile`: Archive checkpoint data

### 4. Database Module (`controller/db/db.py`)

**Purpose**: PostgreSQL database utilities and queries

**Key Functions**:
- `connect_to_db()`: Connect to PostgreSQL database
- `fetch_min_slope()`: Fetch minimum carbon intensity records
- `fetch_region_slope()`: Fetch region-specific records
- `collect_carbon_forecast()`: Collect carbon forecast data
- `table_exists()`: Check if table exists

**Database Functions**:
- `get_min_intensity_records()`: PostgreSQL function for minimum intensity
- `get_records_by_source()`: PostgreSQL function for region-specific data

**Database Configuration**:
- Host: `DB_HOST` (default: `db-service`)
- Port: `DB_PORT` (default: `5432`)
- Database: `DB_NAME` (default: `sfarokhi`)
- User: `DB_USER` (default: `sfarokhi`)
- Password: `DB_PASSWORD` (default: `wordpass`)

**Dependencies**:
- `psycopg2`: PostgreSQL adapter

### 5. Metadata Service (`controller/db/metadata.py`)

**Purpose**: HTTP service providing carbon intensity forecast data

**Key Features**:
- RESTful API for forecast queries
- Combined minimum and region-specific forecasts
- Integration with PostgreSQL database

**Endpoints**:
- `POST /`: Get combined minimum forecast with all region forecasts

**Request**:
```json
{
    "duration": 24  // Hours
}
```

**Response**:
```json
{
    "min_forecast": [...],
    "region_forecasts": {
        "US-NE-ISNE": [...],
        "US-TEN-TVA": [...],
        ...
    }
}
```

**Class**: `CarbonDataHandler`

**Key Methods**:
- `handle_combined_min_forecast()`: Generate combined forecast

**Dependencies**:
- `fastapi`: Web framework
- `uvicorn`: ASGI server
- `psycopg2`: PostgreSQL adapter

### 6. Data Upload Module (`controller/db/upload_data.py`)

**Purpose**: Upload carbon intensity CSV data to PostgreSQL

**Key Features**:
- Reads CSV files from data directory
- Transforms and normalizes data
- Bulk inserts into PostgreSQL
- Runs as Kubernetes Job

**Usage**:
- Deployed as Kubernetes Job
- Processes CSV files from `data/regions/`
- Populates `public.table` in PostgreSQL

**Dependencies**:
- `psycopg2`: PostgreSQL adapter
- `pandas`: CSV processing

## 🔌 Module Interfaces

### Controller → Migration Service

**Interface**: HTTP REST API
- **Endpoint**: `POST /live-migrate`
- **Request**: `MigrateRequest` model
- **Response**: Migration result with status and details

### Controller → Metadata Service

**Interface**: HTTP REST API
- **Endpoint**: `POST /`
- **Request**: `{"duration": int}`
- **Response**: Forecast data with min_forecast and region_forecasts

### Metadata Service → Database

**Interface**: PostgreSQL connection
- **Functions**: `get_min_intensity_records()`, `get_records_by_source()`
- **Queries**: Carbon intensity data queries

### Migration Service → Kubernetes API

**Interface**: Kubernetes Python client
- **Operations**: Pod creation, deletion, exec
- **Resources**: Pods, containers, nodes

### Migration Service → CRIU

**Interface**: Command-line execution via kubectl exec
- **Commands**: `criu dump`, `criu restore`
- **Execution**: Inside migrator pods on KIND nodes

## 🏛️ Cluster Design Choices

### KIND Cluster Architecture

**Design Decision**: Use KIND (Kubernetes in Docker) for local development and testing

**Rationale**:
- Enables local Kubernetes cluster without cloud resources
- Simplifies development and testing workflow
- Allows full control over cluster configuration
- Supports privileged containers required for CRIU

**Configuration**:
- **Control Plane**: 1 node
- **Worker Nodes**: 3 nodes (kind-worker, kind-worker2, kind-worker3)
- **Node Labels**: Each worker node labeled with region (REGION=NE, REGION=TEN, REGION=CENT)
- **Network**: Default KIND networking with pod-to-pod communication

### Node Region Mapping

**Design Decision**: Map each KIND worker node to a US power grid region

**Mapping**:
- `kind-worker` → `REGION=NE` (Northeast - US-NE-ISNE)
- `kind-worker2` → `REGION=TEN` (Tennessee - US-TEN-TVA)
- `kind-worker3` → `REGION=CENT` (Central - US-CENT-SWPP)

**Rationale**:
- Enables carbon-aware scheduling based on regional carbon intensity
- Simplifies region selection for pod placement
- Allows testing of migration policies across regions

### Migrator Pod Design

**Design Decision**: Deploy migrator pods as DaemonSet on each worker node

**Rationale**:
- Ensures CRIU tools available on every node
- Provides privileged access to containerd socket
- Enables direct container manipulation via ctr and crictl
- Simplifies migration execution without node-specific configuration

**Capabilities**:
- Privileged containers with SYS_ADMIN, CHECKPOINT_RESTORE capabilities
- Host path volumes for checkpoint data sharing
- Direct access to containerd socket
- CRIU, ctr, and crictl tools pre-installed

### Namespace Design

**Design Decision**: Use separate namespaces for system components and test workloads

**Namespaces**:
- `monitor`: System components (controller, migration service, database, metadata service)
- `test-namespace`: Test pods for migration testing

**Rationale**:
- Separation of concerns
- Easier resource management
- Clear distinction between system and workload pods

### Database Design

**Design Decision**: Use PostgreSQL for carbon intensity data storage

**Schema**:
- Single table `public.table` with carbon intensity records
- Columns: `source`, `datetime`, `carbon_intensity_direct_avg`, and other metrics
- PostgreSQL functions for efficient querying

**Rationale**:
- Relational database provides structured data storage
- PostgreSQL functions enable efficient minimum and region-specific queries
- Supports time-series queries for forecast generation

### Service Communication

**Design Decision**: Use HTTP REST APIs for inter-service communication

**Services**:
- Migration Service: FastAPI on port 8000
- Metadata Service: FastAPI on port 8008
- Controller: Direct HTTP calls to services

**Rationale**:
- Simple and standard communication pattern
- Easy to test and debug
- Language-agnostic (though all services are Python)
- Supports future service replacement

### Scheduling Policy Design

**Design Decision**: Implement three distinct scheduling policies

**Policies**:
1. **Policy 1**: Initial placement only - Static assignment at runtime
2. **Policy 2**: Hourly migration - Reactive migration every hour
3. **Policy 3**: Forecast-based - Proactive migration based on forecasts

**Rationale**:
- Allows comparison of different scheduling strategies
- Policy 1: Baseline with no migration overhead
- Policy 2: Simple reactive approach
- Policy 3: Optimized for long-running workloads

### Pod Naming Strategy

**Design Decision**: Use counter-based pod naming for migrations

**Pattern**: `{base-name}-{counter}` (e.g., `test-pod-1`, `test-pod-2`)

**Rationale**:
- Prevents naming conflicts during migration
- Allows tracking of migration history
- Simplifies target pod creation

## ⚠️ Shortcomings and Limitations

### Migration Limitations

1. **CRIU Container Compatibility**:
   - **Limited Container Support**: CRIU migration currently only works with the specific testpod and its associated Docker image
   - **Image-Specific**: The migration system is tightly coupled to the testpod's container image configuration
   - **No Generic Migration**: Cannot migrate arbitrary containers without significant modification
   - **Container Requirements**: Containers must be built with CRIU compatibility in mind (specific entrypoints, mount configurations, etc.)

2. **CRIU Versioning and Compatibility**:
   - **Sparse Version Support**: CRIU versioning is sparsely supported across different Linux distributions and kernel versions
   - **Strict Download Requirements**: Requires a strict list of specific CRIU versions and dependencies
   - **Version Locking**: System is locked to specific CRIU versions that are known to work
   - **Dependency Management**: Upgrading CRIU versions requires extensive testing and may break existing functionality
   - **Kernel Version Dependency**: CRIU requires specific kernel features and versions, limiting portability

3. **System Requirements and Platform Limitations**:
   - **Linux-Only**: CRIU only works on Linux systems - **will not work on non-Linux machines** (macOS, Windows)
   - **Kernel Requirements**: Requires specific Linux kernel features (CHECKPOINT_RESTORE, namespaces, etc.)
   - **Architecture Constraints**: Limited to x86_64 architecture in most cases
   - **Host System Dependency**: The host system must be Linux-based, even when using KIND (which runs Linux containers)

4. **File Mounting Process Limitations**:
   - **Mount Namespace Complexity**: File mounting process is complex and may not handle all mount types correctly
   - **External Mount Discovery**: Automatic mount discovery may miss certain mount configurations
   - **Bind Mount Handling**: Bind mounts require careful mapping between source and target nodes
   - **Volume Migration**: Persistent volumes and external storage may not migrate correctly
   - **Mount Point Conflicts**: Potential conflicts when restoring mounts on target node

5. **Network and Connection Limitations**:
   - **No TCP Connection Preservation**: **TCP connections are not preserved during migration**
   - **Network State Loss**: Active network connections are lost during checkpoint/restore
   - **Service Disruption**: Applications with persistent connections will experience connection drops
   - **Network Namespace Migration**: Network namespace migration is complex and may not fully restore network state
   - **IP Address Changes**: Container IP addresses may change after migration, requiring service discovery updates

6. **State Preservation**:
   - Some state may not be fully preserved beyond network connections
   - File system changes during migration may cause issues
   - Process state may be incomplete for certain application types

7. **Performance**:
   - Migration time depends on container size
   - Checkpoint data transfer can be slow
   - No incremental checkpointing

8. **Error Recovery**:
   - Limited rollback capabilities
   - Failed migrations may leave orphaned resources
   - No automatic retry mechanism

**Note**: Future iterations of this project will need to address all of these CRIU-related limitations, including:
- Generic container migration support beyond the testpod
- Better CRIU version management and compatibility testing
- Cross-platform considerations (though CRIU itself is Linux-only, the orchestration layer could be more portable)
- Improved mount handling and discovery
- TCP connection preservation or application-level reconnection mechanisms
- Enhanced state preservation for various application types

### Scheduling Limitations

1. **Policy Limitations**:
   - Only three predefined policies
   - To change the policy, the scheduler must be reran
   - Policy 3 requires `EXPECTED_DURATION` annotation

2. **Migration Cost**:
   - Doesn't account for migration overhead
   - No cost-benefit analysis

### Database Limitations

1. **Data Range**:
   - Limited to 2020-2022 data
   - No real-time data integration
   - System time must be within data range

2. **Query Performance**:
   - No caching layer
   - Queries may be slow for large date ranges
   - No query optimization

3. **Data Quality**:
   - No data validation on insert
   - Missing data not handled gracefully
   - No data freshness monitoring

### Service Limitations

1. **Scalability**:
   - Single instance of each service
   - No horizontal scaling
   - No load balancing

2. **High Availability**:
   - No redundancy
   - Single point of failure for each service
   - No automatic failover

3. **Monitoring**:
   - Limited observability
   - No distributed tracing
   - Basic logging only

### Architecture Limitations

1. **KIND-Specific**:
   - System designed specifically for KIND clusters
   - May not work with production Kubernetes clusters
   - Relies on Docker-in-Docker architecture

2. **Single Namespace Focus**:
   - Primarily tested with `test-namespace`
   - Limited multi-namespace support
   - Namespace configuration not fully dynamic

3. **Node Assumptions**:
   - Assumes exactly 3 worker nodes
   - Hardcoded node names (kind-worker, kind-worker2, kind-worker3)
   - Region labels must match expected values

## 🚀 Future Work

### Architecture Improvements

1. **Production Kubernetes Support**:
   - Support for standard Kubernetes clusters
   - Remove KIND-specific assumptions
   - Support for cloud providers (GKE, EKS, AKS)

2. **Multi-Namespace Support**:
   - Dynamic namespace configuration
   - Namespace-specific policies
   - Cross-namespace migration support

3. **Dynamic Node Management**:
   - Support for variable number of nodes
   - Dynamic node discovery
   - Automatic region labeling

### Migration Enhancements

1. **CRIU Compatibility Improvements**:
   - Generic container migration support (beyond testpod)
   - Container compatibility testing framework
   - Automated CRIU version compatibility validation
   - Support for multiple container image types

2. **Advanced CRIU Features**:
   - Incremental checkpointing
   - Pre-copy migration
   - Network namespace migration improvements
   - TCP connection preservation mechanisms
   - Application-level reconnection handling

3. **Mount and Storage Improvements**:
   - Enhanced mount discovery and handling
   - Support for all mount types (bind, volume, tmpfs, etc.)
   - Persistent volume migration strategies
   - Mount conflict resolution

4. **Migration Optimization**:
   - Parallel migration support
   - Migration scheduling and queuing
   - Bandwidth-aware migration

5. **State Management**:
   - Enhanced state preservation
   - Migration rollback capabilities
   - State verification and validation

6. **Performance Improvements**:
   - Compression for checkpoint data
   - Deduplication of transferred data
   - Migration time prediction

### Scheduling Enhancements

1. **Policy Framework**:
   - Custom policy definition
   - Policy composition
   - Machine learning-based policies

2. **Forecast Improvements**:
   - Real-time data integration
   - Uncertainty quantification
   - Multiple forecast models

3. **Cost-Aware Scheduling**:
   - Migration cost modeling
   - Cost-benefit analysis
   - Multi-objective optimization

### Database Improvements

1. **Real-Time Data**:
   - Integration with live APIs
   - Streaming data updates
   - Data freshness guarantees

2. **Performance**:
   - Redis caching layer
   - Query optimization
   - Materialized views

3. **Data Quality**:
   - Data validation pipelines
   - Missing data handling
   - Data quality metrics

### Service Improvements

1. **Scalability**:
   - Horizontal scaling support
   - Load balancing
   - Service mesh integration

2. **High Availability**:
   - Multi-instance deployments
   - Automatic failover
   - Health check improvements

3. **Observability**:
   - Distributed tracing (Jaeger, Zipkin)
   - Metrics collection (Prometheus)
   - Advanced logging (ELK stack)

### Testing and Validation

1. **Test Coverage**:
   - Unit tests for all modules
   - Integration tests
   - End-to-end tests

2. **Performance Testing**:
   - Load testing
   - Stress testing
   - Migration performance benchmarks

3. **Chaos Engineering**:
   - Failure injection
   - Network partition testing
   - Resource constraint testing

## 📚 Related Documentation

- Main README: `../README.md`
- Source Code README: `README.md` (usage and commands)
- Data README: `../data/README.md`
- Kubernetes Documentation: https://kubernetes.io/docs/
- CRIU Documentation: https://criu.org/
- KIND Documentation: https://kind.sigs.k8s.io/

