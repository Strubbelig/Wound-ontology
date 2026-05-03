from __future__ import annotations
"""Base connector abstractions for the wound ontology pipeline."""
from abc import ABC, abstractmethod
from wound_ontology.data_manager.data_manager import DataManager


class BaseConnector(ABC):
    """
    Abstract Base Class for all data and ontology sources.
    Enforces a consistent interface for the Orchestrator.

    Subclasses must implement connect(), get_data(), and save().
    """
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
        """Persist connector data to disk."""
        pass
