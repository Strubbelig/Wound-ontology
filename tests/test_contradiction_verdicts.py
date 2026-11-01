"""The Contradiction Queue's verdicts have to arrive, or not count as made.

The page at claude.ai/artifact/9VpYXEKfmQ1zxmgEfidLG4 holds two queues that
land in two different places, and it stops offering a row the moment it is
answered. So a decision this applier quietly drops is not a decision deferred
— it is one the curator believes they made and nobody will ever be asked
again. Everything unrecognised is collected and named rather than skipped.
"""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "apply_contradiction_verdicts", ROOT / "scripts" / "apply_contradiction_verdicts.py")
mod = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = mod
_spec.loader.exec_module(mod)


def _row(**kw):
    base = {"queue": "contested", "verdict": "in", "term": "pain score", "note": ""}
    base.update(kw)
    return base


# ── what goes where ──────────────────────────────────────────────────────────

def test_a_scope_answer_and_a_pair_answer_are_kept_apart():
    scope, pairs, held, unknown = mod.classify([
        _row(queue="contested", verdict="out"),
        _row(queue="pairs", verdict="same_class", term="a", canonical="b"),
    ])
    assert len(scope) == 1 and len(pairs) == 1 and not held and not unknown


def test_cant_say_is_held_open_not_applied():
    """`unsure` is a real answer — it says the curator looked and could not
    decide. Writing it as a verdict would close a question that is still open."""
    scope, pairs, held, unknown = mod.classify([_row(verdict="unsure")])
    assert not scope and not unknown and len(held) == 1


@pytest.mark.parametrize("row", [
    {"queue": "contested", "verdict": "same_class", "term": "x"},   # pair verdict, scope queue
    {"queue": "pairs", "verdict": "in", "term": "x"},               # scope verdict, pair queue
    {"queue": "pairs", "verdict": "probably", "term": "x"},         # invented verdict
    {"verdict": "in", "term": "x"},                                 # no queue at all
])
def test_anything_it_cannot_place_is_named_not_dropped(row):
    scope, pairs, held, unknown = mod.classify([row])
    assert not scope and not pairs and not held
    assert unknown == [row], "a decision this script cannot apply must be reported"


def test_reverse_is_a_pair_verdict_the_applier_knows():
    """The curator's fifth button: one class, named the wrong way round.

    It is two writes, not one — the inverse entry AND a refusal on the
    original pair. Without the refusal the next build proposes the direction
    that was just rejected, and the adjudication cache approves it from
    memory; that is the exact failure rule 37 was written for.
    """
    scope, pairs, held, unknown = mod.classify(
        [_row(queue="pairs", verdict="reverse", term="a", canonical="b")])
    assert len(pairs) == 1 and not unknown


def test_every_button_on_the_page_is_a_verdict_the_applier_accepts():
    """The page and this script are two lists of the same vocabulary. When
    they drift, the curator's answer lands in `unrecognised` and is lost."""
    on_the_page = {"same_class", "narrower", "broader", "reverse", "different"}
    assert on_the_page == mod.PAIR
    assert {"in", "out", "unsure"} == mod.SCOPE


# ── reading the store's export ───────────────────────────────────────────────

def test_it_reads_one_document_per_file(tmp_path):
    (tmp_path / "c0000.json").write_text(json.dumps(_row()))
    (tmp_path / "d0000.json").write_text(json.dumps(
        _row(queue="pairs", verdict="different", term="a", canonical="b")))
    assert len(mod._load(tmp_path)) == 2


def test_it_reads_a_file_holding_a_list_of_documents(tmp_path):
    """`read_db` writes one file per document, but a hand-assembled export is
    a list — both have arrived before."""
    (tmp_path / "all.json").write_text(json.dumps([_row(), _row(verdict="out")]))
    assert len(mod._load(tmp_path)) == 2


def test_it_looks_in_subdirectories(tmp_path):
    """The store's export nests by collection path."""
    nested = tmp_path / "decisions"
    nested.mkdir()
    (nested / "c0000.json").write_text(json.dumps(_row()))
    assert len(mod._load(tmp_path)) == 1


def test_an_undecided_row_is_not_a_decision(tmp_path):
    """A document with no verdict is a row the page touched and left open."""
    (tmp_path / "c0000.json").write_text(json.dumps({"queue": "contested", "term": "x"}))
    assert mod._load(tmp_path) == []


