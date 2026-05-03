from __future__ import annotations
import pandas as pd
from Bio import Entrez, Medline
from wound_ontology.connectors.base_connector import BaseConnector
from wound_ontology.data_manager.data_manager import DataManager


class PubmedConnector(BaseConnector):
    """
    Connector for PubMed (NCBI Entrez) to fetch medical abstracts.
    Maintains a local CSV database to avoid redundant API calls.
    """
    def __init__(self, data_manager, email):
        super().__init__("PubMed API", data_manager,"pubmed_abstracts")
        self.email = email
        self._database = self.dm.load_latest_csv(self.file_name)
        self.connect()

    def connect(self):
        """Implementation of ABC: Configures Entrez credentials."""
        if not self.email:
            raise ValueError("PubMed Connector requires a valid email for Entrez.")
        Entrez.email = self.email
        print(f"Connected to PubMed via {self.email}")
    def get_data(self, queries: str | list[str], max_abstracts_per_query: int = 1000):
        """
        Fetch abstracts for one or more PubMed queries, merging all results
        into the local database. Duplicate PMIDs are dropped automatically.

        queries                 – a single query string or a list of query strings
        max_abstracts_per_query – retmax applied to each individual query
        """
        if isinstance(queries, str):
            queries = [queries]
        for i, query in enumerate(queries, 1):
            print(f"[{i}/{len(queries)}] Querying: {query!r}")
            self._fetch_abstracts(query, max_abstracts_per_query)
        print(f"Done. Total unique abstracts in database: {len(self.database)}")
        return self.database


    def save(self):
        self.dm.save_as_csv(self.database,self.file_name)


    @property
    def database(self):
        """Truly lazy loader: No predefined columns."""
        if self._database is None:
            # If load fails or file is missing, return a blank slate
            self._database = pd.DataFrame()
        return self._database


    @database.setter
    def database(self, new_data: pd.DataFrame):
        """
        Updates the existing database with new_data instead of overwriting it.
        """
        # 1. Initialize the current database if it's still None
        current_df = self.database

        if not isinstance(new_data, pd.DataFrame):
            raise TypeError("New data must be a Pandas DataFrame.")

        # 2. Combine the old and new
        # ignore_index=True prevents duplicate index numbers (0, 1, 0, 1...)
        updated_df = pd.concat([current_df, new_data], ignore_index=True)

        # 3. Optional: Remove exact duplicates if necessary
        self._database = updated_df.drop_duplicates().reset_index(drop=True)
        self.save()
        print(f"Database updated. New total rows: {len(self._database)}")



    def _fetch_abstracts(self, query, max_abstracts):
        """Search and retrieve Medline records, then sync with local storage."""
        try:
            # 1. Search for pmids
            with Entrez.esearch(db="pubmed", term=query, retmax=max_abstracts) as handle:
                id_list = Entrez.read(handle)["IdList"]

            if not id_list:
                print("No abstracts found for the given query.")
                return self.database # Return existing DB if nothing new found

            # 2. Fetch and Parse Medline details
            with Entrez.efetch(db="pubmed", id=id_list, rettype="medline", retmode="text") as handle:
                  records = list(Medline.parse(handle))

            # 3. Transform to DataFrame
            # pmid as a string!!

            meta_col_name, meta_id = self.dm.get_meta_stamp("abstract_query")

            new_data = [{
            "pmid": str(r.get("PMID")),
            meta_col_name: meta_id,  # <--- Tracking tag
            "query": query,      # <--- Keep track of which search found this
            "title": r.get("TI"),
            "abstract": r.get("AB")
    }
    for r in records if "AB" in r
]
            df_new = pd.DataFrame(new_data)

            self.database = df_new

            return self.database

        except Exception as e:
             print(f"Error during fetch: {e}")
             return self.database
