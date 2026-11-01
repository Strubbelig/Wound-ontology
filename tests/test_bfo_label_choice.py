"""One name per BFO class, the same every run (2026-10-29).

Some import modules label BFO_0000147 both `fiat point` (older BFO) and
`zero-dimensional continuant fiat boundary` (BFO 2020). The BFO tree and the
reasoner's skeleton took whichever label the merged graph yielded first, so the
hash seed picked the name and the class hierarchy changed between runs.
"""
from wound_ontology.hierarchies.curated_seed import bfo_label

OBO = "http://purl.obolibrary.org/obo/"


def test_the_extraction_category_name_wins():
    labels = {"zero-dimensional continuant fiat boundary", "fiat point"}
    assert bfo_label(OBO + "BFO_0000147", labels) == "fiat point"


def test_without_a_category_name_the_first_in_sorted_order():
    assert bfo_label(OBO + "BFO_9999999", {"b label", "a label"}) == "a label"


def test_a_category_name_that_is_no_label_of_the_class_is_not_invented():
    assert bfo_label(OBO + "BFO_0000147", {"zero-dimensional continuant fiat boundary"}) \
        == "zero-dimensional continuant fiat boundary"
