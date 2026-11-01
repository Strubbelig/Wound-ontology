"""A renamed import is still the import (rule 74).

The naming rules rename inside the pipeline (`specimen from organism` ->
`sample from organism`); the import keeps its own label. Found 2026-10-07: the
export minted OBI_0001479 again as a parentless WONT class, and the core build,
which looked the parent up the same way, kept its children out even after the
export had been fixed. One lookup, `other_names` + `find_imported`, serves both.
"""

from conftest import memory_mapping
from wound_ontology.owl.extend import IMPORT_SKIP, find_imported, other_names
from wound_ontology.utils.label_match import LabelIndex

OBO = "http://purl.obolibrary.org/obo/"


def _index(**labels):
    idx = LabelIndex()
    for label, iri in labels.items():
        idx.add(label.replace("_", " "), OBO + iri)
    return idx


def test_a_renamed_term_is_found_under_its_former_spelling():
    tdict = memory_mapping({"specimen from organism": {"to": None, "pairs": {}}})
    tdict.spell("specimen from organism", "sample from organism", by="pass0")
    idx = _index(specimen_from_organism="OBI_0001479")
    assert idx.get("sample from organism")[0] is None          # the miss the rule is about
    assert find_imported(idx, "Sample From Organism", other_names(tdict)) == \
        (OBO + "OBI_0001479", "specimen from organism")


def test_a_mapped_term_is_its_class_and_its_class_wins_over_old_spellings():
    tdict = memory_mapping({"disease course": {"to": None, "pairs": {}},
                            "disorder course": {"to": "course of the disease process", "pairs": {}}})
    tdict.spell("disease course", "disorder course", by="pass0")
    idx = _index(disease_course="OGMS_0000063", course_of_the_disease_process="MILD_120028")
    hit = find_imported(idx, "Disorder Course", other_names(tdict))
    assert hit == (OBO + "MILD_120028", "course of the disease process")


def test_doid_is_never_reached_this_way():
    tdict = memory_mapping({"metabolic disease": {"to": None, "pairs": {}}})
    tdict.spell("metabolic disease", "metabolic disorder", by="pass0")
    idx = _index(metabolic_disease="DOID_0014667")
    assert find_imported(idx, "Metabolic Disorder", other_names(tdict), IMPORT_SKIP) is None


def test_two_classes_answering_is_no_answer():
    tdict = memory_mapping({"a thing": {"to": None, "pairs": {}}, "the thing": {"to": None, "pairs": {}}})
    tdict.spell("a thing", "thing x", by="pass0")
    tdict.spell("the thing", "thing x", by="pass0")
    idx = _index(a_thing="OBI_1", the_thing="OBI_2")
    assert find_imported(idx, "thing x", other_names(tdict)) == "ambiguous"


def test_a_term_with_no_other_name_is_not_found():
    assert find_imported(_index(swab="OBI_9"), "Deep Tissue Sample", other_names(memory_mapping({}))) is None
