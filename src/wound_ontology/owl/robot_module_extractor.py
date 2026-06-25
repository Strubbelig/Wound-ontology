"""SLME module extraction via ROBOT for wound-ontology seed terms."""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from rdflib import Graph, OWL, URIRef
from rdflib.namespace import RDFS


# Prefixes we skip because the source file is already tiny or unavailable
_SKIP_PREFIXES: frozenset[str] = frozenset({"BFO", "COB", "IAO", "NCBITaxon"})

# Mapping from prefix → filename inside onto_dir
_DEFAULT_ONTO_FILES: dict[str, str] = {
    "CHEBI":    "chebi.obo",
    "DOID":     "doid.owl",
    "HP":       "hp.obo",
    "GO":       "go.obo",
    "PATO":     "pato.owl",
    "OBI":      "OBI.rdf",
    "DRON":     "dron.owl",
    "OGMS":     "ogms.owl",
}

WOND_BASE = "http://purl.obolibrary.org/obo/WOND_"
OBO_BASE  = "http://purl.obolibrary.org/obo/"


class RobotModuleExtractor:
    """Extract SLME modules from OBO ontologies seeded by ground-truth IRIs.

    Reads all external (non-WOND) OBO class IRIs from a ground-truth OWL file,
    groups them by ontology prefix, and runs ``robot extract --method SLME``
    on each source ontology to produce a focused module.  The resulting modules
    are small enough to use as OAK annotator sources.

    Usage::

        extractor = RobotModuleExtractor(
            onto_dir="path/to/Import-Ontologien",
            modules_dir="output/owl/modules",
        )
        modules = extractor.run("output/owl/ground_truth_final.owl")
        # → {"CHEBI": Path("output/owl/modules/chebi_module.owl"), ...}
    """

    def __init__(
        self,
        onto_dir: str | Path,
        modules_dir: str | Path = "output/owl/modules",
        onto_files: dict[str, str] | None = None,
        slme_method: str = "BOT",
        robot_cmd: str = "robot",
    ) -> None:
        """
        Args:
            onto_dir:    Directory containing the source OWL/OBO files.
            modules_dir: Output directory for extracted modules.
            onto_files:  Override the default prefix→filename mapping.
            slme_method: ROBOT SLME variant: BOT (ancestors) | TOP (descendants) | STAR.
            robot_cmd:   Path to the ``robot`` executable.
        """
        self.onto_dir    = Path(onto_dir)
        self.modules_dir = Path(modules_dir)
        self.onto_files  = onto_files or _DEFAULT_ONTO_FILES
        self.slme_method = slme_method.lower()  # robot expects: bot | top | star
        self.robot_cmd   = robot_cmd

    # ── Public API ─────────────────────────────────────────────────────────────

    def seeds_from_owl(self, owl_path: str | Path) -> dict[str, list[str]]:
        """Return {prefix: [IRI, ...]} for all external OBO classes in owl_path."""
        g = Graph()
        path = Path(owl_path)
        fmt = "turtle" if path.read_text(errors="replace")[:300].strip().startswith("@") else "xml"
        g.parse(str(path), format=fmt)

        seeds: dict[str, list[str]] = {}
        seen: set[str] = set()

        for s in g.subjects(predicate=None, object=OWL.Class):
            iri = str(s)
            if not self._is_external(iri) or iri in seen:
                continue
            seen.add(iri)
            pfx = self._prefix(iri)
            seeds.setdefault(pfx, []).append(iri)

        # Also collect subClassOf targets (may not appear as owl:Class subjects)
        for _, _, o in g.triples((None, RDFS.subClassOf, None)):
            iri = str(o)
            if not self._is_external(iri) or iri in seen:
                continue
            seen.add(iri)
            pfx = self._prefix(iri)
            seeds.setdefault(pfx, []).append(iri)

        return seeds

    def extract_module(
        self,
        prefix: str,
        seed_iris: list[str],
        dry_run: bool = False,
    ) -> Path | None:
        """Extract an SLME module for one ontology prefix.

        Returns the output path, or None if the source file is not configured.
        """
        if prefix in _SKIP_PREFIXES:
            print(f"  [{prefix}] skipped (source is already small)")
            return None

        filename = self.onto_files.get(prefix)
        if not filename:
            print(f"  [{prefix}] no source file configured — skipping")
            return None

        source = self.onto_dir / filename
        if not source.exists():
            print(f"  [{prefix}] source not found: {source} — skipping")
            return None

        out_name = f"{prefix.lower()}_module.owl"
        out_path = self.modules_dir / out_name

        print(f"  [{prefix}] {len(seed_iris)} seeds → {out_name}", end="", flush=True)

        if dry_run:
            print("  [dry-run]")
            return out_path

        self.modules_dir.mkdir(parents=True, exist_ok=True)

        # Write seed IRIs to a temp file
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as tf:
            tf.write("\n".join(seed_iris))
            seed_file = tf.name

        try:
            cmd = [
                self.robot_cmd, "extract",
                "--method", self.slme_method,
                "--input",  str(source),
                "--term-file", seed_file,
                "--imports", "EXCLUDE",
                "--intermediates", "all",
                "--output", str(out_path),
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
            if result.returncode != 0:
                err = (result.stderr or result.stdout or "").strip()
                print(f"  ERROR: {err[-400:]}")
                return None
            size_kb = out_path.stat().st_size // 1024
            print(f"  ({size_kb} KB)")
            return out_path
        except subprocess.TimeoutExpired:
            print("  TIMEOUT")
            return None
        finally:
            Path(seed_file).unlink(missing_ok=True)

    def run(
        self,
        owl_path: str | Path,
        prefixes: list[str] | None = None,
        dry_run: bool = False,
    ) -> dict[str, Path]:
        """Extract SLME modules for all (or selected) prefixes in owl_path.

        Args:
            owl_path: Ground-truth OWL file to read seed IRIs from.
            prefixes: Restrict extraction to these prefixes (default: all).
            dry_run:  Report what would be done without running ROBOT.

        Returns:
            Mapping of prefix → module Path for successfully extracted modules.
        """
        print(f"[RobotModuleExtractor] reading seeds from {Path(owl_path).name}")
        seeds = self.seeds_from_owl(owl_path)

        target = set(prefixes) if prefixes else set(seeds)
        modules: dict[str, Path] = {}

        for pfx in sorted(target):
            iris = seeds.get(pfx, [])
            if not iris:
                print(f"  [{pfx}] no seeds found in source OWL — skipping")
                continue
            path = self.extract_module(pfx, iris, dry_run=dry_run)
            if path:
                modules[pfx] = path

        print(f"\nDone. {len(modules)} module(s) extracted → {self.modules_dir}")
        return modules

    # ── Helpers ────────────────────────────────────────────────────────────────

    @staticmethod
    def _is_external(iri: str) -> bool:
        return (
            iri.startswith(OBO_BASE)
            and not iri.startswith(WOND_BASE)
            and "_" in iri.split(OBO_BASE, 1)[1]
        )

    @staticmethod
    def _prefix(iri: str) -> str:
        local = iri.split("/obo/")[1]
        return local.split("_")[0]
