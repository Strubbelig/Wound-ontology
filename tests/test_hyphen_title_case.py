"""A title-cased hyphenated word keeps its final s (found 2026-10-05).

`Retro-Rectus` was read as a chemical name with an internal capital and came
back `Retro-Rectu`, while `retro-rectus` stayed whole: one term, two keys, and
the id registry could give it two WONT ids.
"""
import pytest

from wound_ontology.utils.label_match import singular_spelling
from wound_ontology.utils.normalise import normalise


@pytest.mark.parametrize("title, lower", [
    ("Retro-Rectus", "retro-rectus"),
    ("Complete-Thickness", "complete-thickness"),
    ("Neo-Epidermis", "neo-epidermis"),
    ("Pro-Angiogenesis", "pro-angiogenesis"),
    ("Extremity-Loss", "extremity-loss"),
    ("Kruskal-Wallis", "kruskal-wallis"),
    ("Follow-Ups", "follow-ups"),
    ("T-Cells", "t-cells"),
])
def test_title_and_lower_case_share_key_and_name(title, lower):
    assert normalise(title).key == normalise(lower).key
    assert normalise(title).name.lower() == normalise(lower).name.lower()


@pytest.mark.parametrize("label, expected", [
    ("Retro-Rectus", "Retro-Rectus"),
    ("Complete-Thickness", "Complete-Thickness"),
    ("T-Cells", "T-Cell"),
    ("Follow-Ups", "Follow-Up"),
    ("Full-Thickness Wounds", "Full-Thickness Wound"),
    # internal capitals are still left to the acronym rule
    ("IL-6s", "IL-6"),
    ("miRNA-21s", "miRNA-21"),
    ("Post-ARDS", "Post-ARDS"),
])
def test_singular_spelling_on_hyphenated_words(label, expected):
    assert singular_spelling(label) == expected
