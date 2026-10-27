"""Code that existed only for the mereological hierarchy, removed 2026-10-27.

The curator asked whether the part_of hierarchy was used for anything. It was not:
since 2026-10-21 it was no pipeline stage, and its text part_of edges were never
exported (rule 66). part_of reaches the FCA as an attribute read from the cleaned
store, and WONT only as one of the relations read as true of every instance
(15 of 266 part_of statements read). "verschieb erstmal den ganzen alten code
dorthin, wo der rest schon ist." The class itself is
mereological_hierarchy_removed_2026-10-27.py, its tests
test_mereological_hierarchy_removed_2026-10-27.py. Below, the pieces cut out of
files that stay, verbatim, each under the file and place it came from, commented
out because methods keep their class indentation.
"""

# ============================================================================
# src/wound_ontology/orchestrator.py -- module imports
# ============================================================================
# from wound_ontology.hierarchies.mereological_hierarchy import MereologicalHierarchy

# ============================================================================
# src/wound_ontology/orchestrator.py -- Orchestrator.__init__
# ============================================================================
#         # The mereological hierarchy left the pipeline the same day: its text
#         # part_of edges were never exported (rule 66). Built on demand only.
#         self._mere_hier: MereologicalHierarchy | None = None

# ============================================================================
# src/wound_ontology/orchestrator.py -- class Orchestrator
# ============================================================================
#     @property
#     def mere_hier(self) -> MereologicalHierarchy:
#         """The mereological hierarchy, built in memory on demand.
#
#         Not a pipeline stage any more (2026-10-21): its text part_of edges were
#         never exported (rule 66), and the FCA reads part_of from the store. Kept
#         for review_mere_relations and the inspection scripts.
#         """
#         if self._mere_hier is None:
#             self._mere_hier = MereologicalHierarchy(self.dm)
#             self._mere_hier.get_data(self.store)
#         return self._mere_hier
#
#     @mere_hier.setter
#     def mere_hier(self, value) -> None:
#         self._mere_hier = value

# ============================================================================
# src/wound_ontology/orchestrator.py -- class Orchestrator
# ============================================================================
#     def review_mere_relations(self, batch_size: int = 50) -> None:
#         """
#         LLM-validate every part_of edge in the mereological hierarchy.
#
#         Each (child, part_of, parent) triple is classified as:
#           keep  – valid anatomical/physical part_of → left unchanged
#           is_a  – subtype relation mislabelled as part_of →
#                   removed from mere_hier, added to class_hier
#           drop  – wrong in both directions → removed from mere_hier
#
#         Both hierarchies are saved after correction.
#         Re-run after run_build_hierarchies() to keep corrections current.
#         """
#         df = self.mere_hier.df
#         if df.empty:
#             print("Mereological hierarchy is empty.")
#             return
#
#         # Collect all edges as (child, parent)
#         triples: list[tuple[str, str]] = []
#         for child in df.index:
#             for parent in df.columns[df.loc[child] == 1.0]:
#                 triples.append((child, parent))
#
#         if not triples:
#             print("No part_of edges found.")
#             return
#
#         print(f"[review_mere_relations] Validating {len(triples)} part_of edges "
#               f"in batches of {batch_size}...")
#
#         async def _run():
#             results = []
#             total = (len(triples) + batch_size - 1) // batch_size
#             for i in range(0, len(triples), batch_size):
#                 batch = triples[i:i + batch_size]
#                 bn = i // batch_size + 1
#                 print(f"  batch {bn}/{total} ({len(batch)} triples)...", flush=True)
#                 results.extend(await self.llm.validate_mere_batch(batch))
#             return results
#
#         results = self._run_sync(_run())
#
#         kept = dropped = reclassified = 0
#         for r in results:
#             child, parent, verdict = r.child, r.parent, r.verdict.strip().lower()
#             if verdict == "keep":
#                 kept += 1
#                 continue
#             # Remove from mere_hier
#             if child in self.mere_hier._df.index and parent in self.mere_hier._df.columns:
#                 self.mere_hier._df.at[child, parent] = 0.0
#             if verdict == "is_a":
#                 self.class_hier._set_edge(child, parent)
#                 reclassified += 1
#             else:
#                 dropped += 1
#
#         self.mere_hier.save()
#         self.class_hier.save()
#         print(f"\n[review_mere_relations] done — "
#               f"kept={kept}, reclassified as is_a={reclassified}, dropped={dropped}. "
#               f"Both hierarchies saved.")

