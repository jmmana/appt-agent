"""Re-export Intent from top-level models to avoid circular imports."""
from appt_agent.models import Intent

__all__ = ["Intent"]
