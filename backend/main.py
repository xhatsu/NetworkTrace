"""TraceScope monolith entrypoint (role ``all``).

This module is intentionally thin: the historical monolith application now
lives in :mod:`backend.app.application` as ``create_app("all")`` so that the
same code can also be started as isolated ingest-only or agent-stats-only
workloads (see ``backend/ingest_main.py`` and ``backend/agent_stats_main.py``).

``backend.main:app`` remains the documented and lifecycle-script entrypoint and
serves exactly the same routes as before this refactor.

Keeping this compatibility entrypoint means the stateless UI/read role can be
upgraded without requiring clients to learn the internal role split.
"""
from __future__ import annotations

from backend.app.application import ROLE_ALL, create_app

app = create_app(ROLE_ALL)
