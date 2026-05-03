from __future__ import annotations
import os, glob, json, pickle
from pathlib import Path
from datetime import datetime
import pandas as pd

_DEFAULT_BASE_PATH = Path(__file__).resolve().parents[3] / "data" / "cache"

class DataManager:
    """
    Handles saving and versioning of wound ontology data to storage.
    """
    def __init__(self, base_path=_DEFAULT_BASE_PATH):
        self.base_path = Path(base_path)
        # Automatically create the folder if it doesn't exist
        self._ensure_directory()
        self.file_name = "meta_ids"
        self.meta_id_dict = self.load_latest_json(self.file_name) or {}

    def _ensure_directory(self):
        """Creates the storage directory if it's missing."""
        try:
            self.base_path.mkdir(parents=True, exist_ok=True)
            print(f"Directory ready: {self.base_path}")
        except Exception as e:
            print(f"Note: Could not create directory (Local mode?): {e}")

    def _get_timestamped_name(self, prefix, extension):
        """Generates a filename like: wound_data_2026-03-05_21-30.json"""
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M")
        return f"{prefix}_{timestamp}.{extension}"

    def _cleanup_old_files(self, prefix, limit=10):
        """
        Removes oldest files matching the prefix, regardless of extension.
        Assumes prefix is unique to file type.

        This keeps only the most recent `limit` files and prevents the cache
        directory from growing without bound.
        """
        # search for any file starting with prefix_
        search_pattern = str(self.base_path / f"{prefix}_*")
        files = sorted(glob.glob(search_pattern))

        if len(files) > limit:
            # The file names are timestamped in a sortable format, so the
            # oldest files naturally appear first after sorting.
            files_to_delete = files[:-limit]
            for file_path in files_to_delete:
                try:
                    os.remove(file_path)
                    print(f"Cleanup: Pruned old version {os.path.basename(file_path)}")
                except Exception as e:
                    print(f"Cleanup Warning: Could not delete {file_path}: {e}")


    def save_as_json(self, data_list, filename_prefix):
        """Saves JSON and prunes by prefix."""
        filename = self._get_timestamped_name(filename_prefix, "json")
        full_path = self.base_path / filename

        with open(full_path, 'w', encoding='utf-8') as f:
            json.dump(data_list, f, indent=4)

        self._cleanup_old_files(filename_prefix) # Extension-agnostic
        return str(full_path)

    def save_as_csv(self, df, filename_prefix):
        """Saves CSV and prunes by prefix."""
        filename = self._get_timestamped_name(filename_prefix, "csv")
        full_path = self.base_path / filename

        df.to_csv(full_path, index=True)

        self._cleanup_old_files(filename_prefix) # Extension-agnostic
        return str(full_path)


    def save_owl(self, graph, filename_prefix: str) -> str:
        """Saves an rdflib.Graph as a timestamped OWL/RDF-XML file."""
        filename = self._get_timestamped_name(filename_prefix, "owl")
        full_path = self.base_path / filename
        graph.serialize(destination=str(full_path), format="xml")
        self._cleanup_old_files(filename_prefix)
        print(f"[DataManager] Saved OWL → {full_path.name}  ({full_path.stat().st_size:,} bytes)")
        return str(full_path)

    def save_as_pickle(self, obj, filename_prefix):
        filename = self._get_timestamped_name(filename_prefix, "pkl")
        full_path = self.base_path / filename
        with open(full_path, 'wb') as f:
            pickle.dump(obj, f)
        return str(full_path)


    def _find_latest_path(self, prefix: str, extension: str):
        """
        Helper: Searches the directory for the most recent file
        matching the prefix and extension.

        Uses the timestamped filename format to find the newest version.
        """
        search_pattern = str(self.base_path / f"{prefix}_*.{extension}")
        files = glob.glob(search_pattern)

        if not files:
            return None

        # Standard sort puts the latest YYYY-MM-DD_HH-MM at the end [-1]
        return sorted(files)[-1]
    def load_latest_owl(self, prefix: str) -> str | None:
        """Returns the path to the most recent OWL file matching prefix (does not parse)."""
        path = self._find_latest_path(prefix, "owl")
        if path:
            print(f"[DataManager] Latest OWL: {os.path.basename(path)}")
            return path
        print(f"[DataManager] No OWL found for prefix: {prefix}")
        return None
    def load_latest_csv(self, prefix: str):
        """Loads the most recent CSV matching the prefix into a DataFrame."""
        path = self._find_latest_path(prefix, "csv")

        if path:
            print(f"Loading latest CSV: {os.path.basename(path)}")
            return pd.read_csv(path, encoding='utf-8')

        print(f"No CSV found for prefix: {prefix}")
        return None
    def load_latest_json(self, prefix: str):
        """Loads the most recent JSON matching the prefix into a Dictionary."""
        path = self._find_latest_path(prefix, "json")

        if path:
            print(f"Loading latest JSON: {os.path.basename(path)}")
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)

        print(f"No JSON found for prefix: {prefix}")
        return None
    def load_latest_pickle(self, prefix: str):
        """Loads the most recent Pickle matching the prefix into an Object."""
        path = self._find_latest_path(prefix, "pkl")

        if path:
            print(f"Loading latest Pickle: {os.path.basename(path)}")
            try:
                with open(path, 'rb') as f:
                    return pickle.load(f)
            except Exception as e:
                print(f"Error loading pickle: {e}")
                return None

        print(f"No Pickle found for prefix: {prefix}")
        return None


    def get_meta_stamp(self, workflow_prefix: str):
        """
        Returns ONLY the metadata fields for a specific workflow.
        Returns: tuple(meta_column_name, meta_id_string)

        This method keeps a simple persistent counter in `meta_ids.json` so that
        every execution of a workflow can be traced with a stable stamp.
        """
        # 1. Increment the persistent state
        self.meta_id_dict[workflow_prefix] = self.meta_id_dict.get(workflow_prefix, 0) + 1

        # 2. Persist the state immediately so future calls do not reuse the same counter.
        self.save_as_json(self.meta_id_dict, self.file_name)

        # 3. Format the unique ID
        count = self.meta_id_dict[workflow_prefix]
        timestamp = datetime.now().strftime("%Y%m%d_%H%M")
        meta_id=f"{workflow_prefix}_{count}_{timestamp}"
        meta_col_name = f"meta_{workflow_prefix}_id"

        return meta_col_name, meta_id

    def purge_by_prefix(self, prefix: str, confirm: bool = False):
        """
        Deletes ALL files matching the prefix (json, csv, pkl).
        Safety: Requires confirm=True to actually execute deletion.

        This is a destructive operation; the user must explicitly opt in.
        """
        if not prefix or len(prefix) < 5:
            print(f"Purge aborted: Prefix '{prefix}' is too short/dangerous.")
            return

        # Find all files starting with prefix_
        search_pattern = str(self.base_path / f"{prefix}_*")
        files_to_purge = glob.glob(search_pattern)

        if not files_to_purge:
            print(f"Purge: No files found matching prefix '{prefix}'.")
            return

        print(f"--- PURGE WARNING: Found {len(files_to_purge)} files for '{prefix}' ---")
        for f in files_to_purge:
            print(f"Target: {os.path.basename(f)}")

        if not confirm:
            print("Purge: Action cancelled. Set confirm=True to delete.")
            return

        # Execution
        count = 0
        for file_path in files_to_purge:
            try:
                os.remove(file_path)
                count += 1
            except Exception as e:
                print(f"Purge Error: Could not delete {file_path}: {e}")

        print(f"Purge Complete: Deleted {count} files matching '{prefix}'.")

    # ── Reference files (stable, unversioned) ─────────────────────────────────

    @property
    def reference_path(self) -> Path:
        """Stable reference data — no versioning, not purged."""
        ref = self.base_path.parent / "reference"
        ref.mkdir(parents=True, exist_ok=True)
        return ref

    def save_reference_csv(self, df: pd.DataFrame, filename: str) -> str:
        """Save a stable reference CSV (overwrites, no timestamp)."""
        path = self.reference_path / f"{filename}.csv"
        df.to_csv(path, index=False)
        print(f"Reference saved: {path.name}")
        return str(path)

    def load_reference_csv(self, filename: str) -> pd.DataFrame | None:
        """Load a reference CSV by exact filename (no prefix search)."""
        path = self.reference_path / f"{filename}.csv"
        if path.exists():
            print(f"Loading reference: {path.name}")
            return pd.read_csv(path)
        print(f"No reference found: {filename}.csv")
        return None

        print(f"Purge Complete: Deleted {count} files matching '{prefix}'.")
