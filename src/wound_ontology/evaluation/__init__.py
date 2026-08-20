"""Measuring whether the ontology answers the questions it was built for."""

from wound_ontology.evaluation.competency import (
    CompetencyQuestion,
    CQResult,
    Verdict,
    compile_ask,
    load_questions,
    run_suite,
)

__all__ = [
    "CompetencyQuestion", "CQResult", "Verdict",
    "compile_ask", "load_questions", "run_suite",
]