# ── the question the decision answers ────────────────────────────────────────
#
# The page stores what the curator SAID -- term, verdict, note -- and not what
# they were asked, so a pair decision arrives with no canonical. Reading it
# back off the live mapping is not enough: most of these pairs are ones the
# adjudicator withdrew, so the term has no live `to`, and on the first real
# run 634 of the 695 pair decisions resolved to nothing and printed
# `NO CANONICAL ... skipped`. The queue payload has it, under the same row id.

def _queue(tmp_path, body):
    path = tmp_path / "payload.json"
    path.write_text(json.dumps(body), encoding="utf-8")
    return path


def test_the_row_id_is_the_document_name(tmp_path):
    """The store carries the id as the file name, never as a field."""
    (tmp_path / "d0007.json").write_text(
        json.dumps(_row(queue="pairs", verdict="same_class", term="a")),
        encoding="utf-8")
    assert mod._load(tmp_path)[0]["id"] == "d0007"


def test_the_canonical_comes_from_the_queue_the_row_was_asked_about(tmp_path):
    rows = [_row(queue="pairs", verdict="same_class", term="a", id="d0001")]
    payload = _queue(tmp_path, {"disagreements": [
        {"id": "d0000", "term": "z", "canonical": "zz"},
        {"id": "d0001", "term": "a", "canonical": "b"},
    ]})
    assert mod._with_queue(rows, payload)[0]["canonical"] == "b"


def test_a_decision_that_already_names_its_canonical_keeps_it(tmp_path):
    rows = [_row(queue="pairs", verdict="same_class", term="a",
                 canonical="chosen", id="d0001")]
    payload = _queue(tmp_path, {"disagreements": [
        {"id": "d0001", "term": "a", "canonical": "b"}]})
    assert mod._with_queue(rows, payload)[0]["canonical"] == "chosen"


def test_a_payload_that_asks_about_another_term_stops_the_run(tmp_path):
    """The ids are positional. A payload rebuilt against a different queue
    lines every decision up against the wrong question, and writing 695
    verdicts onto the wrong pairs is not something to discover afterwards."""
    rows = [_row(queue="pairs", verdict="same_class", term="a", id="d0001")]
    payload = _queue(tmp_path, {"disagreements": [
        {"id": "d0001", "term": "SOMETHING ELSE", "canonical": "b"}]})
    with pytest.raises(SystemExit) as caught:
        mod._with_queue(rows, payload)
    assert "DIFFERENT term" in str(caught.value)


def test_a_decision_with_no_row_in_the_queue_is_named_not_dropped(tmp_path, capsys):
    rows = [_row(queue="pairs", verdict="same_class", term="a", id="d9999")]
    payload = _queue(tmp_path, {"disagreements": [
        {"id": "d0001", "term": "a", "canonical": "b"}]})
    mod._with_queue(rows, payload)
    assert "d9999" in capsys.readouterr().out


# ── a canonical can only point at one term ───────────────────────────────────

def test_a_reversal_onto_a_canonical_that_is_spoken_for_is_not_written():
    clashes = mod.reversal_clashes([("a", "b")], {"b": "c"}.get)
    assert list(clashes) == [("a", "b")]
    assert "already maps to 'c'" in clashes[("a", "b")]


def test_a_reversal_onto_a_free_canonical_is_written():
    assert mod.reversal_clashes([("a", "b")], {}.get) == {}


def test_the_canonical_already_pointing_at_the_term_is_not_a_clash():
    """Re-applying the same verdict is not a collision with itself."""
    assert mod.reversal_clashes([("a", "b")], {"b": "a"}.get) == {}


def test_two_reversals_claiming_one_canonical_both_lose():
    """The standing check cannot see the batch, so this needs its own.

    On the 2026-09-27 queue `inflammation level` and `inflammatory level`
    both reversed onto `levels of inflammation`, and `near-infrared
    radiation` and `near-infrared light` both onto `near-infrared`. Neither
    canonical was mapped beforehand, so both passed the standing check and
    the second write replaced the first: of 179 reversals, 177 landed. Which
    spelling a canonical should point at is the curator's question, so
    neither claim wins it by being written last.
    """
    clashes = mod.reversal_clashes(
        [("inflammation level", "levels of inflammation"),
         ("inflammatory level", "levels of inflammation"),
         ("a", "b")], {}.get)
    assert ("a", "b") not in clashes
    assert set(clashes) == {("inflammation level", "levels of inflammation"),
                            ("inflammatory level", "levels of inflammation")}
    assert "2 verdicts claim it" in clashes[("inflammation level",
                                             "levels of inflammation")]


