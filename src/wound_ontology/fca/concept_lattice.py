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
        # Populated by get_data_and_run_fca(). Intents (frozensets of attribute
        # names) that survive both readings of the undecided cells vs. those that
        # depend on reading an undecided cell as "true".
        self.certain_intents: set = set()
        self.candidate_intents: set = set()

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
        Runs FCA over the ContextMatrix, twice, and separates what is certain
        from what merely depends on an undecided cell.

        A NaN in the matrix means "not decided". Handing it to `concepts` would
        silently assert the attribute holds, because bool(float('nan')) is True.
        Instead the context is built under both readings:

          pessimistic  undecided -> attribute ABSENT
          optimistic   undecided -> attribute PRESENT

        A concept whose intent appears in BOTH lattices is certain: no undecided
        cell can change it. A concept that appears only in the optimistic lattice
        is a *candidate* — it exists only if some undecided cell happens to be
        true. Candidates are reported but must not be committed as superclasses.

        The returned (and persisted) lattice is the pessimistic one, so anything
        downstream reads only concepts that are actually supported by the data.
        """
        if not self.matrix.objects or not self.matrix.attributes:
            print("ContextMatrix is empty — skipping FCA.")
            return None

        objs, attrs = self.matrix.objects, self.matrix.attributes
        undecided = self.matrix.undecided_count

        print("Constructing concept lattice from FCA matrix...")
        pess = Context(objs, attrs, self.matrix.tuples(self.matrix.UNKNOWN_ABSENT)).lattice

        if not undecided:
            self.certain_intents = {frozenset(c.intent) for c in pess}
            self.candidate_intents = set()
            print(f"  no undecided cells — {len(pess)} concepts, all certain.")
            self.lattice = pess
            return self._lattice

        opti = Context(objs, attrs, self.matrix.tuples(self.matrix.UNKNOWN_PRESENT)).lattice

        pess_intents = {frozenset(c.intent) for c in pess}
        opti_intents = {frozenset(c.intent) for c in opti}
        self.certain_intents = pess_intents & opti_intents
        self.candidate_intents = opti_intents - pess_intents

        print(f"  undecided cells       : {undecided} "
              f"({self.matrix.undecided_density:.1%} of the matrix)")
        print(f"  concepts (pessimistic): {len(pess_intents)}")
        print(f"  concepts (optimistic) : {len(opti_intents)}")
        print(f"  certain (in both)     : {len(self.certain_intents)}")
        print(f"  candidates (optimistic only): {len(self.candidate_intents)} "
              f"— reported, NOT committed")

        self.lattice = pess
        return self._lattice

    def is_certain(self, concept) -> bool:
        """True if this concept survives both readings of the undecided cells."""
        if not self.certain_intents and not self.candidate_intents:
            return True          # no dual build was run; caller gets old behaviour
        return frozenset(concept.intent) in self.certain_intents

    def candidate_summary(self, max_display: int = 25) -> None:
        """Print the concepts that exist only if some undecided cell is true."""
        if not self.candidate_intents:
            print("No candidate-only concepts.")
            return
        print(f"{len(self.candidate_intents)} concepts depend on an undecided cell:")
        for i, intent in enumerate(sorted(self.candidate_intents, key=lambda x: (-len(x), sorted(x)))):
            if i >= max_display:
                print(f"  ... and {len(self.candidate_intents) - max_display} more.")
                break
            print("  {" + ", ".join(sorted(intent)) + "}")

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
            if c.intent and len(c.extent) >= min_objects and self.is_certain(c)
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
