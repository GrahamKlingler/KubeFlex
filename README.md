# Flex-Nautilus
### Sallar Farokhi

We're using [cAdvisor](https://github.com/google/cadvisor) to monitor specific Kubernetes namespaces and containers. This tool provides real-time insights into container CPU, memory, and network usage.

## 📋 Prerequisites

- Kubernetes cluster
- Docker

## 🛠️ Installation

Go to `src/` and run:
```bash
./run.sh namespace=kube-system
```
This will boot up all of the necessary resources within /manifests
After that, you can visit the cAdvisor UI [here](http://localhost:30081)

In order to tear everything down, you simply run:
```bash
./delete.sh
```

## 🔍 Monitoring Specific Processes
You can narrow down the processes you want to observe based on the namespace. You do this with the `SELECTOR` arguments.

**NOTE**: If `SELECTOR` is not given, value is defaulted to `namespace=default`

The options are:
```yaml
namespace=<namespace>
```
In the example above, we observe all the internal pod processes within `kube-system`.
You can include multiple options with a comma-seperated list.

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