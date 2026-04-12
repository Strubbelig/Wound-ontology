from __future__ import annotations
from abc import ABC, abstractmethod
from pydantic import validate_call, ConfigDict
from wound_ontology.data_manager.data_manager import DataManager


class BaseConnector(ABC):
    """
    Abstract Base Class for all data and ontology sources.
    Enforces a consistent interface for the Orchestrator.
    """

    @validate_call(config=ConfigDict(extra='forbid', arbitrary_types_allowed=True))
    def __init__(self, source_name: str, data_manager: DataManager, file_name: str):
        self.source_name = source_name
        print(f"Initializing {self.source_name}...")
        self.dm = data_manager
        self.file_name = file_name

    @abstractmethod
    def connect(self):
        """Establish connection or load local resources."""
        pass

    @abstractmethod
    def get_data(self, query):
        """Main method to retrieve information."""
        pass

    @abstractmethod
    def save(self):
        pass