# ============================================================================
# src/wound_ontology/llm/llm_client.py -- module imports
# ============================================================================
#     MereRelationResult, MereRelationBatchResponse,

# ============================================================================
# src/wound_ontology/llm/llm_client.py -- class LLMClient
# ============================================================================
#     async def validate_mere_batch(
#         self, triples: list[tuple[str, str]]
#     ) -> list[MereRelationResult]:
#         """
#         Classify (child, part_of, parent) triples for a wound ontology.
#
#         Returns list of MereRelationResult with verdict:
#           keep  – valid anatomical/physical part_of
#           is_a  – child is a subtype of parent, not a part
#           drop  – relation is wrong in both directions
#         """
#         lines = [f'- ("{c}", part_of, "{p}")' for c, p in triples]
#         prompt = f"""
#         You are a biomedical ontologist curating a wound care ontology (BFO/RO).
#
#         BFO rule: part_of connects CONTINUANTS (material entities, anatomical structures).
#         A PROCESS or PROCEDURE cannot be part_of a material entity.
#
#         Classify each triple with one of three verdicts:
#           keep  – the child is physically/anatomically a PART of the parent
#                   (e.g. "Wound Bed part_of Wound", "Dermis part_of Skin")
#           is_a  – the child is a SUBTYPE/KIND of the parent, not a part
#                   (e.g. "Pressure Injury is_a Wound", "Alveolar Bone Plate Avulsion is_a Alveolar Bone Injury")
#           drop  – the relation is wrong in both directions; remove it
#                   (e.g. "Alginate Hydrogel part_of Wound Management" — a dressing is not a part of a management concept)
#
#         TRIPLES:
#         {chr(10).join(lines)}
#
#         Return JSON with "results": list of {{child, parent, verdict}}.
#         Use the EXACT child and parent strings from the input — do not paraphrase.
#         """
#         result = await self._execute_with_retry(
#             self._call_json, prompt, MereRelationBatchResponse,
#             temperature=0.0, timeout=360,
#         )
#         return result.results

# ============================================================================
# src/wound_ontology/llm/schemas.py -- module level
# ============================================================================
# class MereRelationResult(BaseModel):
#     child: str
#     parent: str
#     verdict: str  # "keep" | "is_a" | "drop"
#
# class MereRelationBatchResponse(BaseModel):
#     results: list[MereRelationResult]

# ============================================================================
# src/wound_ontology/owl/curator.py -- OntologyCurator.from_hierarchies, signature
# ============================================================================
#         mereological_hierarchy=None,

# ============================================================================
# src/wound_ontology/owl/curator.py -- OntologyCurator.from_hierarchies, body
# ============================================================================
#         if mereological_hierarchy is not None and not mereological_hierarchy.df.empty:
#             self._export_mereological(cls_reg, mereological_hierarchy)

# ============================================================================
# src/wound_ontology/owl/curator.py -- class OntologyCurator
# ============================================================================
#     def _export_mereological(self, cls_reg: dict, mere_hier) -> None:
#         onto = self.ontology.onto
#         with onto:
#             iri, label, transitive = self.RELATION_IRIS["part_of"]
#             part_of = self._get_or_create_prop(iri, label, transitive)
#             for branch in mere_hier.df.index:
#                 for root in mere_hier.df.columns:
#                     if mere_hier.df.at[branch, root] != 1.0:
#                         continue
#                     branch_cls  = self._get_or_create_cls(cls_reg, branch)
#                     root_cls    = self._get_or_create_cls(cls_reg, root)
#                     restriction = part_of.some(root_cls)
#                     if restriction not in branch_cls.is_a:
#                         branch_cls.is_a.append(restriction)
#         print(f"[OntologyCurator] MereologicalHierarchy: {len(mere_hier.df.index)} concepts exported.")

# ============================================================================
# src/wound_ontology/owl/extend.py -- extend_ground_truth, signature
# ============================================================================
#     mere_hier=None,

# ============================================================================
# src/wound_ontology/owl/extend.py -- extend_ground_truth, body
# ============================================================================
#     for branch, root in _hierarchy_edges(mere_hier):
#         add_restriction(branch, "part_of", root)