# ── a verdict the curator supersedes is still a verdict they made ────────────

def test_a_superseded_curator_verdict_is_kept_not_overwritten():
    """660 of the 695 pairs already carried one, from the phone review."""
    pair = {"curator": {"verdict": "refused", "reason": "the review UI"}}
    mod.record_curator(pair, {"verdict": "reverse", "reason": "the queue"})
    assert pair["curator"]["verdict"] == "reverse"
    assert [h["verdict"] for h in pair["curator_history"]] == ["refused"]


def test_the_first_curator_verdict_on_a_pair_starts_no_history():
    pair = {}
    mod.record_curator(pair, {"verdict": "same_class"})
    assert pair == {"curator": {"verdict": "same_class"}}


def test_re_applying_the_same_verdict_does_not_grow_the_history():
    """The applier is safe to run twice; running it twice is not a decision."""
    pair, j = {}, {"verdict": "same_class", "when": "t"}
    mod.record_curator(pair, j)
    mod.record_curator(pair, dict(j))
    assert "curator_history" not in pair


# ── a confirmation is a mapping, not a note ─────────────────────────────────

def test_a_confirmation_with_nothing_in_its_way_is_written():
    assert mod.confirmation_clashes([("a", "b")], {}.get) == {}


def test_a_confirmation_onto_a_term_that_maps_elsewhere_is_not_written():
    """`diabetes mellitus patient` maps to `diabetic patient`; the queue
    confirmed it against `patients with diabetes`. Which is the canonical is
    a question nobody in this queue was asked."""
    clashes = mod.confirmation_clashes(
        [("diabetes mellitus patient", "patients with diabetes")],
        {"diabetes mellitus patient": "diabetic patient"}.get)
    assert "already maps to 'diabetic patient'" in list(clashes.values())[0]


def test_a_confirmation_of_the_mapping_that_already_stands_is_not_a_clash():
    assert mod.confirmation_clashes([("a", "b")], {"a": "b"}.get) == {}


def test_a_pair_that_names_one_term_twice_is_not_a_mapping():
    """`proliferative phase -> proliferative phase` came through the queue."""
    clashes = mod.confirmation_clashes([("x", "x")], {}.get)
    assert clashes[("x", "x")] == "the pair names one term twice"


# ── a mapping has to bottom out in a name ───────────────────────────────────

def test_an_edge_that_closes_a_two_cycle_is_not_written():
    """`orthopedics -> orthopedic` stood; the queue confirmed the other way.

    The source was free, so every other check passed, and the write closed a
    two-cycle. 26 of them on the 2026-09-27 queue, all this shape.
    """
    looping = mod.cycles_closed([("orthopedic", "orthopedics")], set(),
                                {"orthopedics": "orthopedic"}.get)
    assert looping == {("orthopedic", "orthopedics")}


def test_an_edge_onto_a_name_is_written():
    assert mod.cycles_closed([("a", "b")], set(), {}.get) == set()


def test_a_chain_is_not_a_cycle():
    """`a -> b -> c` is fine; resolve_chains collapses it to `a -> c`."""
    assert mod.cycles_closed([("a", "b")], set(), {"b": "c"}.get) == set()


def test_a_cycle_the_batch_is_about_to_break_is_not_a_cycle():
    """The reversal nulls `b -> a` before it writes `a -> b`, so asking the
    graph as it stands would refuse a write that is perfectly safe."""
    assert mod.cycles_closed([("a", "b")], {"b"}, {"b": "a"}.get) == set()


def test_a_longer_loop_is_caught_too():
    looping = mod.cycles_closed([("a", "b")], set(), {"b": "c", "c": "a"}.get)
    assert looping == {("a", "b")}


def test_both_halves_of_a_loop_the_batch_writes_itself_are_held_back():
    looping = mod.cycles_closed([("a", "b"), ("b", "a")], set(), {}.get)
    assert looping == {("a", "b"), ("b", "a")}


def test_an_edge_that_runs_into_someone_elses_loop_is_still_written():
    """`a -> b` is a sound arrow. That `b` and `c` point at each other is a
    knot that was there before and is not this edge's doing; refusing `a`
    over it would hold back a decision for someone else's problem."""
    assert mod.cycles_closed([("a", "b")], set(), {"b": "c", "c": "b"}.get) == set()
