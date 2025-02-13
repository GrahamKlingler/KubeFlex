# Flex-Nautilus
### Sallar Farokhi

We're using cAdvisor to monitor specific Kubernetes namespaces and containers. This tool provides real-time insights into container CPU, memory, and network usage.

## 📋 Prerequisites

- Kubernetes cluster
- Docker

## 🛠️ Installation

Go to `/src/manifests/` and create each of the objects, in THIS order:
```bash
kubectl apply -f namespace.yml
kubectl apply -f storage.yml
kubectl apply -f service.yml
kubectl apply -f cadvisor.yml
```

After that, visit the cAdvisor UI at `http://127.0.0.1:8080`

## ⚙️ Configuration

The deployment can be configured using the following environment variables:

| Variable | Description | Default |
|----------|-------------|---------|
| `POLLING_INTERVAL` | Metrics collection interval (seconds) | `300` |
| `POD_SELECTOR` | Kubernetes label selector for pods | `io.kubernetes.pod.namespace=foo` |

## 🔍 Monitoring Specific Namespaces

To monitor specific namespaces, modify the `POD_SELECTOR` environment variable in `cadvisor.yml`:

```yaml
- name: POD_SELECTOR
  value: "io.kubernetes.pod.namespace=your-namespace"
```

## 📊 Metrics Collected

### CPU Metrics
- Total usage
- User mode usage
- System mode usage

### Memory Metrics
- Current usage
- Maximum usage
- Cache
- RSS
- Swap
- Working set

### Network Metrics
- Transmitted bytes
- Received bytes
- Packets sent/received
- Network errors

## 🗄️ Data Storage

Metrics are stored in JSON format with the following structure:
```json
{
    "namespace/pod-name": {
        "cpu": {
            "total_usage": 123456,
            "user_mode_usage": 123456,
            "system_mode_usage": 123456
        },
        "memory": {
            "current_usage": 123456,
            "max_usage": 123456,
            ...
        },
        "network": {
            "tx_bytes": 123456,
            "rx_bytes": 123456,
            ...
        },
        "timestamp": "2025-02-13T05:31:32.137903198Z"
    }
}
```