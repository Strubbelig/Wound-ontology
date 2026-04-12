from __future__ import annotations
from wound_ontology.connectors.base_connector import BaseConnector
from wound_ontology.data_manager.data_manager import DataManager


class OntoConnector(BaseConnector):
    def __init__(self, name, data_manager, filename, onto_url):
        super().__init__(name, data_manager, filename)
        self.onto_url = onto_url
        self.onto = None
        self.label_to_iri = {}
        self.iri_to_label = {}

        # Load existing labels
        loaded = self.dm.load_latest_json(self.file_name)
        self._label_list = loaded if isinstance(loaded, list) else []
        self.connect()

    @property
    def label_list(self):
        if not self._label_list:
            self.fetch_labels()
        return self._label_list

    @label_list.setter
    def label_list(self, new_labels):
        if not isinstance(new_labels, list):
            new_labels = [new_labels]
        combined = set(self._label_list) | set(new_labels)
        self._label_list = sorted(list(combined))

    def connect(self):
        try:
            from owlready2 import get_ontology
            print(f"Loading {self.source_name} from {self.onto_url}...")
            self.onto = get_ontology(self.onto_url).load()
        except Exception as e:
            print(f"Failed to load ontology: {e}")

    def get_data(self, query=None):
        """Implementation of ABC: Returns the full label list."""
        return self.label_list

    def fetch_labels(self):
        """To be implemented by BFO or RO subclasses."""
        pass

    def save(self):
        self.dm.save_as_json(self.label_list, self.file_name)
