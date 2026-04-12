from __future__ import annotations
from abc import ABC, abstractmethod
from pydantic import validate_call, ConfigDict
from wound_ontology.data_manager.data_manager import DataManager


class BaseMapper(ABC):

    def __init__(self, mapper_name: str, data_manager: DataManager, file_name: str):
        self.name = mapper_name
        self.dm = data_manager
        self.file_name = file_name

        self._mapping = self.dm.load_latest_json(self.file_name) or {}

    @property
    def mapping(self) -> dict:
        """Access the underlying mapping dictionary."""
        return self._mapping

    @mapping.setter
    @validate_call(config=ConfigDict(extra='forbid', arbitrary_types_allowed=True))
    def mapping(self, new_data: dict):
        """Updates the mapping and automatically triggers a save."""
        self._mapping.update(new_data)
        self.save()

    def save(self):
        """Persists the mapping state via DataManager."""
        if self._mapping:
            print(f"[{self.name}] Saving updated mapping...")
            self.dm.save_as_json(self._mapping, self.file_name, )
