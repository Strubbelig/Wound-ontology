"""An anchor mapping is an identity claim, so a model has to make it.

Mapping a store term onto an existing WONT or MILD class says the two ARE the
same class; every downstream axiom then hangs off the ontology's IRI and the
store term is gone. SapBERT proposes those mappings and cannot decide them.
Measured over the 50 anchor proposals of the 2026-09-05 build, cosine similarity
put the right and wrong ones in the same band:

    chronic wounds           -> Chronic wound                       0.9785  right
    clean wound class. grade -> clean-contaminated wound class.g.   0.9736  WRONG
    E. coli                  -> Escherichia coli                    0.9708  right
    Horizontal mattress s.   -> Vertical mattress suture            0.9604  WRONG

No threshold separates that. What does is how the labels differ: 28 of the 50
differed only by case, punctuation or plural and every one was right; all seven
wrong ones were among the 22 where a real word changed. So the surface-form pairs
are kept without a call, and only the rest are adjudicated.

These tests exist to make the failure modes reachable: a pair the model never
answers must NOT quietly stand, and an answer outside the enum must not be read
as agreement.
"""
import pytest

from wound_ontology.mappers import mapping_adjudicator as adj


# ── Triage: which pairs need a model at all ───────────────────────────────────

@pytest.mark.parametrize("a,b,expected", [
    ("wound", "Wound", "identical"),
    ("negative-pressure wound therapy", "Negative pressure wound therapy", "identical"),
    ("Povidone Iodine", "Povidone-iodine", "identical"),
    ("wounds", "Wound", "inflection"),
    ("chronic wounds", "Chronic wound", "inflection"),
    ("malignancies", "Malignancy", "inflection"),
    ("dressing changes", "Dressing change", "inflection"),
    ("Horizontal mattress suture", "Vertical mattress suture", "content"),
    ("clean wound classification grade",
     "clean-contaminated wound classification grade", "content"),
    ("E. coli", "Escherichia coli", "content"),
    ("Skin Scarring", "Scarring", "content"),
    ("Gangrenous", "Gangrene", "content"),
    ("wound closure", "Wound closure process", "content"),
])
def test_label_difference(a, b, expected):
    assert adj.label_difference(a, b) == expected


def test_triage_sends_only_content_pairs():
    surface, content = adj.triage({
        "wounds": "Wound",
        "abscess": "Abscess",
        "Horizontal mattress suture": "Vertical mattress suture",
    })
    assert surface == {"wounds": "Wound", "abscess": "Abscess"}
    assert content == {"Horizontal mattress suture": "Vertical mattress suture"}


# ── The model ─────────────────────────────────────────────────────────────────

class _LLM:
    """Answers from a scripted table; records every pair it was asked about."""

    def __init__(self, answers, echo=lambda s: s):
        self.answers = answers
        self.echo    = echo
        self.asked   = []

    async def adjudicate_mappings_batch(self, candidates):
        class _V:
            def __init__(self, t, c, v, r):
                self.store_term, self.ontology_class = t, c
                self.verdict, self.reason = v, r
        out = []
        for c in candidates:
            pair = (c["store_term"], c["ontology_class"])
            self.asked.append(pair)
            if pair in self.answers:
                verdict, reason = self.answers[pair]
                out.append(_V(self.echo(pair[0]), self.echo(pair[1]), verdict, reason))
        return out


def _run(coro):
    import asyncio
    return asyncio.run(coro)


def test_surface_pairs_never_reach_the_model():
    llm = _LLM({})
    report = _run(adj.adjudicate({"wounds": "Wound", "abscess": "Abscess"}, llm))
    assert llm.asked == []
    assert report.accepted_without_model == {"wounds": "Wound", "abscess": "Abscess"}
    assert report.asked == 0


def test_same_class_is_accepted_and_different_is_refused():
    llm = _LLM({
        ("E. coli", "Escherichia coli"): ("same_class", "abbreviation"),
        ("Horizontal mattress suture", "Vertical mattress suture"):
            ("different", "opposite techniques"),
    })
    report = _run(adj.adjudicate({
        "E. coli": "Escherichia coli",
        "Horizontal mattress suture": "Vertical mattress suture",
    }, llm))
    assert report.accepted_by_model == {"E. coli": "Escherichia coli"}
    assert [p[0] for p in report.refused] == ["Horizontal mattress suture"]


def test_narrower_is_kept_as_a_subsumption_candidate_not_a_mapping():
    """`Skin Scarring` under `Scarring` is not a synonym — but it is not noise
    either, and dropping it would throw away a real subclass edge."""
    llm = _LLM({("Skin Scarring", "Scarring"): ("narrower", "a kind of scarring")})
    report = _run(adj.adjudicate({"Skin Scarring": "Scarring"}, llm))
    assert report.accepted_by_model == {}
    assert report.refused == []
    assert report.subsumption_candidates == [
        ("Skin Scarring", "Scarring", "narrower", "a kind of scarring")]


