# -*- coding: utf-8 -*-
"""Per-batch reasoner gate (C7).

Round 1 added disjointness axioms to MILD and WONT. Until now nothing enforced
them at extraction time: the axioms could only be checked by a manual audit,
which is how `wound infecting disposition ⊑ material entity` survived. This gate
runs ELK over the skeleton TBox plus one batch of extracted content, and refuses
whatever the reasoner proves inconsistent.

Failure policy is QUARANTINE, not reject-the-batch: the offending terms and
relations are isolated with the reasoner's own explanation, and everything else
is committed. This matches how FCA candidates and undecided cells are already
handled — isolate the uncertain part rather than discarding good work or letting
bad work through.

Terms that grounded to an existing MILD/WONT class are asserted **against that
class's real IRI**, so a relation on a known class is checked against that
class's actual axioms rather than against a fresh, unconstrained stand-in.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import signal
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import rdflib
from rdflib import OWL, RDF, RDFS, URIRef

from wound_ontology.llm.extraction_models import CATEGORY_IRI, RELATION_IRI

BATCH_NS = "urn:wont:batch#"
_UNSAT_RE = re.compile(r"unsatisfiable:\s*(\S+)")
_MAX_PASSES = 12  # a pass per provenance tier, plus explanation-guided passes (2026-10-03)
#: The edge gate judges the empty classes whose kept parents are satisfiable
#: first (2026-10-29), so a chain of empty classes takes a pass per level.
_MAX_EDGE_PASSES = 30


@dataclass
class EdgeGateResult:
    """Subsumption edges the reasoner accepted or refused."""

    accepted: list = field(default_factory=list)
    quarantined: list = field(default_factory=list)
    unsatisfiable: list[str] = field(default_factory=list)
    explanation: str = ""
    skipped: str | None = None
    #: quarantined edge -> the provenance it carried, when the caller supplied one.
    quarantined_sources: dict = field(default_factory=dict)
    #: edges kept because a lower-ranked edge on the same child was dropped instead.
    spared: list = field(default_factory=list)
    #: (child, parent) -> why THIS edge was refused (rule 89: one reason per verdict).
    why: dict = field(default_factory=dict)

    @property
    def clean(self) -> bool:
        return not self.quarantined

    def summary(self) -> str:
        if self.skipped:
            return f"edge gate SKIPPED ({self.skipped})"
        if self.clean:
            return f"edge gate: clean ({len(self.accepted)} edges)"
        return (f"edge gate: {len(self.quarantined)} edge(s) quarantined, "
                f"{len(self.accepted)} accepted")


@dataclass
class GateResult:
    """What the gate accepted, what it held back, and why."""

    accepted_entities: list = field(default_factory=list)
    accepted_relations: list = field(default_factory=list)
    quarantined_entities: list = field(default_factory=list)
    quarantined_relations: list = field(default_factory=list)
    unsatisfiable: list[str] = field(default_factory=list)
    explanation: str = ""
    skipped: str | None = None          # set when the gate could not run
    #: one line per reasoner run that had to be asked again without WONT's
    #: named individuals, saying which individuals sat in which emptied class.
    without_individuals: list[str] = field(default_factory=list)
    #: classes still empty when the gate stopped (pass limit, or no cause found).
    still_empty: list[str] = field(default_factory=list)
    #: one entry per cause found (`ReasonerGate._causes`): what kind of clash,
    #: and the statements on each side -- what the curator decides between.
    causes: list[dict] = field(default_factory=list)
    #: (subject, predicate, object) -> why THIS relation was held back (rule 89:
    #: one reason per verdict, not the run's one explanation on every item).
    why: dict = field(default_factory=dict)

    @property
    def clean(self) -> bool:
        return not self.quarantined_entities and not self.quarantined_relations

    def summary(self) -> str:
        if self.skipped:
            return f"reasoner gate SKIPPED ({self.skipped})"
        note = (f" [{len(self.without_individuals)} reasoner run(s) were inconsistent "
                f"with WONT's individuals and were asked again without them]"
                if self.without_individuals else "")
        if self.still_empty:
            note += f" [*** {len(self.still_empty)} class(es) STILL empty ***]"
        if self.clean:
            return (f"reasoner gate: clean "
                    f"({len(self.accepted_entities)} terms, "
                    f"{len(self.accepted_relations)} relations){note}")
        return (f"reasoner gate: {len(self.quarantined_entities)} term(s) and "
                f"{len(self.quarantined_relations)} relation(s) quarantined; "
                f"{len(self.accepted_entities)} terms, "
                f"{len(self.accepted_relations)} relations committed{note}")


def _run_robot(cmd: list[str], timeout: int) -> subprocess.CompletedProcess:
    """Run ROBOT and, on a timeout, end ALL of it.

    `robot` is a shell script that starts Java. `subprocess.run` kills only the
    script on a timeout, and the Java process ran on alone: the explanation
    that timed out on 2026-10-08 09:10 was still reasoning 25 hours later at
    ~180 % CPU, slowing every run after it. ROBOT now gets its own process
    group, and a timeout ends the group before TimeoutExpired goes on."""
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, start_new_session=True)
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            # Already gone: nothing left to end. Said aloud because it means
            # ROBOT exited in the instant between the timeout and the kill.
            print(f"[ReasonerGate] ROBOT (process group {proc.pid}) had already "
                  f"exited when its {timeout} s timeout fired; nothing to kill")
        proc.communicate()
        raise
    return subprocess.CompletedProcess(cmd, proc.returncode, out, err)


def without_individuals(graph: rdflib.Graph) -> tuple[rdflib.Graph, dict]:
    """A copy of `graph` with every named individual and every triple that
    mentions one taken out, and {individual -> the classes it was typed with}.
    The input graph is not changed."""
    bare = rdflib.Graph()
    bare += graph
    removed = {}
    for ind in set(bare.subjects(RDF.type, OWL.NamedIndividual)):
        removed[ind] = {t for t in bare.objects(ind, RDF.type)
                        if isinstance(t, URIRef) and t != OWL.NamedIndividual}
        for t in list(bare.triples((ind, None, None))):
            bare.remove(t)
        for t in list(bare.triples((None, None, ind))):
            bare.remove(t)
    return bare, removed


def _slug(label: str) -> str:
    """Batch-local IRI fragment for a term label. INJECTIVE by construction.

    The readable part alone is not: "wound care practice" and "wound-care
    practice" both reduce to `wound_care_practice`, and on a real 142-abstract
    batch they did. Two distinct store terms then shared one IRI, which
    collected BOTH their category parents -- material entity AND process -- and
    ELK duly reported the merged class unsatisfiable. The gate blamed the terms
    for a contradiction it had manufactured itself.

    Merging near-duplicate surface forms is the term mapper's job, upstream and
    reviewable. The gate must reason about exactly the terms it was given, so
    the fragment carries a digest of the ORIGINAL label and stays unique.
    """
    readable = re.sub(r"[^0-9a-zA-Z]+", "_", label).strip("_") or "term"
    digest = hashlib.sha1(label.encode("utf-8")).hexdigest()[:8]
    return f"{readable}_{digest}"


class ReasonerGate:
    def __init__(
        self,
        skeleton_path: str | Path,
        robot_cmd: str = "robot",
        reasoner: str = "ELK",
        timeout: int = 300,
    ) -> None:
        self.skeleton_path = Path(skeleton_path)
        self.robot_cmd = robot_cmd
        self.reasoner = reasoner
        self.timeout = timeout
        #: filled by `_reason` whenever it had to drop the individuals; `check`
        #: empties it at the start and hands it on in its result.
        self.individual_notes: list[str] = []
        self.cause_notes: list[dict] = []

    # ── category reconciliation ────────────────────────────────────────────
    #
    # Stage-1 typing makes ONE categorical choice per term per abstract. It
    # cannot stop two abstracts choosing differently, and on a 142-abstract
    # pilot 61 terms were typed two or more ways. Dropping them loses real
    # content; last-writer-wins invents agreement that does not exist.
    #
    # The honest third option is to retreat to what the abstracts DO agree on:
    # the most specific category that subsumes every one they proposed. That
    # ancestor is read out of the skeleton TBox, so MILD decides it, not a table
    # written here. `process` + `process boundary` agree on `occurrent`;
    # `material entity` + `process` agree on nothing below `entity` and stay
    # excluded, because there is no honest answer for them.

    def _category_ancestors(self) -> dict[str, set[str]]:
        """{category value -> IRIs subsuming it, itself included}, from the skeleton."""
        if getattr(self, "_cat_anc", None) is not None:
            return self._cat_anc
        g = rdflib.Graph()
        g.parse(str(self.skeleton_path), format="turtle")

        def ancestors(iri: str) -> set[str]:
            seen, stack = {iri}, [URIRef(iri)]
            while stack:
                for parent in g.objects(stack.pop(), RDFS.subClassOf):
                    if isinstance(parent, URIRef) and str(parent) not in seen:
                        seen.add(str(parent))
                        stack.append(parent)
            return seen

        self._cat_anc = {name: ancestors(iri) for name, iri in CATEGORY_IRI.items()}
        return self._cat_anc

    def least_common_category(self, categories) -> str | None:
        """Most specific BFO category subsuming all of `categories`, or None.

        None means the disagreement is irreconcilable at category level -- the
        proposed types share no common ancestor that is itself one of the
        categories the extractor can assign. Those stay out of the gate and get
        reported, rather than being forced to a value nobody proposed.
        """
        # Callers pass whatever the store holds, so names are declared first:
        # an unrecognised name falls through to None below and the disagreement
        # is reported as irreconcilable, which is the honest answer for a name
        # that is not a category at all -- but must NOT be the answer for one
        # that merely arrived spelled the old way.
        from wound_ontology.llm.category_vocab import declared_category
        cats = sorted({declared_category(c) or c for c in categories})
        if not cats:
            return None
        if len(cats) == 1:
            return cats[0]
        anc = self._category_ancestors()
        if any(c not in anc for c in cats):
            return None
        shared = set.intersection(*(anc[c] for c in cats))
        # Keep only shared IRIs that are themselves assignable categories, then
        # take the most specific: the one with the longest ancestor chain.
        by_iri = {iri: name for name, iri in CATEGORY_IRI.items()}
        options = [by_iri[i] for i in shared if i in by_iri]
        if not options:
            return None
        return max(options, key=lambda n: len(anc[n]))

    # ── availability ───────────────────────────────────────────────────────
    def available(self) -> str | None:
        """None if the gate can run, else the reason it cannot."""
        if shutil.which(self.robot_cmd) is None:
            return f"{self.robot_cmd!r} not on PATH"
        if not self.skeleton_path.exists():
            return f"skeleton TBox missing at {self.skeleton_path}"
        return None

    # ── batch graph ────────────────────────────────────────────────────────
    def _iri_for(self, entity) -> URIRef:
        """Grounded terms use their real IRI; new terms get a batch-local one."""
        if getattr(entity, "grounded_to", None):
            return URIRef(entity.grounded_to)
        return URIRef(BATCH_NS + _slug(entity.label))

    def build_batch_graph(self, entities, relations) -> rdflib.Graph:
        g = rdflib.Graph()
        g.parse(str(self.skeleton_path), format="turtle")
        by_label = {e.label: self._iri_for(e) for e in entities}

        for e in entities:
            iri = by_label[e.label]
            if e.grounded_to:
                continue          # already fully axiomatised in the skeleton
            g.add((iri, RDF.type, OWL.Class))
            g.add((iri, RDFS.label, rdflib.Literal(e.label)))
            g.add((iri, RDFS.subClassOf, URIRef(CATEGORY_IRI[e.category.value])))

        for r in relations:
            s_iri, o_iri = by_label.get(r.subject), by_label.get(r.object)
            prop = RELATION_IRI.get(r.predicate.value)
            if s_iri is None or o_iri is None or prop is None:
                continue
            restriction = rdflib.BNode()
            g.add((restriction, RDF.type, OWL.Restriction))
            g.add((restriction, OWL.onProperty, URIRef(prop)))
            g.add((restriction, OWL.someValuesFrom, o_iri))
            g.add((s_iri, RDFS.subClassOf, restriction))
            g.add((URIRef(prop), RDF.type, OWL.ObjectProperty))
        return g

    def _locally_inconsistent(self, entities, relations) -> list:
        """The relations that contradict the ontology ON THEIR OWN.

        Each relation is asserted on a fresh pair of classes -- a copy of its
        subject and a copy of its object, each typed only with the term's
        category (and its grounded class, if any) -- so it meets the skeleton's
        axioms and nothing else. One reasoner run tests all of them; a copy
        that is unsatisfiable names a relation that is wrong by itself
        (`healing --has as process boundary at end--> completely healed`, a
        quality where an instant is required), not one caught up in a
        neighbour's contradiction. Holding those back first is what keeps one
        bad sentence on a hub term from quarantining everything that touches
        it: on 2026-09-30 that sentence made `healing` unsatisfiable, and with
        it 7,163 classes and 20,777 relations.
        """
        g = rdflib.Graph()
        g.parse(str(self.skeleton_path), format="turtle")
        by_label = {e.label: e for e in entities}
        probes = {}
        for n, r in enumerate(relations):
            se, oe = by_label.get(r.subject), by_label.get(r.object)
            prop = RELATION_IRI.get(r.predicate.value)
            if se is None or oe is None or prop is None:
                continue
            s_c = URIRef(f"{BATCH_NS}probe_s_{n}")
            o_c = URIRef(f"{BATCH_NS}probe_o_{n}")
            for c, e in ((s_c, se), (o_c, oe)):
                g.add((c, RDF.type, OWL.Class))
                g.add((c, RDFS.subClassOf, URIRef(CATEGORY_IRI[e.category.value])))
                if getattr(e, "grounded_to", None):
                    g.add((c, RDFS.subClassOf, URIRef(e.grounded_to)))
            restriction = rdflib.BNode()
            g.add((restriction, RDF.type, OWL.Restriction))
            g.add((restriction, OWL.onProperty, URIRef(prop)))
            g.add((restriction, OWL.someValuesFrom, o_c))
            g.add((s_c, RDFS.subClassOf, restriction))
            g.add((URIRef(prop), RDF.type, OWL.ObjectProperty))
            probes[str(s_c)] = r
        unsat = self._unsatisfiable(g)
        return [r for iri, r in probes.items() if iri in unsat]

    # ── reasoning ──────────────────────────────────────────────────────────
    def _unsatisfiable(self, graph: rdflib.Graph) -> set[str]:
        """IRIs ELK finds unsatisfiable in `graph`.

        An inconsistent ontology names no culprit. Here it means that a class
        the batch emptied holds one of WONT's 48 named individuals (Wagner
        grades, zones of a burn): an empty class with a member in it is a
        contradiction about the whole ontology, not about a class. On
        2026-10-07 that stopped the relation gate cold ("The ontology is
        inconsistent"), and the run went on without it. The question is then
        asked again without the individuals, so the emptied classes are named
        -- as `build_wont_core.elk_unsat` and the edge graph already do -- and
        that is said, loudly, with the individuals and the classes they sit in
        (rule 1). If the ontology is inconsistent without them too, or holds
        none, or no class comes back empty, nothing can be named and it raises.
        """
        try:
            return self._run_elk(graph)
        except RuntimeError as exc:
            if "inconsistent" not in str(exc):
                raise
            first = exc
        bare, removed = without_individuals(graph)
        if not removed:
            raise first
        found = self._run_elk(bare)
        if not found:
            raise RuntimeError(
                f"ELK: the ontology is inconsistent with WONT's {len(removed)} named "
                f"individual(s), and without them no class is unsatisfiable -- the "
                f"contradiction is not an emptied class; nothing can be called "
                f"clean, look by hand:\n{first}")
        msg = self._describe_removed(graph, removed, found)
        print(f"[ReasonerGate] *** {msg} ***", flush=True)
        self.individual_notes.append(msg)
        return found

    @staticmethod
    def _describe_removed(graph: rdflib.Graph, removed: dict, found: set[str]) -> str:
        """Plain words: which individuals were set aside, and which emptied
        class each of them sits in."""
        def name(node) -> str:
            lab = graph.value(node, RDFS.label)
            return f"{lab} <{node}>" if lab is not None else f"<{node}>"

        held = sorted((name(ind), name(c)) for ind, types in removed.items()
                      for c in types if str(c) in found)
        msg = (f"inconsistent with WONT's {len(removed)} named individual(s); asked "
               f"again without them: {len(found)} class(es) are unsatisfiable")
        if held:
            shown = "; ".join(f"{i} is a member of {c}" for i, c in held[:10])
            more = f" (and {len(held) - 10} more)" if len(held) > 10 else ""
            return (f"{msg}. {len(held)} individual(s) sit in a class that is now "
                    f"empty: {shown}{more}")
        return (f"{msg}. None of the individuals' own classes is among them, so "
                f"the contradiction reached the individuals another way -- look "
                f"at the unsatisfiable classes by hand")

    def _run_elk(self, graph: rdflib.Graph) -> set[str]:
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "batch.ttl"
            graph.serialize(destination=str(src), format="turtle")
            proc = _run_robot(
                [self.robot_cmd, "reason", "--input", str(src),
                 "--reasoner", self.reasoner,
                 "--equivalent-classes-allowed", "all",
                 "--output", str(Path(td) / "out.owl")],
                timeout=self.timeout,
            )
        out = proc.stdout + proc.stderr
        found = set(_UNSAT_RE.findall(out))
        # ROBOT exits non-zero when it lists unsatisfiable classes -- that is a
        # result. Any other failure (an inconsistent ontology, a crash, too little
        # memory) used to come back as the empty set, i.e. "clean": on 2026-10-03
        # the hierarchy gate reported 36,644 edges clean while `Allergy` sat
        # under both disposition and material disease entity.
        if proc.returncode != 0 and not found:
            tail = "\n".join(out.strip().splitlines()[-12:])
            raise RuntimeError(f"ELK did not run to a result (exit {proc.returncode}); "
                               f"nothing can be called clean:\n{tail}")
        return found

    _AXIOM_RE = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)\s+SubClassOf\s+\[[^\]]*\]\(([^)\s]+)\)\s*$")

    def _explained_pairs(self, graph: rdflib.Graph) -> set[tuple[str, str]]:
        """(child IRI, parent IRI) of every named SubClassOf axiom in one
        explanation per root unsatisfiable class."""
        text = self._explain(graph, max_expl=1)
        pairs = set()
        for line in text.splitlines():
            m = self._AXIOM_RE.search(line.strip().lstrip("-").strip())
            if m:
                pairs.add((m.group(1), m.group(2)))
        return pairs

    def _explain(self, graph: rdflib.Graph, max_expl: int = 5) -> str:
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "batch.ttl"
            out = Path(td) / "expl.md"
            graph.serialize(destination=str(src), format="turtle")
            try:
                _run_robot(
                    [self.robot_cmd, "explain", "--input", str(src),
                     "--reasoner", self.reasoner, "-M", "unsatisfiability",
                     "-u", "root", "-m", str(max_expl), "--explanation", str(out)],
                    timeout=self.timeout,
                )
            except subprocess.TimeoutExpired:
                # The explanation is a report, not the verdict: the unsatisfiable
                # classes are already known and are quarantined either way. Losing
                # the whole reasoner run to a slow explanation (2026-09-30) was
                # worse than saying it timed out.
                msg = (f"robot explain timed out after {self.timeout} s; the "
                       f"unsatisfiable classes are listed in the gate report")
                print(f"[ReasonerGate] {msg}")
                return msg
            return out.read_text(encoding="utf-8") if out.exists() else ""

    # ── the gate ───────────────────────────────────────────────────────────
    def check(self, entities, relations) -> GateResult:
        why = self.available()
        if why:
            return GateResult(accepted_entities=list(entities),
                              accepted_relations=list(relations), skipped=why)

        ents, rels = list(entities), list(relations)
        self.individual_notes = []
        self.cause_notes = []
        self.cause_why: dict = {}
        q_ents: list = []
        q_rels: list = []
        why: dict = {}
        key = lambda r: (r.subject, r.predicate.value, r.object)   # noqa: E731
        unsat_seen: set[str] = set()
        explanation = ""

        # An abstract that says something about the bare word `tendency` (or
        # `process`, `disposition`) is not stating an axiom about the BFO/MILD
        # category itself. Asserted on the category class it is one: on
        # 2026-09-30 `tendency --has realization--> therapy`, once `therapy`
        # was ruled an information entity, made MILD's tendency class
        # unsatisfiable, and with it every tendency in the store and the
        # curated classes that mention one -- 7,361 classes and 20,844
        # relations quarantined for one sentence. Such a relation is held back
        # here, by name, and reported with the rest.
        cat_iris = {str(v) for v in CATEGORY_IRI.values()}
        by_label0 = {e.label: str(self._iri_for(e)) for e in ents}
        on_category = [r for r in rels if by_label0.get(r.subject) in cat_iris]
        if on_category:
            print(f"[ReasonerGate] {len(on_category)} relation(s) whose subject is a "
                  f"BFO/MILD category class held back, e.g. "
                  f"{[(r.subject, r.predicate.value, r.object) for r in on_category[:3]]}")
            q_rels += on_category
            for r in on_category:
                why[key(r)] = (f"its subject {r.subject!r} is the BFO/MILD category itself; a sentence "
                               f"about the bare word is no axiom about the category")
            held = {id(r) for r in on_category}
            rels = [r for r in rels if id(r) not in held]

        local = self._locally_inconsistent(ents, rels) if rels else []
        if local:
            print(f"[ReasonerGate] {len(local)} relation(s) contradict the ontology on "
                  f"their own and are held back before the batch is reasoned, e.g. "
                  f"{[(r.subject, r.predicate.value, r.object) for r in local[:3]]}")
            q_rels += local
            for r in local:
                why[key(r)] = (f"contradicts the ontology on its own: {r.subject!r} typed as it is "
                               f"cannot {r.predicate.value} {r.object!r} typed as it is")
            held = {id(r) for r in local}
            rels = [r for r in rels if id(r) not in held]

        for _ in range(_MAX_PASSES):
            g = self.build_batch_graph(ents, rels)
            n_notes = len(self.individual_notes)
            unsat = self._unsatisfiable(g)
            if not unsat:
                break
            unsat_seen |= unsat
            if not explanation:
                # An explanation is asked of the graph that gave the answer:
                # with the individuals in, it is inconsistent and explains
                # nothing.
                asked_bare = len(self.individual_notes) > n_notes
                explanation = self._explain(without_individuals(g)[0] if asked_bare else g)

            by_label = {e.label: str(self._iri_for(e)) for e in ents}

            # Causes first (2026-10-08). Holding back every relation that
            # touches an empty class, all at once, cannot tell the relation
            # that empties a class from the thousands that merely point at
            # it: on 2026-10-08 31 terms whose relations asked for two kinds
            # of thing at once (`wound size` inheres in a wound AND is about
            # something) emptied `wound size`, through it `Wound`, and
            # through that 6,756 classes -- and 20,363 of 24,584 relations
            # were held back. Only the causes go; the next pass re-asks.
            causes, how = self._causes(ents, rels, unsat, by_label)
            if causes:
                print(f"[ReasonerGate] pass: {len(unsat)} empty class(es); holding back "
                      f"{len(causes)} relation(s) that empty a class themselves "
                      f"({how}), e.g. "
                      f"{[(r.subject, r.predicate.value, r.object) for r in causes[:3]]}",
                      flush=True)
                q_rels += causes
                for r in causes:
                    why[key(r)] = self.cause_why.get(id(r)) or f"empties a class by itself ({how})"
                held = {id(r) for r in causes}
                rels = [r for r in rels if id(r) not in held]
                continue

            print(f"[ReasonerGate] *** {len(unsat)} empty class(es) and no relation "
                  f"found that empties one by itself; holding back EVERY relation that "
                  f"touches an empty class, the old way. Expect collateral loss. ***",
                  flush=True)
            bad_labels = {lab for lab, iri in by_label.items() if iri in unsat}

            # A pre-existing class made unsatisfiable means the batch RELATION is
            # at fault, not the term — the class was satisfiable before the batch.
            touched = {lab for lab, iri in by_label.items()
                       if iri in unsat and not iri.startswith(BATCH_NS)}

            keep_rels, drop_rels = [], []
            for r in rels:
                if r.subject in bad_labels or r.object in bad_labels or \
                        r.subject in touched or r.object in touched:
                    drop_rels.append(r)
                else:
                    keep_rels.append(r)

            # Only quarantine a TERM when its own minted class is unsatisfiable.
            new_bad = {lab for lab in bad_labels
                       if by_label[lab].startswith(BATCH_NS)}
            keep_ents = [e for e in ents if e.label not in new_bad]
            drop_ents = [e for e in ents if e.label in new_bad]

            if not drop_ents and not drop_rels:
                break                       # cannot attribute further; stop
            q_ents += drop_ents
            q_rels += drop_rels
            for r in drop_rels:
                hit = sorted({r.subject, r.object} & (bad_labels | touched))
                why[key(r)] = (f"touches the empty class {', '.join(map(repr, hit))}; no relation was "
                               f"found that empties it by itself, so every relation touching it is "
                               f"held back")
            ents, rels = keep_ents, keep_rels
        else:
            unsat = self._unsatisfiable(self.build_batch_graph(ents, rels))

        if unsat:
            print(f"[ReasonerGate] *** {len(unsat)} class(es) are STILL empty after the "
                  f"last pass; the relations kept are not all sound: "
                  f"{sorted(unsat)[:5]} ***", flush=True)

        return GateResult(
            accepted_entities=ents,
            accepted_relations=rels,
            quarantined_entities=q_ents,
            quarantined_relations=q_rels,
            unsatisfiable=sorted(unsat_seen),
            explanation=explanation,
            without_individuals=list(self.individual_notes),
            still_empty=sorted(unsat),
            causes=list(self.cause_notes),
            why=why,
        )

    def _causes(self, ents, rels, unsat: set[str], by_label: dict) -> tuple[list, str]:
        """The relations among those on an empty class that empty it THEMSELVES.

        One reasoner run over the batch without the suspects (every relation
        on an empty class, and every relation pointing at one), plus probes:
        a fresh copy of the subject, typed as the subject is, carrying

        * one suspect relation, pointing at its REAL target: empty means the
          relation clashes with what its target is (`X has quality Y` where
          Y's own relations make it a piece of information); and, for a term
          with none of those,
        * two of its relation types at once, each to `Thing`: empty means the
          two ask for incompatible kinds (`inheres in` wants a property, `is
          about` a piece of information). That depends on the relation types
          only, never on the targets: tested against its real targets, the
          clash on `pressure ulcer stage` stayed hidden (2026-10-09), because
          its `is about` points at itself and so at a target as empty as it
          is. All of its relation types together are tried as well. Every
          group in a clash is held back -- which one the abstracts got wrong
          is a judgement, not something to guess (rule 12).

        A target that is itself empty is replaced by a stand-in that keeps
        its KIND -- its category or ontology class, and one bare relation of
        each type it has (`∃inheres in.Thing`), so the domains it implies hold
        -- but not its emptiness. Without it a loop hides its own cause
        (2026-10-09, second pass, 6,721 empty classes and none to blame): A's
        relation needs B to be a quality, B's own relation back towards A
        makes it a piece of information; both go empty, and each probe saw
        only an empty target. A probe whose target is empty even so proves
        nothing and is ignored.
        Returns (causes, how they were found), or ([], "") when none is found.
        """
        suspects = [r for r in rels if by_label.get(r.subject) in unsat]
        if not suspects:
            return [], ""
        susp = {id(r) for r in suspects}
        ent = {e.label: e for e in ents}
        preds_of: dict[str, set] = {}
        for r in rels:
            if RELATION_IRI.get(r.predicate.value):
                preds_of.setdefault(r.subject, set()).add(r.predicate.value)
        g = self.build_batch_graph(ents, [])

        def some(c, prop_name: str, filler) -> None:
            b = rdflib.BNode()
            prop = URIRef(RELATION_IRI[prop_name])
            g.add((b, RDF.type, OWL.Restriction))
            g.add((b, OWL.onProperty, prop))
            g.add((b, OWL.someValuesFrom, filler))
            g.add((c, RDFS.subClassOf, b))
            g.add((prop, RDF.type, OWL.ObjectProperty))

        def kind(c, label: str) -> None:
            e = ent[label]
            g.add((c, RDF.type, OWL.Class))
            g.add((c, RDFS.subClassOf, URIRef(e.grounded_to) if e.grounded_to
                   else URIRef(CATEGORY_IRI[e.category.value])))

        stand_ins: dict[str, URIRef] = {}

        def target(label: str) -> URIRef:
            if by_label[label] not in unsat:
                return URIRef(by_label[label])
            if label not in stand_ins:
                c = URIRef(BATCH_NS + "kind_" + _slug(label))
                kind(c, label)
                for pred in sorted(preds_of.get(label, ())):
                    some(c, pred, OWL.Thing)
                stand_ins[label] = c
            return stand_ins[label]

        for r in rels:
            if id(r) not in susp and r.object in by_label and RELATION_IRI.get(r.predicate.value):
                some(URIRef(by_label[r.subject]), r.predicate.value, target(r.object))

        def probe(name: str, subject: str, group, *, to_thing: bool = False) -> str:
            c = URIRef(BATCH_NS + name)
            kind(c, subject)
            for r in group:
                some(c, r.predicate.value, OWL.Thing if to_thing else target(r.object))
            return str(c)

        usable = [r for r in suspects
                  if r.object in by_label and RELATION_IRI.get(r.predicate.value)]
        singles = {probe(f"cause_{n}", r.subject, [r]): r for n, r in enumerate(usable)}
        by_subject: dict[str, dict] = {}
        for r in usable:
            by_subject.setdefault(r.subject, {}).setdefault(r.predicate.value, []).append(r)
        pairs, wholes = {}, {}
        for n, (subj, preds) in enumerate(sorted(by_subject.items())):
            names = sorted(preds)
            if len(names) < 2:
                continue
            for i, p1 in enumerate(names):
                for j, p2 in enumerate(names[i + 1:]):
                    group = preds[p1] + preds[p2]
                    pairs[probe(f"pair_{n}_{i}_{j}", subj, group, to_thing=True)] = ((p1, p2), group)
            if len(names) > 2:
                group = [r for q in names for r in preds[q]]
                wholes[probe(f"all_{n}", subj, group, to_thing=True)] = (tuple(names), group)
        u2 = self._unsatisfiable(g)

        def typing_holds(subject: str) -> bool:
            # A subject whose own class is empty even here makes every probe
            # on it empty; that proves nothing about its relations.
            e = ent[subject]
            return not (e.grounded_to and str(e.grounded_to) in u2)

        def proves(group) -> bool:
            return all(str(target(r.object)) not in u2 for r in group)

        single_bad = [r for c, r in singles.items()
                      if c in u2 and typing_holds(r.subject) and proves([r])]
        done = {r.subject for r in single_bad}
        pair_bad, seen = [], set()

        def hold(group) -> None:
            for r in group:
                if id(r) not in seen:
                    seen.add(id(r)); pair_bad.append(r)

        clashing: dict[str, list] = {}
        for c, (names, group) in pairs.items():
            if c in u2 and group[0].subject not in done and typing_holds(group[0].subject):
                hold(group)
                clashing.setdefault(group[0].subject, []).append(list(names))
        for c, (names, group) in wholes.items():
            subj = group[0].subject
            if c in u2 and subj not in done | set(clashing) and typing_holds(subj):
                hold(group)
                clashing.setdefault(subj, []).append(list(names))

        # What each cause is, for the curator (rule 72): which statements are
        # on each side. For a clash with the target, one more run asks which
        # of the target's own relation types make it the wrong kind.
        blame = self._target_blame(g, kind, some, single_bad, preds_of) if single_bad else {}
        self.cause_why = {}
        for r in single_bad:
            b = blame.get(id(r), [])
            self.cause_why[id(r)] = (f"clashes with what its target {r.object!r} is"
                                     + (f" (made so by the target's own {', '.join(map(str, b))})" if b else ""))
        for subj, sets in clashing.items():
            kinds = "; ".join(" and ".join(s) for s in sets)
            for r in pair_bad:
                if r.subject == subj:
                    self.cause_why[id(r)] = (f"{subj!r} is asked to be two kinds of thing at once "
                                             f"by its relations {kinds}")
        for r in single_bad:
            self.cause_notes.append({
                "kind": "target", "subject": r.subject, "predicate": r.predicate.value,
                "object": r.object,
                "target_blamed": blame.get(id(r), []),
                "target_statements": sorted((x.predicate.value, x.object) for x in rels
                                            if x.subject == r.object)})
        for subj, sets in sorted(clashing.items()):
            self.cause_notes.append({
                "kind": "two kinds", "subject": subj, "clashing": sets,
                "groups": {q: sorted(r.object for r in by_subject[subj][q])
                           for q in sorted({q for st in sets for q in st})}})
        how = []
        if single_bad:
            how.append(f"{len(single_bad)} clash with what their target is")
        if pair_bad:
            how.append(f"{len(pair_bad)} on {len({r.subject for r in pair_bad})} term(s) "
                       f"whose relations ask for two kinds of thing at once")
        return single_bad + pair_bad, "; ".join(how)

    def _target_blame(self, g, kind, some, single_bad, preds_of) -> dict:
        """{id(relation) -> the target's relation types that make it the wrong
        kind for that relation}, by one reasoner run on fresh copies: the
        subject's kind with the relation pointing at the target's kind plus
        one of its relation types. Empty list: the target's own class or
        category is what clashes."""
        probes = {}
        for n, r in enumerate(single_bad):
            for m, q in enumerate(sorted(preds_of.get(r.object, ()))):
                t = URIRef(f"{BATCH_NS}blame_t_{n}_{m}")
                kind(t, r.object)
                some(t, q, OWL.Thing)
                c = URIRef(f"{BATCH_NS}blame_{n}_{m}")
                kind(c, r.subject)
                some(c, r.predicate.value, t)
                probes[str(c)] = (r, q)
        if not probes:
            return {}
        u = self._unsatisfiable(g)
        out: dict = {}
        for c, (r, q) in probes.items():
            if c in u:
                out.setdefault(id(r), []).append(q)
        return out

    # ── subsumption edges ──────────────────────────────────────────────────
    #
    # This is where the gate earns its keep. Extracted relations are already
    # filtered by the category-pair table, but is_a edges are not: the curated
    # CSV and the FCA lattice bypass the extraction schema entirely. And the
    # table is blind to same-category disjointness — `Wound base`, `Wound edge`
    # and `Wound pocket` are all `material entity` yet pairwise disjoint, so an edge
    # making something a subclass of two of them passes every schema check and
    # only a reasoner rejects it.

    def _label_index(self) -> dict[str, URIRef]:
        g = rdflib.Graph()
        g.parse(str(self.skeleton_path), format="turtle")
        idx: dict[str, URIRef] = {}
        for subj, obj in g.subject_objects(RDFS.label):
            if isinstance(subj, URIRef):
                idx.setdefault(str(obj).strip().lower(), subj)
        return idx

    def build_edge_graph(self, edges, label_index=None) -> rdflib.Graph:
        """Skeleton plus `edges`, a sequence of (child_label, parent_label)."""
        g = rdflib.Graph()
        g.parse(str(self.skeleton_path), format="turtle")
        idx = label_index if label_index is not None else self._label_index()

        def resolve(label: str) -> URIRef:
            hit = idx.get(str(label).strip().lower())
            return hit if hit is not None else URIRef(BATCH_NS + _slug(str(label)))

        for child, parent in edges:
            c, p = resolve(child), resolve(parent)
            if c == p:
                continue
            for node, lab in ((c, child), (p, parent)):
                if str(node).startswith(BATCH_NS) and (node, RDF.type, OWL.Class) not in g:
                    g.add((node, RDF.type, OWL.Class))
                    g.add((node, RDFS.label, rdflib.Literal(str(lab))))
            g.add((c, RDFS.subClassOf, p))
        # The gate asks which CLASSES an edge makes empty. WONT's 48 named
        # individuals (Wagner grades, zones of a burn) turn one empty class into
        # an inconsistent ontology, and an inconsistent ontology names no
        # culprit at all (2026-10-03: 32,655 text edges, "inconsistent", no
        # edge attributable). Individuals are not what this gate checks.
        return without_individuals(g)[0]

    def check_edges(self, edges, sources=None) -> EdgeGateResult:
        """Reason over candidate subsumption edges; quarantine the inconsistent ones.

        `sources` maps (child, parent) -> provenance. When given, a clash is
        resolved by dropping the LOWEST-ranked edges on the offending child
        first, then re-checking; a higher-ranked edge is dropped only if the
        clash survives without any lower-ranked company.

        Without it the gate is provenance-blind, and that is not a cosmetic
        difference. WONT asserts `Necrosis subClassOf pathological disorder` and
        nothing else; two abstracts typed Necrosis as a Process; BFO makes
        continuant and occurrent disjoint, so the reasoner derives ⊥ — and the
        gate quarantined *both* edges, including the curated one. A text
        assertion had silently overridden the ground truth, which is exactly what
        the provenance ranks exist to prevent.

        An edge the caller could not stamp is treated as the lowest rank of all:
        an edge nothing claims is the first thing to give up.
        """
        why = self.available()
        if why:
            return EdgeGateResult(accepted=list(edges), skipped=why)

        from wound_ontology.hierarchies.base_hierarchy import SOURCE_RANK

        idx = self._label_index()
        kept = list(edges)
        dropped: list = []
        spared: list = []
        why: dict = {}
        unsat_seen: set[str] = set()
        explanation = ""
        src = lambda e: (sources or {}).get(tuple(e)) or "unstamped"   # noqa: E731

        def resolve(label: str) -> str:
            hit = idx.get(str(label).strip().lower())
            return str(hit) if hit is not None else BATCH_NS + _slug(str(label))

        # Rule 79 (2026-10-18): which edge gives way FIRST in a clash. An FCA
        # edge reaches the hierarchy only through the accepted slice, and only
        # when the curator's head-word rule licensed it, so here it gives way
        # after one abstract's is_a and before a checked placement. At rank 1
        # all 436 licensed edges of 2026-10-18 were dropped first whenever
        # their child was unsatisfiable through a text edge elsewhere, and the
        # cause stayed. SOURCE_RANK itself (which source owns a shared edge) is
        # unchanged.
        gate_rank = {**SOURCE_RANK, "fca": 2.5}

        def rank(edge) -> float:
            if not sources:
                return 0
            return gate_rank.get(sources.get(tuple(edge)), 0)

        for _ in range(_MAX_EDGE_PASSES):
            g = self.build_edge_graph(kept, label_index=idx)
            unsat = self._unsatisfiable(g)
            if not unsat:
                break
            unsat_seen |= unsat
            if not explanation:
                explanation = self._explain(g)
            # An edge is culpable when its CHILD is unsatisfiable: the child is
            # what the edge constrains. A parent going unsatisfiable is a
            # consequence, handled on the next pass.
            culprits = [e for e in kept if resolve(e[0]) in unsat]
            if not culprits:
                break                       # cannot attribute further
            # A class empty only because a parent it keeps is empty is not where
            # the clash is: blaming its own weakest edge refused correct typings
            # under every empty class (2026-10-29: `Aggressive surgical
            # debridement is_a process`, `Debridement method is_a information
            # entity`). The empty classes whose kept parents are all satisfiable
            # are judged first; their descendants are heard again next pass. A
            # loop of empty classes has no such class: all are judged, as before.
            under_empty = {resolve(c) for c, p in kept if resolve(p) in unsat}
            culprits = [e for e in culprits if resolve(e[0]) not in under_empty] or culprits

            # Drop the weakest evidence FIRST, and globally rather than per
            # child. Per-child was not enough: `Dry Necrosis is_a Necrosis` is
            # curated and its only edge, so on its own it looked like the weakest
            # evidence available and went — while the text edge that had made
            # Necrosis unsatisfiable in the first place was still present. Its
            # child was only unsatisfiable by inheritance. Dropping one whole
            # rank at a time and re-checking lets the cause go before its
            # consequences are judged.
            lowest = min(rank(e) for e in culprits)
            # Before a placed or curated edge goes, ask the reasoner WHY
            # (2026-10-03). The cause need not be on the empty class at all:
            # `Nutrient is_a Material Entity` (text) leaves nothing that can be
            # protein's `has role some nutrient`, so CHEBI protein and its 33
            # placed children went empty while nutrient itself stayed fine --
            # and the gate, blaming only the empty classes' own edges, dropped
            # the checked placements. An explanation names the text edge.
            if sources and lowest >= SOURCE_RANK.get("placed", 3):
                pairs = self._explained_pairs(g)
                weaker = [e for e in kept if rank(e) < lowest
                          and (resolve(e[0]), resolve(e[1])) in pairs]
                if weaker:
                    for e in weaker:
                        why[tuple(e)] = (f"the reasoner's explanation of an empty class names it; "
                                         f"a {src(e)} edge gives way before a {src(culprits[0])} one "
                                         f"(rule 79)")
                    dropped += weaker
                    bad = {tuple(e) for e in weaker}
                    kept = [e for e in kept if tuple(e) not in bad]
                    continue
            now_bad = [e for e in culprits if rank(e) == lowest]
            spared += [e for e in culprits if rank(e) != lowest]
            if not now_bad:
                break

            for e in now_bad:
                why[tuple(e)] = (f"{e[0]!r} is unsatisfiable with it; of the edges on empty classes "
                                 f"the weakest evidence ({src(e)}) gives way first (rule 79)")
            dropped += now_bad
            bad = {tuple(e) for e in now_bad}
            kept = [e for e in kept if tuple(e) not in bad]
        else:
            left = self._unsatisfiable(self.build_edge_graph(kept, label_index=idx))
            if left:
                print(f"[ReasonerGate] *** the edge gate stopped after {_MAX_EDGE_PASSES} passes with "
                      f"{len(left)} class(es) still empty: {sorted(left)[:5]} ***")

        # Anything "spared" that survived to the end really was spared; anything
        # dropped on a later pass was not.
        dropped_set = {tuple(e) for e in dropped}
        spared = [e for e in dict.fromkeys(map(tuple, spared)) if e not in dropped_set]

        return EdgeGateResult(
            accepted=kept,
            quarantined=dropped,
            unsatisfiable=sorted(unsat_seen),
            explanation=explanation,
            quarantined_sources={tuple(e): (sources or {}).get(tuple(e)) for e in dropped},
            spared=spared,
            why={e: why[e] for e in dropped_set},
        )

    # ── persistence ────────────────────────────────────────────────────────
    @staticmethod
    def write_quarantine(result: GateResult, directory: str | Path,
                         tag: str = "") -> Path | None:
        if result.clean:
            return None
        d = Path(directory)
        d.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        path = d / f"quarantine_{stamp}{('_' + tag) if tag else ''}.json"
        path.write_text(json.dumps({
            "unsatisfiable": result.unsatisfiable,
            "entities": [{"label": e.label, "category": e.category.value,
                          "grounded_to": e.grounded_to}
                         for e in result.quarantined_entities],
            "relations": [{"subject": r.subject, "predicate": r.predicate.value,
                           "object": r.object}
                          for r in result.quarantined_relations],
            "explanation": result.explanation,
            "asked_without_individuals": result.without_individuals,
            "still_empty": result.still_empty,
            "causes": result.causes,
        }, indent=2), encoding="utf-8")
        return path
