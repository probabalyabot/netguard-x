"""NetGuard-X: pre-deployment network change impact verification."""
from .changes import ChangeError, apply_changes
from .gatekeeper import Decision, Gatekeeper
from .impact import AnalysisOptions, ChangeReport, analyze
from .incremental import IncrementalVerifier
from .models import Change, Network
from .risk import RiskWeights
from .verify import verify_network

__all__ = [
    "AnalysisOptions", "Change", "ChangeError", "ChangeReport", "Decision", "Gatekeeper", "IncrementalVerifier",
    "Network", "RiskWeights", "analyze", "apply_changes", "verify_network",
]
__version__ = "0.1.0"