def test_a_verdict_outside_the_enum_is_refused_not_read_as_agreement():
    llm = _LLM({("wound closure", "Wound closure process"): ("probably_same", "")})
    report = _run(adj.adjudicate({"wound closure": "Wound closure process"}, llm))
    assert report.accepted_by_model == {}
    assert report.refused[0][2] == "probably_same"


def test_an_unanswered_pair_raises_rather_than_standing():
    """The whole point of the step. A mapping nobody looked at must not survive
    just because the model went quiet."""
    llm = _LLM({})
    with pytest.raises(RuntimeError, match="never adjudicated"):
        _run(adj.adjudicate({"wound closure": "Wound closure process"}, llm))


def test_a_paraphrased_echo_still_matches_its_pair():
    """The prompt demands exact strings back; models re-case them anyway. Losing
    the verdict to that would raise on a pair the model actually answered."""
    llm = _LLM({("wound closure", "Wound closure process"): ("same_class", "same")},
               echo=str.upper)
    report = _run(adj.adjudicate({"wound closure": "Wound closure process"}, llm))
    assert report.accepted_by_model == {"wound closure": "Wound closure process"}


def test_a_cached_verdict_is_not_re_asked_but_still_applies():
    cache = {adj._key("E. coli", "Escherichia coli"):
             {"verdict": "same_class", "reason": "abbreviation"}}
    llm = _LLM({})
    report = _run(adj.adjudicate({"E. coli": "Escherichia coli"}, llm, cache=cache))
    assert llm.asked == []
    assert report.accepted_by_model == {"E. coli": "Escherichia coli"}


def test_new_verdicts_are_written_into_the_cache():
    cache: dict = {}
    llm = _LLM({("E. coli", "Escherichia coli"): ("same_class", "abbreviation")})
    _run(adj.adjudicate({"E. coli": "Escherichia coli"}, llm, cache=cache))
    assert cache == {adj._key("E. coli", "Escherichia coli"):
                     {"verdict": "same_class", "reason": "abbreviation"}}


def test_the_definition_is_what_the_model_is_shown():
    """The label is what misled the embedding, so the definition has to reach the
    prompt — a silently absent one would leave the model with the same evidence
    that produced the error."""
    seen = {}

    class _Spy(_LLM):
        async def adjudicate_mappings_batch(self, candidates):
            seen.update({c["store_term"]: c for c in candidates})
            return await super().adjudicate_mappings_batch(candidates)

    llm = _Spy({("Cutaneous wound", "Skin wound"): ("same_class", "")})
    _run(adj.adjudicate(
        {"Cutaneous wound": "Skin wound"}, llm,
        definitions={"Skin wound": "A wound whose disrupted tissue is skin."},
        store_categories={"Cutaneous Wound": "material entity"},
        ontology_categories={"Skin wound": "material entity"},
    ))
    c = seen["Cutaneous wound"]
    assert c["ontology_definition"] == "A wound whose disrupted tissue is skin."
    assert c["store_category"] == "material entity"
    assert c["ontology_category"] == "material entity"


def test_parents_stand_in_where_a_class_has_no_definition():
    seen = {}

    class _Spy(_LLM):
        async def adjudicate_mappings_batch(self, candidates):
            seen.update({c["store_term"]: c for c in candidates})
            return await super().adjudicate_mappings_batch(candidates)

    llm = _Spy({("Horizontal mattress suture", "Vertical mattress suture"):
                ("different", "")})
    _run(adj.adjudicate(
        {"Horizontal mattress suture": "Vertical mattress suture"}, llm,
        parents={"Vertical mattress suture": ["Suture technique"]},
    ))
    c = seen["Horizontal mattress suture"]
    assert c["ontology_definition"] is None
    assert c["ontology_parents"] == ["Suture technique"]


def test_batching_covers_every_pair():
    pairs = {f"term {i} alpha": f"Class {i} beta" for i in range(45)}
    llm = _LLM({(t, c): ("same_class", "") for t, c in pairs.items()})
    report = _run(adj.adjudicate(pairs, llm, batch_size=20))
    assert len(llm.asked) == 45
    assert report.accepted_by_model == pairs


def test_build_term_mapping_refuses_to_run_without_the_llm():
    """The user's rule: the model is integral to the mapping now. No key means no
    mapping, not a mapping built the old way."""
    from wound_ontology.orchestrator import Orchestrator

    pipeline = Orchestrator.__new__(Orchestrator)

    class _NoKey:
        has_credentials = False
    pipeline.llm = _NoKey()
    with pytest.raises(RuntimeError, match="needs the LLM"):
        Orchestrator.run_build_term_mapping(pipeline)


# ── Store-to-store pairs ──────────────────────────────────────────────────────

