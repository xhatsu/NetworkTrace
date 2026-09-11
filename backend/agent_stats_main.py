"""Agent lifecycle / health entrypoint (role ``agent-stats``).

Exposes only the Oldkernel Agent Statistics Protocol v1 surface:

  POST   /api/agent/stats
  GET    /api/agent/stats
  GET    /api/agent/stats/{node}
  GET    /api/agent/stats/{node}/history
  DELETE /api/agent/stats/{node}[/{instance_id}]
  GET    /api/v1/health

Run with::

    uvicorn backend.agent_stats_main:app --host 0.0.0.0 --port 30104

This process deliberately does not start the trace writer. In Kubernetes it
uses the authenticated storage-owner API for every agent table operation and
therefore mounts no database volume.
"""
from __future__ import annotations

from backend.app.application import ROLE_AGENT_STATS, create_app

app = create_app(ROLE_AGENT_STATS)
