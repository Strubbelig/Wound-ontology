from __future__ import annotations
from wound_ontology.connectors.onto_connector import OntoConnector

try:
    from config.settings import OBI_OWL_URL
except ImportError:
    OBI_OWL_URL = "http://purl.obolibrary.org/obo/obi.owl"


class OBIConnector(OntoConnector):
    def __init__(self, data_manager):
        super().__init__(
            "OBI Ontology",
            data_manager,
            "obi_class_labels",
            OBI_OWL_URL,
        )

    def fetch_labels(self):
        if self.onto:
            labels = []
            for cls in self.onto.classes():
                label = cls.label[0].lower() if cls.label else cls.name
                self.label_to_iri[label] = cls.iri
                self.iri_to_label[cls.iri] = label
                labels.append(label)
            self.label_list = labels
