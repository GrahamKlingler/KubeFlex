# Flex-Nautilus: Container Live Migration System

Flex-Nautilus is a Kubernetes-based container live migration system designed to enable seamless migration of running containers between nodes in a KIND (Kubernetes in Docker) cluster. The system uses CRIU (Checkpoint/Restore in Userspace) to perform live migrations without service interruption.

## 🎯 Project Goals

- **Zero-downtime Migration**: Migrate running containers between nodes without service interruption
- **CRIU Integration**: Leverage CRIU (Checkpoint/Restore in Userspace) for process-level checkpointing
- **KIND Cluster Support**: Optimized for Kubernetes in Docker (KIND) environments
- **Live Migration**: Perform complete container state migration with memory preservation
- **Production Ready**: Robust error handling, logging, and monitoring capabilities

## 🏗️ Architecture Overview

### Core Components

```
┌─────────────────────────────────────────────────────────────┐
│                    Flex-Nautilus System                     │
├─────────────────────────────────────────────────────────────┤
│  ┌─────────────────┐  ┌─────────────────┐  ┌──────────────┐ │
│  │Migration Service│  │   Controller    │  │   Database   │ │
│  │                 │  │                 │  │              │ │
│  │• Live Migration │  │ • Orchestration │  │ • Metadata   │ │
│  │• CRIU Checkpoint│  │ • Scheduling    │  │ • State      │ │
│  │• Process Restore│  │ • Monitoring    │  │ • History    │ │
│  └─────────────────┘  └─────────────────┘  └──────────────┘ │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    KIND Cluster                             │
├─────────────────────────────────────────────────────────────┤
│  ┌─────────────────┐  ┌─────────────────┐  ┌──────────────┐ │
│  │ kind-worker     │  │ kind-worker2    │  │ kind-control │ │
│  │                 │  │                 │  │              │ │
│  │ ┌─────────────┐ │  │ ┌─────────────┐ │  │              │ │
│  │ │Migrator Pod │ │  │ │Migrator Pod │ │  │              │ │
│  │ │             │ │  │ │             │ │  │              │ │
│  │ │ • ctr       │ │  │ │ • ctr       │ │  │              │ │
│  │ │ • crictl    │ │  │ │ • crictl    │ │  │              │ │
│  │ │ • CRIU      │ │  │ │ • CRIU      │ │  │              │ │
│  │ └─────────────┘ │  │ └─────────────┘ │  │              │ │
│  └─────────────────┘  └─────────────────┘  └──────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

### Migration Flow

1. **Discovery**: Identify source container and target node using crictl
2. **Mount Analysis**: Discover container mount paths and external bind mounts
3. **Target Pod Creation**: Create target pod with CRIU capabilities and privileged access
4. **CRIU Checkpoint**: Create complete container checkpoint using `criu dump` with external mount handling
5. **Data Transfer**: Transfer checkpoint data and script data between nodes via kubectl cp
6. **CRIU Restore**: Restore container state using `criu restore` with matching mount configuration
7. **Verification**: Verify migration success and cleanup resources

## 🚀 Key Features

### Live Migration Capabilities
- **Complete State Preservation**: Full container state including memory, file system, and network connections
- **Mount Namespace Handling**: Intelligent discovery and handling of external bind mounts
- **Cross-Node Migration**: Seamless migration between KIND worker nodes
- **Process Continuity**: Maintain running processes and application state

### CRIU Integration
- **Process-Level Checkpointing**: Uses CRIU for complete process state capture
- **External Mount Support**: Handles Docker volumes and bind mounts during checkpoint/restore
- **Cgroup Yard Management**: Proper cgroup setup for CRIU operations
- **Container Runtime Integration**: Works with containerd via crictl and ctr

### KIND Cluster Optimization
- **Node-Specific Pods**: Migrator pods deployed on each KIND worker node with CRIU installed
- **Privileged Containers**: Full access to containerd socket, CRIU, and system resources
- **Host Path Volumes**: Checkpoint data sharing via host path volumes
- **Debug Pod Access**: Direct kubectl exec access to migrator pods for CRIU operations

## 📁 Project Structure

```
Flex-Nautilus/
├── src/
│   ├── controller/           # Main application code
│   │   ├── main.py          # Controller service
│   │   ├── migrate_service.py # Migration API service
│   │   └── utils/           # Utility modules
│   │       ├── db.py           # Database utilities
│   │       ├── metadata.py     # Metadata management
│   │       └── live_migration.py # CRIU-based migration logic
│   ├── manifests/           # Kubernetes manifests
│   │   ├── cluster.yml      # KIND cluster configuration
│   │   ├── python-migrate.yml # Migration service deployment
│   │   ├── migrator.yml     # Migrator pod template
│   │   ├── controller.yml   # Controller deployment
│   │   └── storage.yml      # Database and storage
│   ├── build/               # Build configurations
│   │   ├── Dockerfile.migrate # Migration service image
│   │   └── start.sh         # Service startup script
│   └── run.sh               # Main deployment script
├── data/                    # Data processing and visualization
└── benchmark/               # Performance testing tools
```

## 🛠️ Technology Stack

- **Checkpoint/Restore**: CRIU (Checkpoint/Restore in Userspace)
- **Container Runtime**: containerd with crictl and ctr tools
- **Orchestration**: Kubernetes with KIND
- **Language**: Python 3.9+ with FastAPI
- **Database**: PostgreSQL for metadata storage
- **Monitoring**: Kubernetes metrics and structured logging
- **Build**: Docker containers with multi-stage builds

## 🚀 Quick Start

### Prerequisites
- Docker and Docker Compose
- KIND (Kubernetes in Docker)
- kubectl
- Python 3.9+
- CRIU installed in migrator pods (handled automatically)

### Deployment

1. **Deploy the entire system**:
   ```bash
   cd src
   ./run.sh --all
   ```

2. **Deploy only migration components**:
   ```bash
   cd src
   ./run.sh --migrate
   ```

3. **Test the migration service**:
   ```bash
   kubectl port-forward -n monitor svc/python-migrate-service 8000:8000
   curl -X POST http://localhost:8000/live-migrate \
     -H "Content-Type: application/json" \
     -d '{"pod": "test-pod", "target_node": "kind-worker2", "namespace": "test-namespace"}'
   ```

### API Endpoints

- `GET /health` - Service health check
- `POST /live-migrate` - Perform live migration
- `GET /status` - Migration status and metrics

## 🔧 Configuration

### Environment Variables
- `KUBECONFIG`: Kubernetes configuration path
- `CHECKPOINT_DIR`: Directory for checkpoint storage (default: `/tmp/checkpoints`)
- `NAMESPACE`: Kubernetes namespace for deployment

### CRIU Configuration
The system automatically configures CRIU for optimal migration:
- **Cgroup Yard**: Sets up `/cgroup-yard` for proper cgroup handling
- **External Mounts**: Automatically discovers and handles Docker volumes and bind mounts
- **Privileged Access**: Required capabilities for CRIU operations
- **Mount Namespace**: Intelligent mount point discovery and external mount mapping

### KIND Cluster Configuration
The system is optimized for KIND clusters with:
- Multiple worker nodes (`kind-worker`, `kind-worker2`)
- Migrator pods with CRIU capabilities on each worker node
- Privileged containers for containerd socket access
- Host path volumes for checkpoint data sharing

## 📊 Monitoring and Observability

- **Structured Logging**: Comprehensive logging with state tracking and migration phases
- **CRIU Metrics**: Checkpoint creation, transfer, and restore statistics
- **Health Checks**: Service availability and readiness probes
- **Error Handling**: Detailed error reporting and recovery mechanisms
- **Migration State Tracking**: Real-time migration progress and status

## 🧪 Testing and Benchmarking

The project includes comprehensive testing tools:
- **Performance Benchmarks**: Migration time and resource usage
- **Stress Testing**: High-load migration scenarios
- **Integration Tests**: End-to-end migration validation

## 🔒 Security Considerations

- **Privileged Containers**: Required for containerd socket access and CRIU operations
- **RBAC**: Kubernetes role-based access control
- **Network Policies**: Secure inter-pod communication
- **Resource Limits**: CPU and memory constraints
- **CRIU Capabilities**: SYS_ADMIN, CHECKPOINT_RESTORE, and other required capabilities

## 📈 Performance Characteristics

- **Migration Time**: Typically 10-30 seconds depending on container size and checkpoint data
- **Checkpoint Size**: Complete process state including memory pages and file descriptors
- **Resource Usage**: Low overhead during migration process with CRIU optimization
- **Scalability**: Supports multiple concurrent migrations with proper resource isolation