def test_two_reports_merge_into_one_decision_set():
    """Anchor and store-to-store pairs are asked in separate calls because they
    get different evidence, but the caller withdraws from one set."""
    a = adj.AdjudicationReport(accepted_by_model={"E. coli": "Escherichia coli"},
                               refused=[("x", "y", "different", "")])
    b = adj.AdjudicationReport(accepted_without_model={"wounds": "Wound"},
                               subsumption_candidates=[("p", "q", "narrower", "")])
    a.extend(b)
    assert a.accepted_by_model == {"E. coli": "Escherichia coli"}
    assert a.accepted_without_model == {"wounds": "Wound"}
    assert len(a.refused) == 1 and len(a.subsumption_candidates) == 1


def test_store_to_store_pairs_are_asked_without_categories():
    """Measured 2026-09-06: passing the store's own per-abstract typings in the
    slot the anchor path fills from the skeleton TBox pushed the model into
    refusing `haemorrhage -> Hemorrhage` as a BFO category clash, and took the
    not-synonymous rate on the same 52 pairs from 27% to 46%. There is no
    ontology side here, so there is no category to show."""
    seen = {}

    class _Spy(_LLM):
        async def adjudicate_mappings_batch(self, candidates):
            seen.update({c["store_term"]: c for c in candidates})
            return await super().adjudicate_mappings_batch(candidates)

    llm = _Spy({("haemorrhage", "Hemorrhage"): ("same_class", "spelling variant")})
    report = _run(adj.adjudicate({"haemorrhage": "Hemorrhage"}, llm))
    c = seen["haemorrhage"]
    assert c["store_category"] is None
    assert c["ontology_category"] is None
    assert report.accepted_by_model == {"haemorrhage": "Hemorrhage"}


def test_a_store_to_store_merge_that_loses_a_subtype_is_caught():
    """`diabetes mellitus -> diabetes` was live in the mapping and would have
    folded a subtype into its parent."""
    llm = _LLM({("diabetes mellitus", "diabetes"): ("narrower", "a specific subtype")})
    report = _run(adj.adjudicate({"diabetes mellitus": "diabetes"}, llm))
    assert report.accepted_by_model == {}
    assert report.subsumption_candidates[0][:3] == (
        "diabetes mellitus", "diabetes", "narrower")


# ── it says where it is ──────────────────────────────────────────────────────

def _many(n):
    """`n` content pairs the model must be asked about."""
    return {f"term number {i} thing": f"Class number {i} entity" for i in range(n)}


def test_every_chunk_reports_its_position(capsys):
    """The loop used to print nothing between its first line and its last.

    On 2026-09-26 a build sat in it for 3h40m without a word, and answering
    "is it still running?" took socket byte counters — because a healthy run
    and a dead one produce exactly the same output: none.
    """
    pairs = _many(7)
    llm = _LLM({p: ("same_class", "ok") for p in pairs.items()})
    _run(adj.adjudicate(pairs, llm, batch_size=2))
    out = capsys.readouterr().out
    assert "7 pair(s) to ask in 4 chunk(s)" in out
    for i in range(1, 5):
        assert f"chunk {i}/4" in out, f"chunk {i} never reported itself"


def test_the_report_carries_a_time_estimate(capsys):
    pairs = _many(4)
    llm = _LLM({p: ("same_class", "ok") for p in pairs.items()})
    _run(adj.adjudicate(pairs, llm, batch_size=2))
    out = capsys.readouterr().out
    assert "min gone" in out and "min left" in out


def test_verdicts_are_checkpointed_along_the_way():
    """Four hours of adjudication banked nothing on 2026-09-26, because the
    only save was after the loop and the loop never finished."""
    pairs = _many(6)
    llm = _LLM({p: ("same_class", "ok") for p in pairs.items()})
    saves = []
    cache: dict = {}
    _run(adj.adjudicate(pairs, llm, batch_size=1, cache=cache,
                        checkpoint=lambda: saves.append(len(cache)),
                        checkpoint_every=2))
    assert saves, "nothing was ever checkpointed"
    assert saves == sorted(saves), "the cache should only grow"
    assert saves[0] > 0, "the first checkpoint saved an empty cache"


def test_no_checkpoint_callback_means_no_checkpointing():
    pairs = _many(4)
    llm = _LLM({p: ("same_class", "ok") for p in pairs.items()})
    _run(adj.adjudicate(pairs, llm, batch_size=2))     # must not raise


def test_a_label_says_which_pass_is_talking(capsys):
    """Two adjudications run back to back; their lines have to be tellable
    apart or the progress is worse than none."""
    pairs = _many(2)
    llm = _LLM({p: ("same_class", "ok") for p in pairs.items()})
    _run(adj.adjudicate(pairs, llm, batch_size=1, label="anchor pairs"))
    assert "[anchor pairs]" in capsys.readouterr().out
