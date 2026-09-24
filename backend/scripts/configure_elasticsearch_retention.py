#!/usr/bin/env python3
"""Configure Elasticsearch 7-day retention ILM policy, templates, and prune expired documents."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend.config import settings
from backend.elasticsearch import ElasticsearchReader


def main():
    days = settings.elasticsearch_retention_days
    print(f"Configuring Elasticsearch {days}-day retention policy on {settings.elasticsearch_url}...")
    reader = ElasticsearchReader()
    if not reader.url:
        print("Error: Elasticsearch URL is not configured.")
        sys.exit(1)

    res = reader.configure_retention(days)
    print("ILM Policy and Template configuration result:", json.dumps(res, indent=2))

    print(f"Triggering asynchronous pruning of documents older than {days} days...")
    prune_res = reader.prune_expired_documents(days)
    print("Pruning result:", json.dumps(prune_res, indent=2))
    print(f"Elasticsearch {days}-day retention enforcement completed successfully.")


if __name__ == "__main__":
    main()
