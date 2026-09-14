# NetworkTracing Bootstrap Server (Port 30105)

A standalone, lightweight HTTP distribution server for zero-friction NetworkTracing agent installation across fleet nodes.

## Features

- **Port 30105**: Dedicated bootstrap & distribution server, separate from telemetry ingestion & dashboard on active hub port `:30102`.
- **One-Liner Agent Bootstrap**: Instant deployment on any remote host without manual file copying.
- **Dynamic Endpoint Target**: The bootstrap script automatically downloads from port 30105 and targets the active hub at port 30102 (the legacy port `:31115` is obsolete and unused).
- **Pure POSIX `/bin/sh`**: Compatible with any standard Linux environment. Supports both `curl` and `wget`.
- **Zero code changes**: Operates in this dedicated `bootstrap/` folder without modifying any core repository code.

## Quick Start

### Start Server
```sh
sh bootstrap/start.sh
```

Or run in foreground:
```sh
python3 bootstrap/nt-bootstrap.py
```

Or install as systemd service:
```sh
sudo cp bootstrap/networktracing-bootstrap.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now networktracing-bootstrap.service
```

### Stop Server
```sh
sh bootstrap/stop.sh
```

## Agent Installation Commands (on Target Nodes)

### Modern Nodes (Kernel >= 5.5, eBPF)
```sh
# Install and start:
curl -sSf http://<HUB_IP>:30105/bootstrap | sudo -n sh

# Preflight check only (dry-run):
curl -sSf http://<HUB_IP>:30105/bootstrap | sudo -n sh -s -- --check

# Uninstall agent:
curl -sSf http://<HUB_IP>:30105/bootstrap | sudo -n sh -s -- --uninstall
```

### Legacy Nodes (CentOS 6.x / Kernel 2.6.32+)
```sh
# One-line install and start (auto-detects Hub IP & port 30102):
curl -sSf http://<HUB_IP>:30105/oldkernel/bootstrap | sudo -n sh

# Preflight check only (dry-run):
curl -sSf http://<HUB_IP>:30105/oldkernel/bootstrap | sudo -n sh -s -- --check

# Custom options (e.g. C++ mode, custom interface, ports, CPU core):
curl -sSf http://<HUB_IP>:30105/oldkernel/bootstrap | sudo -n sh -s -- --mode cpp --iface eth0 --ports 80,8080 --cpu 2

# Uninstall legacy agent:
curl -sSf http://<HUB_IP>:30105/oldkernel/bootstrap | sudo -n sh -s -- --uninstall
```

## HTTP Endpoints (:30105)

| Endpoint | Method | Purpose |
|---|---|---|
| `/` | GET | Quick guide & copy-paste one-liners |
| `/bootstrap` or `/bootstrap.sh` | GET | Dynamic POSIX shell bootstrap script (modern eBPF agent) |
| `/oldkernel/bootstrap` or `/bootstrap-oldkernel` | GET | Dynamic POSIX shell bootstrap script (legacy CentOS 6.x agent) |
| `/bundle.tar.gz` | GET | Complete deployment tarball |
| `/install.sh` | GET | Raw installer script |
| `/healthz` | GET | Health check JSON |
| `/oldkernel` | GET | Plaintext index of available CentOS 6.x / 2.6.32+ kit files |
| `/oldkernel/<file>` | GET | Old-kernel (CentOS 6.x) C++ and Python kit files (`nt-sniff-cpp.cpp`, `nt-ship-cpp.cpp`, `nt-sniff-cpp`, `nt-ship-cpp`, `install-oldkernel.sh`, `install-firstrun-el68.sh`, `nt-resource-guard.sh`, `nt-supervise.sh`, `nt-control.py`, etc.) |
