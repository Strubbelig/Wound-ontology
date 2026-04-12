from __future__ import annotations
from wound_ontology.connectors.onto_connector import OntoConnector
from wound_ontology.data_manager.data_manager import DataManager

RO_OWL_URL = "http://purl.obolibrary.org/obo/ro.owl"


class ROConnector(OntoConnector):
    def __init__(self, data_manager):
        super().__init__("Relations Ontology",
            data_manager,
            "ro_property_labels",
            RO_OWL_URL
        )

    def fetch_bfo_relations(self):
        """
        Fetches only foundational properties originally defined in BFO.
        These are the most robust predicates for Formal Concept Analysis.
        """
        if not self.onto:
            return []

        bfo_labels = []
        for prop in self.onto.object_properties():
            # Check if the IRI is a BFO identifier
            if "BFO_" in prop.iri:
                label = (prop.label[0].lower() if prop.label else prop.name).replace(" ", "_")

                # We still keep our label_to_iri mapping for the OWL Exporter
                self.label_to_iri[label] = prop.iri
                self.iri_to_label[prop.iri] = label

                bfo_labels.append(label)

        # BFO is small (usually < 40 relations), so no strict limit needed
        return sorted(list(set(bfo_labels)))

    def fetch_labels(self):
        if self.onto:
            labels = []
            # We look at object_properties() instead of classes()
            for prop in self.onto.object_properties():
                label = prop.label[0].lower() if prop.label else prop.name
                # Sanitize for LLM (e.g., "part of" -> "part_of")
                clean_label = label.replace(" ", "_")

                self.label_to_iri[clean_label] = prop.iri
                self.iri_to_label[prop.iri] = clean_label
                labels.append(clean_label)
            self.label_list = labels
