from __future__ import annotations
import pandas as pd
from wound_ontology.connectors.onto_connector import OntoConnector
from wound_ontology.data_manager.data_manager import DataManager

BFO_OWL_URL = "http://purl.obolibrary.org/obo/bfo.owl"


class BFOConnector(OntoConnector):
    def __init__(self, data_manager):
        super().__init__("BFO Ontology",
            data_manager,
            "bfo_class_labels",
            BFO_OWL_URL
        )

    def fetch_labels(self):
        if self.onto:
            labels = []
            for cls in self.onto.classes():
                # Prefer label, fallback to name
                label = cls.label[0].lower() if cls.label else cls.name
                self.label_to_iri[label] = cls.iri
                self.iri_to_label[cls.iri] = label
                labels.append(label)
            self.label_list = labels

    # BFO anchor classes offered to the LLM as is_a target candidates.
    # Using mid-level categories rather than leaves keeps classification
    # meaningful without over-specifying the upper ontology.
    BFO_ANCHOR_CLASSES = [
        "material entity", "immaterial continuant",
        "quality", "disposition", "role", "process",
    ]

    def get_anchor_names(self) -> list[str]:
        """
        Returns the BFO anchor class names used as is_a target candidates
        during LLM extraction (e.g. ['material entity', 'immaterial entity']).
        """
        return self.BFO_ANCHOR_CLASSES

    def get_hierarchy_df(self) -> pd.DataFrame:
        """
        Build a Class / Parent class DataFrame from the BFO class hierarchy
        and save it to data/reference/bfo_hierarchy.csv.

        Rows where a class has no parent (top-level) are excluded.
        Returns the DataFrame.
        """
        if not self.onto:
            print("BFO ontology not loaded.")
            return pd.DataFrame(columns=["Class", "Parent class"])

        rows = []
        for cls in self.onto.classes():
            label = cls.label[0].lower() if cls.label else cls.name
            for parent in cls.is_a:
                # is_a entries can be restrictions or plain classes
                if hasattr(parent, "name"):
                    parent_label = (
                        parent.label[0].lower() if parent.label else parent.name
                    )
                    rows.append({"Class": label, "Parent class": parent_label})

        df = pd.DataFrame(rows).drop_duplicates()
        self.dm.save_reference_csv(df, "bfo_hierarchy")
        print(f"BFO hierarchy: {len(df)} edges saved to data/reference/bfo_hierarchy.csv")
        return df
