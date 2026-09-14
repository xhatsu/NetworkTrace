"""Keep the legacy principal-baseline import stable during behavioral-engine consolidation."""

from backend.app.services.principal_relationships import process_principal_intelligence

__all__ = ["process_principal_intelligence"]
