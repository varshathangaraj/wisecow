# Wisecow — Containerised K8s Deployment with CI/CD & TLS

[![CI/CD](https://img.shields.io/github/actions/workflow/status/YOUR_GITHUB_USERNAME/wisecow/ci-cd.yaml?label=CI%2FCD&logo=github-actions)](https://github.com/YOUR_GITHUB_USERNAME/wisecow/actions)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue)](LICENSE)

> AccuKnox DevOps Trainee Practical Assessment — Problem Statements 1, 2 & 3

---

## Repository Layout

```
wisecow/
├── wisecow.sh                          # Application source (cow wisdom HTTP server)
├── Dockerfile                          # Container image definition
├── k8s/
│   ├── namespace.yaml                  # Kubernetes namespace
│   ├── deployment.yaml                 # Deployment (2 replicas, rolling update)
│   ├── service.yaml                    # LoadBalancer service on port 80 → 4499
│   ├── ingress.yaml                    # Ingress with TLS (cert-manager)
│   ├── cluster-issuer.yaml             # Let's Encrypt ClusterIssuers
│   └── kubearmor-policy.yaml           # Zero-trust KubeArmor policy (PS3)
├── scripts/
│   ├── system_health_monitor.py        # PS2 Objective 1 — System health monitor
│   └── app_health_checker.py           # PS2 Objective 4 — Application health checker
└── .github/
    └── workflows/
        └── ci-cd.yaml                  # GitHub Actions CI/CD pipeline
```

---

## Problem Statement 1 — Containerisation & K8s Deployment

### Prerequisites

```bash
# Local tools
docker --version       # ≥ 24
kubectl version        # ≥ 1.28
minikube version       # or kind
```

### Quick Start — Local (Minikube)

```bash
# 1. Start a local cluster
minikube start --driver=docker

# 2. Enable addons
minikube addons enable ingress
minikube addons enable ingress-dns

# 3. Build image locally (optional — CI/CD does this automatically)
docker build -t wisecow:local .
minikube image load wisecow:local

# 4. Deploy
kubectl apply -f k8s/namespace.yaml
kubectl apply -f k8s/deployment.yaml
kubectl apply -f k8s/service.yaml

# 5. Access
minikube service wisecow-service -n wisecow
```

### Docker Build

```bash
# Build
docker build -t ghcr.io/<YOUR_GITHUB_USERNAME>/wisecow:latest .

# Run locally
docker run -p 4499:4499 ghcr.io/<YOUR_GITHUB_USERNAME>/wisecow:latest

# Visit http://localhost:4499
```

---

## TLS — Secure Communication (Challenge Goal)

TLS is handled at the **Ingress** layer using [cert-manager](https://cert-manager.io) and Let's Encrypt.

### Setup

```bash
# Install cert-manager
kubectl apply -f https://github.com/cert-manager/cert-manager/releases/latest/download/cert-manager.yaml

# Wait for cert-manager to be ready
kubectl wait --namespace cert-manager \
  --for=condition=Available deployment --all --timeout=120s

# Apply ClusterIssuers and Ingress
kubectl apply -f k8s/cluster-issuer.yaml
kubectl apply -f k8s/ingress.yaml -n wisecow
```

Edit `k8s/ingress.yaml` — replace `wisecow.example.com` with your real domain.

cert-manager will automatically provision and renew TLS certificates via ACME HTTP-01.

---

## CI/CD Pipeline

The GitHub Actions workflow at `.github/workflows/ci-cd.yaml` does the following on every push to `main`:

| Step | Description |
|------|-------------|
| Checkout | Clone the repo |
| Set up Buildx | Multi-arch Docker builds |
| Login to GHCR | Authenticate to GitHub Container Registry |
| Extract metadata | Generate tags (`latest`, `sha-<short>`, branch) |
| Build & Push | Build multi-arch image, push to GHCR |
| Deploy | Update K8s deployment via `kubectl set image` |
| Rollback | Auto-rollback if deployment fails |

### Required GitHub Secrets

| Secret | Description |
|--------|-------------|
| `KUBE_CONFIG` | Base64-encoded kubeconfig for your cluster |

```bash
# Encode your kubeconfig
cat ~/.kube/config | base64 -w 0
# Paste output as GITHUB_SECRET named KUBE_CONFIG
```

---

## Problem Statement 2 — Scripts

### Objective 1 — System Health Monitor

```bash
# Single check (exits 1 if any threshold exceeded)
python3 scripts/system_health_monitor.py

# Continuous mode — check every 60 seconds
python3 scripts/system_health_monitor.py --interval 60 --log /var/log/health.log

# Custom thresholds
python3 scripts/system_health_monitor.py --cpu 90 --memory 85 --disk 90
```

**Default Thresholds:**

| Metric | Default |
|--------|---------|
| CPU Usage | > 80% |
| Memory Usage | > 80% |
| Disk Usage (any partition) | > 85% |
| Zombie Processes | > 5 |

### Objective 4 — Application Health Checker

```bash
# Check a single URL
python3 scripts/app_health_checker.py --urls http://localhost:4499

# Check multiple URLs
python3 scripts/app_health_checker.py \
  --urls https://example.com https://api.example.com/health

# Continuous monitoring
python3 scripts/app_health_checker.py \
  --urls http://localhost:4499 \
  --interval 30 \
  --log /var/log/app-health.log

# Using a JSON config file
python3 scripts/app_health_checker.py --config health_config.json
```

**Example `health_config.json`:**
```json
{
  "endpoints": [
    {
      "name": "Wisecow App",
      "url": "http://wisecow.example.com",
      "timeout": 10,
      "expected_status": [200],
      "expected_body": "cow"
    }
  ]
}
```

**Exit Codes:**

| Code | Meaning |
|------|---------|
| 0 | All endpoints UP |
| 1 | One or more endpoints DOWN/DEGRADED |

---

## Problem Statement 3 — KubeArmor Zero-Trust Policy

The policy at `k8s/kubearmor-policy.yaml` enforces a **default-deny** posture and explicitly allows only what Wisecow legitimately needs.

### Policy Overview

| Policy | What it does |
|--------|-------------|
| `wisecow-process-policy` | Allows only: bash, socat, fortune, cowsay, openssl. Blocks: curl, wget, python, sudo, passwd, etc. |
| `wisecow-file-policy` | Read-only on `/usr/share/games/fortunes`, `/app`, `/etc`. Blocks writes to `/etc/passwd`, `/etc/shadow`. |
| `wisecow-network-policy` | Allows TCP (port 4499) and UDP (DNS). Blocks all other protocols. |
| `wisecow-syscall-policy` | Blocks dangerous capabilities: `net_admin`, `sys_admin`, `sys_ptrace`, `setuid`, `dac_override`. |

### Apply

```bash
# Install KubeArmor
helm repo add kubearmor https://kubearmor.github.io/charts
helm install kubearmor kubearmor/kubearmor -n kube-system

# Apply policy
kubectl apply -f k8s/kubearmor-policy.yaml

# Watch live violations
karmor log --logfilter policy --namespace wisecow
```

---

## License

[Apache 2.0](LICENSE)