# ============================================================================
# src/wound_ontology/hierarchies/__init__.py -- package imports
# ============================================================================
# from wound_ontology.hierarchies.mereological_hierarchy import MereologicalHierarchy

# ============================================================================
# tests/test_owl_ontology.py -- module imports
# ============================================================================
# from wound_ontology.hierarchies.mereological_hierarchy import MereologicalHierarchy

# ============================================================================
# tests/test_owl_ontology.py -- fixtures
# ============================================================================
# @pytest.fixture
# def mere_hier():
#     h = MereologicalHierarchy(MockDM())
#     h._set_edge("Wound Bed",   "Wound")
#     h._set_edge("Wound Fluid", "Wound")
#     return h

# ============================================================================
# tests/test_owl_ontology.py -- tests
# ============================================================================
# # ── from_hierarchies: mereological hierarchy ──────────────────────────────────
#
# def test_mere_concepts_appear_in_owl(mere_hier, dm, tmp_path):
#     onto = _onto("mere_concepts")
#     OntologyCurator(onto).from_hierarchies(mereological_hierarchy=mere_hier)
#     out = tmp_path / "test.owl"
#     onto.save(dm, str(out))
#     content = _owl_text(out)
#     assert "Wound_Bed"   in content
#     assert "Wound_Fluid" in content
#
#
# def test_part_of_property_declared(mere_hier, dm, tmp_path):
#     onto = _onto("part_of_decl")
#     OntologyCurator(onto).from_hierarchies(mereological_hierarchy=mere_hier)
#     out = tmp_path / "test.owl"
#     onto.save(dm, str(out))
#     assert "part_of" in _owl_text(out)
#
#
# def test_part_of_restriction_on_branch(mere_hier, dm, tmp_path):
#     onto = _onto("part_of_restr")
#     OntologyCurator(onto).from_hierarchies(mereological_hierarchy=mere_hier)
#     out = tmp_path / "test.owl"
#     onto.save(dm, str(out))
#     content = _owl_text(out)
#     assert "someValuesFrom" in content or "subClassOf" in content
#
#
# # ── from_hierarchies: combined ─────────────────────────────────────────────────
#
# def test_combined_export(class_hier, mere_hier, dm, tmp_path):
#     onto = _onto("combined")
#     OntologyCurator(onto).from_hierarchies(class_hier, mere_hier)
#     out = tmp_path / "test.owl"
#     onto.save(dm, str(out))
#     content = _owl_text(out)
#     assert "Chronic_Wound" in content
#     assert "Wound_Bed"     in content

# ============================================================================
# tests/test_inspection.py -- module docstring
# ============================================================================
#   tests/test_output/mere_hierarchy.csv   — MereologicalHierarchy DataFrame

# ============================================================================
# tests/test_inspection.py -- test_build_hierarchies
# ============================================================================
#     pipeline.mere_hier.df.to_csv(OUTPUT_DIR / "mere_hierarchy.csv")

# ============================================================================
# tests/test_inspection.py -- test_build_hierarchies
# ============================================================================
#     print(f"MereHierarchy     → {OUTPUT_DIR / 'mere_hierarchy.csv'}")

# ============================================================================
# tests/test_deprecated_paths.py -- test_export_to_owl_warns_before_it_does_any_work
# ============================================================================
#     pipeline.mere_hier = _hier()

# ============================================================================
# tests/test_orchestrator_curated_wiring.py -- fixture pipeline
# ============================================================================
#     p._mere_hier = None

# ============================================================================
# tests/test_orchestrator_curated_wiring.py -- test_run_build_hierarchies_is_an_alias_for_the_view
# ============================================================================
#     assert view is pipeline.fake_view
#     assert pipeline._mere_hier is None

# ============================================================================
# tests/integration/test_pipeline.py -- tests
# ============================================================================
# @pytest.mark.integration
# def test_mereological_hierarchy_populated(pipeline):
#     # Only meaningful if cache contained part_of / has_part triples
#     # — check structure is valid regardless of content
#     assert isinstance(pipeline.mere_hier.df, pd.DataFrame)
#     assert pipeline.mere_hier.df.dtypes.apply(
#         lambda d: d.kind in ("f", "i")
#     ).all(), "MereologicalHierarchy df must be numeric"
