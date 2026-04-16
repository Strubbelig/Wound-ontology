from __future__ import annotations
import asyncio
from concepts import Context
from wound_ontology.data_manager.data_manager import DataManager
from wound_ontology.fca.context_matrix import ContextMatrix


class ConceptLattice:
    """
    Builds and names the formal concept lattice from an ContextMatrix.

    The FCA itself runs in build_lattice() via the `concepts` library:
      Context(objects, attributes, bool_tuples).lattice
    Everything else is naming (LLM) and persistence.
    """

    def __init__(self, data_manager, fca_matrix: ContextMatrix):
        self.dm = data_manager
        self.file_name = "concept_lattice"
        self.matrix = fca_matrix
        self._lattice = self.dm.load_latest_pickle(self.file_name)

    @property
    def semantic_superclass_names(self):
        """Named lattice concepts, excluding composite-attribute or raw-tuple names."""
        semantic_names = []
        for concept in self.lattice:
            name = getattr(concept, 'name', None)
            if isinstance(name, str):
                is_composite = ":" in name or name.startswith("(")
                if not is_composite:
                    semantic_names.append(name)
        return list(semantic_names)

    @property
    def lattice(self):
        if self._lattice is None:
            print("Building lattice...")
            self._lattice = self.get_data_and_run_fca()
        return self._lattice

    @lattice.setter
    def lattice(self, new_lattice):
        self._lattice = new_lattice
        self.save()

    def save(self):
        """Persist the current lattice. Uses _lattice directly to avoid triggering the property."""
        if self._lattice is not None:
            self.dm.save_as_pickle(self._lattice, self.file_name)

    def get_data_and_run_fca(self):
        """
        Runs FCA: constructs a formal Context from the ContextMatrix and
        computes the concept lattice via the `concepts` library.
        """
        if not self.matrix.objects or not self.matrix.attributes:
            print("ContextMatrix is empty — skipping FCA.")
            return None
        print("Constructing concept lattice from FCA matrix...")
        ctx = Context(self.matrix.objects, self.matrix.attributes, self.matrix.bool_tuples)
        self.lattice = ctx.lattice
        return self._lattice

    def summary(self, max_display: int = 50) -> None:
        """Print named lattice concepts with extent size and intent preview."""
        if not self.lattice:
            print("No lattice available.")
            return
        named_count = 0
        for i, concept in enumerate(self.lattice):
            name = getattr(concept, 'name', None)
            if not name:
                continue
            intent_preview = ", ".join(list(concept.intent)[:3])
            print(f"[{i}] {name}")
            print(f"    └─ {len(concept.extent)} objects | {intent_preview}...")
            named_count += 1
            if named_count >= max_display:
                remaining = sum(1 for c in self.lattice if getattr(c, 'name', None)) - named_count
                if remaining:
                    print(f"\n... and {remaining} more.")
                break
        print(f"\n{named_count} named superclasses displayed.")

    async def create_superclass_names(self, llm, min_objects=2, batch_size=10):
        """Name each lattice concept using the LLM (parallel waves)."""
        if not self.lattice:
            print("No lattice found. Run build_lattice() first.")
            return None

        concepts_to_name = [
            c for c in self.lattice
            if c.intent and len(c.extent) >= min_objects
        ]
        print(f"Found {len(concepts_to_name)} concepts requiring naming.")

        sem = asyncio.Semaphore(batch_size)

        async def name_worker(concept):
            async with sem:
                try:
                    name = await llm.generate_semantic_name(
                        concept.intent, self.semantic_superclass_names
                    )
                    concept.name = name
                    return True
                except Exception as e:
                    print(f"Failed to name concept {concept.intent[:2]}: {e}")
                    return False

        results = await asyncio.gather(*[name_worker(c) for c in concepts_to_name])
        print(f"Named {sum(results)} superclasses.")
        self.save()
        return self.lattice
