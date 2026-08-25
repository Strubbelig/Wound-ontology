from __future__ import annotations
import time, requests
from wound_ontology.connectors.base_connector import BaseConnector
from wound_ontology.data_manager.data_manager import DataManager


class UMLSConnector(BaseConnector):
    def __init__(self, data_manager,api_key):
        super().__init__("UMLS API", data_manager,"list_of_ulms_labels")
        self.api_key = api_key
        self.base_url = "https://uts-ws.nlm.nih.gov/rest"
        # NLM allows 20 requests/sec with an API key.
        # 0.06s sleep = ~16 requests/sec (Safe side).
        self.delay = 0.06
        self._list_of_labels=self.dm.load_latest_json("list_of_ulms_labels")

    def connect(self):
        """Verifies API key presence."""
        return self.api_key is not None

    @property
    def list_of_labels(self):
        """Getter: Returns the current list of unique labels."""
        return self._list_of_labels

    @list_of_labels.setter
    def list_of_labels(self, new_labels):
        """
        Setter: Adds new labels to the existing list,
        ensuring uniqueness and avoiding overwrites.
        """
        if not isinstance(new_labels, list):
            new_labels = [new_labels]

        # Combine existing and new, then cast to set for uniqueness, then back to list
        combined = set(self._list_of_labels) | set(new_labels)
        self._list_of_labels = list(set(combined))
        self.save()

    def lookup(self, term: str, max_results: int = 3) -> list[tuple[str, str]]:
        """
        Return up to max_results (CUI, preferred_name) pairs for a single term.
        Results are not cached — intended for targeted per-class UMLS lookups.
        """
        cuis = self._get_cui_paginated(term)[:max_results]
        results = []
        for cui in cuis:
            label = self._get_label_from_cui(cui)
            if label:
                results.append((cui, label))
            time.sleep(self.delay)
        return results

    def get_data(self, term):
        """
        Fetches new labels for a term and adds them to the existing collection
        without deleting previous data.
        """
        print(f"Searching UMLS for: {term}...")
        result_cuis = self._get_cui_paginated(term)

        new_found_labels = []
        total = len(result_cuis)

        for i, cui in enumerate(result_cuis):
            label = self._get_label_from_cui(cui)
            if label:
                new_found_labels.append(label)

            time.sleep(self.delay)

            if i % 50 == 0:
                print(f"  Processed {i}/{total} concepts...")

        # Use the setter to merge data
        self.list_of_labels = new_found_labels

        print(f"Update complete. Total unique labels now: {len(self.list_of_labels)}")
        return self.list_of_labels


    def save(self):
        self.dm.save_as_json(self.list_of_labels,self.file_name)

    def _get_cui_paginated(self, term):
        """Fetches ALL matching CUIs using 250-item pages."""
        all_cuis = []
        page_number = 1
        page_size = 250

        while page_number<6:
            endpoint = f"{self.base_url}/search/current"
            params = {
                "string": term,
                "apiKey": self.api_key,
                "returnIdType": "concept",
                "pageSize": page_size,
                "pageNumber": page_number
            }

            try:
                res = requests.get(endpoint, params=params)
                if res.status_code == 200:
                    data = res.json().get("result", {})
                    results = data.get("results", [])

                    if not results:
                        break

                    page_cuis = [item["ui"] for item in results if item["ui"] != "NONE"]
                    all_cuis.extend(page_cuis)

                    # If the page isn't full, there are no more pages
                    if len(results) < page_size:
                        break

                    page_number += 1
                    time.sleep(self.delay) # Respect rate limit during search too
                else:
                    print(f"Search Error {res.status_code} at page {page_number}")
                    break
            except Exception as e:
                print(f"Connection error: {e}")
                break

        return all_cuis

    def _get_label_from_cui(self, cui):
        """Fetches the official Preferred Name for a CUI."""
        endpoint = f"{self.base_url}/content/current/CUI/{cui}"
        params = {"apiKey": self.api_key}

        try:
            res = requests.get(endpoint, params=params, timeout=30)
        except requests.RequestException as exc:
            # A bare `except: return None` used to make a dead network, a bad API
            # key and "this CUI genuinely has no preferred name" indistinguishable
            # to the caller, so a whole failed enrichment run looked like a run
            # that simply found nothing.
            print(f"[UMLS] request failed for CUI {cui}: {exc}")
            return None
        if res.status_code == 401:
            raise PermissionError(
                f"[UMLS] rejected the API key (HTTP 401) while fetching CUI {cui}. "
                "Refusing to continue and silently return no labels for everything."
            )
        if res.status_code != 200:
            print(f"[UMLS] HTTP {res.status_code} for CUI {cui}; no label returned.")
            return None
        try:
            return res.json().get("result", {}).get("name")
        except ValueError as exc:
            print(f"[UMLS] unparseable JSON for CUI {cui}: {exc}")
            return None
