# Flex-Nautilus: Container Live Migration System

Flex-Nautilus is a Kubernetes-based container live migration system designed to enable seamless migration of running containers between nodes in a KIND (Kubernetes in Docker) cluster. The system uses containerd's native checkpoint/restore capabilities to perform live migrations without service interruption.

## 🎯 Project Goals

- **Zero-downtime Migration**: Migrate running containers between nodes without service interruption
- **Containerd Integration**: Leverage containerd's native checkpoint/restore functionality
- **KIND Cluster Support**: Optimized for Kubernetes in Docker (KIND) environments
- **Streaming Migration**: Perform incremental checkpoint transfers for efficient migration
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
│  │ • Live Migration│  │ • Orchestration │  │ • Metadata   │ │
│  │ • Checkpointing │  │ • Scheduling    │  │ • State      │ │
│  │ • Restore Logic │  │ • Monitoring    │  │ • History    │ │
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
│  │ │ • containerd│ │  │ │ • containerd│ │  │              │ │
│  │ └─────────────┘ │  │ └─────────────┘ │  │              │ │
│  └─────────────────┘  └─────────────────┘  └──────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

### Migration Flow

1. **Discovery**: Identify source container and target node
2. **Checkpoint Creation**: Create incremental checkpoints using `ctr tasks checkpoint`
3. **Data Transfer**: Stream checkpoint data between nodes via shared volumes
4. **Image Building**: Build new container image with checkpoint data
5. **Container Creation**: Create target container with migrated state
6. **Restore**: Restore container state from checkpoint data
7. **Verification**: Verify migration success and cleanup

## 🚀 Key Features

### Live Migration Capabilities
- **Streaming Checkpoints**: Multiple incremental checkpoints for minimal downtime
- **State Preservation**: Complete container state including memory, file system, and network
- **Cross-Node Migration**: Seamless migration between KIND worker nodes
- **Entrypoint Modification**: Prevent re-initialization of migrated containers

### Containerd Integration
- **Native Checkpoint/Restore**: Uses containerd's built-in checkpoint functionality
- **CRI Compatibility**: Works with Kubernetes CRI (Container Runtime Interface)
- **Task Management**: Direct interaction with containerd tasks and containers

### KIND Cluster Optimization
- **Node-Specific Pods**: Migrator pods deployed on each KIND worker node
- **Shared Volumes**: Checkpoint data sharing via host path volumes
- **Privileged Access**: Full access to containerd socket and system resources

## 📁 Project Structure

```
Flex-Nautilus/
├── src/
│   ├── controller/           # Main application code
│   │   ├── main.py          # Controller service
│   │   ├── migrate_service.py # Migration API service
│   │   └── utils/           # Utility modules
│   │       ├── kubeapi.py   # Kubernetes API interactions
│   │       └── live_migration.py # Core migration logic
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

- **Container Runtime**: containerd with CRIU checkpoint/restore
- **Orchestration**: Kubernetes with KIND
- **Language**: Python 3.9+ with FastAPI
- **Database**: PostgreSQL for metadata storage
- **Monitoring**: Kubernetes metrics and custom logging
- **Build**: Docker containers with multi-stage builds

## 🚀 Quick Start

### Prerequisites
- Docker and Docker Compose
- KIND (Kubernetes in Docker)
- kubectl
- Python 3.9+

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
     -d '{"pod": "test-pod", "target_node": "kind-worker2", "namespace": "foo"}'
   ```

### API Endpoints

- `GET /health` - Service health check
- `POST /live-migrate` - Perform live migration
- `GET /status` - Migration status and metrics

## 🔧 Configuration

### Environment Variables
- `KUBECONFIG`: Kubernetes configuration path
- `CHECKPOINT_DIR`: Directory for checkpoint storage
- `NAMESPACE`: Kubernetes namespace for deployment

### KIND Cluster Configuration
The system is optimized for KIND clusters with:
- Multiple worker nodes (`kind-worker`, `kind-worker2`)
- Region-based node labeling
- Shared storage for checkpoint data

## 📊 Monitoring and Observability

- **Structured Logging**: Comprehensive logging with state tracking
- **Migration Metrics**: Checkpoint creation, transfer, and restore statistics
- **Health Checks**: Service availability and readiness probes
- **Error Handling**: Detailed error reporting and recovery mechanisms

## 🧪 Testing and Benchmarking

The project includes comprehensive testing tools:
- **Performance Benchmarks**: Migration time and resource usage
- **Stress Testing**: High-load migration scenarios
- **Integration Tests**: End-to-end migration validation

## 🔒 Security Considerations

- **Privileged Containers**: Required for containerd socket access
- **RBAC**: Kubernetes role-based access control
- **Network Policies**: Secure inter-pod communication
- **Resource Limits**: CPU and memory constraints

## 📈 Performance Characteristics

- **Migration Time**: Typically 5-10 seconds for small containers
- **Checkpoint Size**: Optimized for minimal data transfer
- **Resource Usage**: Low overhead during migration process
- **Scalability**: Supports multiple concurrent migrations

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests for new functionality
5. Submit a pull request

## 📄 License

This project is licensed under the MIT License - see the LICENSE file for details.

## 🙏 Acknowledgments

- containerd project for checkpoint/restore capabilities
- Kubernetes community for KIND and CRI
- CRIU project for checkpoint/restore technology

---

**Flex-Nautilus**: Enabling seamless container migration in Kubernetes environments.
