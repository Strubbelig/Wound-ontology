from __future__ import annotations
import asyncio
from concepts import Context
from wound_ontology.data_manager.data_manager import DataManager
from wound_ontology.fca.context_matrix import ContextMatrix
from wound_ontology.utils.string_utils import smart_title


class ConceptLattice:
    """
    Builds and names the formal concept lattice from an ContextMatrix.

    The FCA itself runs in build_lattice() via the `concepts` library:
      Context(objects, attributes, bool_tuples).lattice
    Everything else is naming (LLM) and persistence.
    """

    def __init__(self, data_manager, fca_matrix: ContextMatrix,
                 file_name: str = "concept_lattice"):
        self.dm = data_manager
        # One lattice instance per analysis (rule 6). A lattice built for the
        # Wound subtree must not share a file -- and so a reload -- with one built
        # for a different subtree, or the two analyses silently become one.
        self.file_name = file_name
        self.matrix = fca_matrix
        self._lattice = self.dm.load_latest_pickle(self.file_name)
        self._accepted: set[tuple[str, str]] | None = None
        # Populated by get_data_and_run_fca(). Intents (frozensets of attribute
        # names) that survive both readings of the undecided cells vs. those that
        # depend on reading an undecided cell as "true".
        self.certain_intents: set = set()
        self.candidate_intents: set = set()

    # ── The reviewed slice ────────────────────────────────────────────────────
    #
    # FCA output is a suggestion, so it is reviewed before it means anything. The
    # review is recorded here, as the subset of this lattice's edges a human
    # accepted, and that slice is what ClassHierarchy.get_data reads back as its
    # `fca` source. It is deliberately not written into the ConceptStore: the
    # store holds what documents asserted, and this is not that.

    def edges(self) -> list[tuple[str, str]]:
        """(child, parent) for each named concept and its named upper neighbours."""
        out: list[tuple[str, str]] = []
        for concept in self.lattice or ():
            child = getattr(concept, "name", None)
            if not isinstance(child, str) or not child:
                continue
            for upper in concept.upper_neighbors:
                parent = getattr(upper, "name", None)
                if isinstance(parent, str) and parent:
                    out.append((smart_title(child), smart_title(parent)))
        return out

    @property
    def accepted(self) -> set[tuple[str, str]]:
        """The reviewed slice: edges of this lattice a human accepted."""
        if self._accepted is None:
            raw = self.dm.load_latest_json(f"{self.file_name}_accepted") or []
            self._accepted = {(str(a), str(b)) for a, b in raw}
        return self._accepted

    def accept(self, pairs) -> int:
        """Record reviewed edges into this lattice's slice. Returns how many are new."""
        new = {(smart_title(str(a)), smart_title(str(b))) for a, b in pairs}
        before = len(self.accepted)
        self._accepted |= new
        self.dm.save_as_json([list(e) for e in sorted(self._accepted)],
                             f"{self.file_name}_accepted")
        added = len(self._accepted) - before
        print(f"[ConceptLattice] {added} edge(s) accepted into the slice of "
              f"'{self.file_name}' ({len(self._accepted)} total).")
        return added

    def withdraw(self, pairs) -> int:
        """Remove edges from this lattice's accepted slice. Returns how many went.

        The inverse of accept, and it has to exist: a review can be wrong, and the
        only alternative is deleting a cache file by hand — which is not an API,
        leaves no record, and gets the versioning wrong. Withdrawing writes a new
        version of the slice, so the previous one stays on disk like every other
        artifact.
        """
        gone = {(smart_title(str(a)), smart_title(str(b))) for a, b in pairs}
        present = self.accepted & gone
        missing = gone - present
        if missing:
            print(f"[ConceptLattice] {len(missing)} edge(s) were not in the slice of "
                  f"'{self.file_name}' and so could not be withdrawn: {sorted(missing)}")
        self._accepted -= present
        self.dm.save_as_json([list(e) for e in sorted(self._accepted)],
                             f"{self.file_name}_accepted")
        print(f"[ConceptLattice] {len(present)} edge(s) withdrawn from the slice of "
              f"'{self.file_name}' ({len(self._accepted)} remain).")
        return len(present)

    def slice(self) -> list[tuple[str, str]]:
        """The accepted sub-lattice, as edges. This is what feeds ClassHierarchy.

        Acceptance is a human decision and does not evaporate because a re-run
        produced a slightly different lattice, so edges no longer present in the
        current lattice are still returned -- and reported, since an accepted edge
        the analysis no longer supports is worth knowing about.
        """
        accepted = self.accepted
        if self._lattice is not None and accepted:
            stale = accepted - set(self.edges())
            if stale:
                print(f"[ConceptLattice] {len(stale)} accepted edge(s) are not in "
                      f"the current lattice of '{self.file_name}'; they are still "
                      f"applied. First: {sorted(stale)[:3]}")
        return sorted(accepted)

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

    # ── Category discipline for names ─────────────────────────────────────────
    #
    # A superclass is the same KIND of thing as its members, only more general.
    # Naming had no way to enforce that: it returned a free-text label, so a
    # concept whose extent was entirely material wounds could be named
    # "Traumatic Wound Healing Disorder" and every member proposed underneath it.
    # No later gate catches this — the label is newly minted, so it carries no
    # axioms for the reasoner to clash with. The extraction schema already types
    # every entity, and those types are in the context as `is_a: <Category>`
    # attributes, so the check costs nothing once the model returns a category.

    def extent_categories(self, concept) -> set[str]:
        """The BFO/MILD categories the context assigns to a concept's extent.

        Only genuine categories count: conceptual scaling also writes
        `is_a: <ancestor>` columns for hierarchy ancestors, which are ordinary
        classes and not types.
        """
        from wound_ontology.llm.extraction_models import CATEGORY_PARENT
        by_lower = {c.lower(): c for c in CATEGORY_PARENT}

        df = self.matrix.df
        cats: set[str] = set()
        for obj in concept.extent:
            if obj not in df.index:
                continue
            row = df.loc[obj]
            for col, value in row.items():
                if value != 1.0 or not str(col).startswith("is_a:"):
                    continue
                target = str(col).split(":", 1)[1].strip().lower()
                if target in by_lower:
                    cats.add(by_lower[target])
        return cats

    @staticmethod
    def _category_and_ancestors(category: str) -> list[str]:
        from wound_ontology.llm.extraction_models import CATEGORY_PARENT
        chain, cur = [category], CATEGORY_PARENT.get(category)
        while cur:
            chain.append(cur)
            cur = CATEGORY_PARENT.get(cur)
        return chain

    @staticmethod
    def name_is_a_grouping(name: str) -> tuple[bool, str]:
        """Refuse a name that is just the BFO category it was told to stay within.

        Handing the model the extent's category stopped it proposing a disorder
        over material wounds — and started it answering "Material entity", the
        category itself. That is not a biomedical grouping, it is the constraint
        read back, and as a superclass it says nothing.
        """
        import re

        from wound_ontology.llm.extraction_models import CATEGORY_PARENT

        # The categories are CamelCase ("MaterialEntity") and the model answers in
        # prose ("Material entity"), so compare with separators removed or the
        # check passes exactly the answers it exists to catch.
        def squash(x: str) -> str:
            return re.sub(r"[^a-z0-9]", "", x.lower())

        if squash(name) in {squash(c) for c in CATEGORY_PARENT}:
            return False, "names the BFO category rather than a biomedical grouping"
        return True, ""

    @staticmethod
    def category_of_known_class(name: str) -> str | None:
        """The ontology's category for this label, if MILD or WONT already has it.

        The model declares the category of the name it proposes, and a declared
        category is a claim. Where the ontologies already know the label, their
        answer is the one that counts — the same rule the extraction stage uses
        for grounding: a lookup, never a generation.
        """
        from wound_ontology.llm.extraction_models import GROUNDING
        target = name.strip().lower()
        for category, table in GROUNDING.items():
            for label in table:
                if label.strip().lower() == target:
                    return category
        return None

    @staticmethod
    def name_is_unused(name: str, taken) -> tuple[bool, str]:
        """Two formal concepts are two classes; they may not share a name.

        Nothing enforced this. The prompt was handed the names so far and asked
        to avoid duplicates, but every worker ran concurrently and read that list
        before any name existed, so it was always empty — and the answer was
        never checked. Four concepts came back called "Wound", smart_title folded
        them onto one node, and the lattice's order edges became a cycle.
        """
        if smart_title(name) in {smart_title(t) for t in taken}:
            return False, f"'{smart_title(name)}' already names another concept"
        return True, ""

    def name_is_licensed(self, name: str, extent_cats) -> tuple[bool, str]:
        """If the ontologies know this label, is it the right kind of thing?

        Only a *known* label can be judged. Its category comes from MILD and WONT
        — a lookup, never a claim — and must be the members' own category or an
        ancestor of it: a superclass is more general, never sideways. Naming a
        group of material wounds with a label the ontologies type as a process is
        refused here.

        A label the ontologies do not know cannot be judged this way at all, and
        is allowed through. Asking the model to declare a category for its own new
        label looked like a check and was not one: unverifiable by construction,
        and satisfied by answering "MaterialEntity" whatever the name meant. Over
        five live runs it refused no bad name and lost one good one. What keeps
        new names honest is naming top-down under an already-named parent, not a
        self-reported type.
        """
        known = self.category_of_known_class(name)
        if known is None:
            return True, "label is not in MILD or WONT, so its category is unknown"
        if not extent_cats:
            return True, "extent carries no category"
        wrong = [c for c in sorted(extent_cats)
                 if known not in self._category_and_ancestors(c)]
        if wrong:
            return False, (f"the ontologies type '{name}' as {known}, which is not "
                           f"{' or '.join(wrong)} nor an ancestor of "
                           f"{'it' if len(wrong) == 1 else 'them'}")
        return True, ""

    async def create_superclass_names(self, llm, min_objects=2, batch_size=10):
        """Name each lattice concept using the LLM (parallel waves).

        A name whose category is not a generalisation of its extent's categories
        is refused, and reported. FCA is a suggestion (see the provenance ranks);
        a suggestion that crosses a categorical boundary is not a weaker
        suggestion, it is a wrong one.
        """
        if not self.lattice:
            print("No lattice found. Run build_lattice() first.")
            return None

        concepts_to_name = [
            c for c in self.lattice
            if c.intent and len(c.extent) >= min_objects and self.is_certain(c)
        ]
        print(f"Found {len(concepts_to_name)} concepts requiring naming.")

        self.rejected_names: list[tuple[str, str]] = []

        # Top-down: general before specific, known before unknown. A concept named
        # in isolation is a guess about what a set of attributes means, and the
        # guesses do not cohere -- four different concepts came back called
        # "Wound", collapsed onto one node, and turned the lattice's own order
        # into a cycle. Named under an already-named parent it is a far smaller
        # question: what distinguishes THIS group from the more general one it
        # sits inside. That also makes "Wound is_a Skin Wound" unaskable, because
        # the parent is fixed before the child is named.
        #
        # This is sequential by necessity: each name is an input to the next.
        ordered = sorted(concepts_to_name, key=lambda c: (-len(c.extent),
                                                          sorted(c.intent)))
        taken: set[str] = set()
        named = 0
        for concept in ordered:
            try:
                cats = self.extent_categories(concept)
                parents = sorted({n for n in (getattr(u, "name", None)
                                              for u in concept.upper_neighbors)
                                  if isinstance(n, str) and n})
                parent_intent = set()
                for upper in concept.upper_neighbors:
                    if isinstance(getattr(upper, "name", None), str):
                        parent_intent |= set(upper.intent)
                differentia = sorted(set(concept.intent) - parent_intent)

                name = await llm.generate_semantic_name(
                    concept.intent, taken | set(self.semantic_superclass_names),
                    cats, parent_names=parents, differentia=differentia,
                    extent_sample=list(concept.extent)[:12],
                )

                ok, why = self.name_is_unused(name, taken)
                if ok:
                    ok, why = self.name_is_a_grouping(name)
                if ok:
                    ok, why = self.name_is_licensed(name, cats)
                if not ok:
                    self.rejected_names.append((name, why))
                    continue
                concept.name = name
                taken.add(smart_title(name))
                named += 1
            except Exception as e:
                print(f"Failed to name concept {list(concept.intent)[:2]}: {e}")

        print(f"Named {named} superclasses.")
        if self.rejected_names:
            print(f"{len(self.rejected_names)} name(s) refused as the wrong kind of "
                  f"thing for their members — the concept stays unnamed and "
                  f"proposes nothing:")
            for name, why in self.rejected_names:
                print(f"    '{name}': {why}")
        self.save()
        return self.lattice
