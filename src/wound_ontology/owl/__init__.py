from .model import OWLOntology
from .curator import OntologyCurator

__all__ = ["OWLOntology", "OntologyCurator"]

from .extend import extend_ground_truth, ExtendReport  # noqa: E402,F401
