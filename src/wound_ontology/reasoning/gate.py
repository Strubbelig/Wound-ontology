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
import re
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
_MAX_PASSES = 3


@dataclass
class EdgeGateResult:
    """Subsumption edges the reasoner accepted or refused."""

    accepted: list = field(default_factory=list)
    quarantined: list = field(default_factory=list)
    unsatisfiable: list[str] = field(default_factory=list)
    explanation: str = ""
    skipped: str | None = None

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

    @property
    def clean(self) -> bool:
        return not self.quarantined_entities and not self.quarantined_relations

    def summary(self) -> str:
        if self.skipped:
            return f"reasoner gate SKIPPED ({self.skipped})"
        if self.clean:
            return (f"reasoner gate: clean "
                    f"({len(self.accepted_entities)} terms, "
                    f"{len(self.accepted_relations)} relations)")
        return (f"reasoner gate: {len(self.quarantined_entities)} term(s) and "
                f"{len(self.quarantined_relations)} relation(s) quarantined; "
                f"{len(self.accepted_entities)} terms, "
                f"{len(self.accepted_relations)} relations committed")


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
    # written here. `Process` + `ProcessBoundary` agree on `Occurrent`;
    # `MaterialEntity` + `Process` agree on nothing below `entity` and stay
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
        cats = sorted(set(categories))
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

    # ── reasoning ──────────────────────────────────────────────────────────
    def _unsatisfiable(self, graph: rdflib.Graph) -> set[str]:
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "batch.ttl"
            graph.serialize(destination=str(src), format="turtle")
            proc = subprocess.run(
                [self.robot_cmd, "reason", "--input", str(src),
                 "--reasoner", self.reasoner,
                 "--equivalent-classes-allowed", "all",
                 "--output", str(Path(td) / "out.owl")],
                capture_output=True, text=True, timeout=self.timeout,
            )
        return set(_UNSAT_RE.findall(proc.stdout + proc.stderr))

    def _explain(self, graph: rdflib.Graph, max_expl: int = 5) -> str:
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "batch.ttl"
            out = Path(td) / "expl.md"
            graph.serialize(destination=str(src), format="turtle")
            subprocess.run(
                [self.robot_cmd, "explain", "--input", str(src),
                 "--reasoner", self.reasoner, "-M", "unsatisfiability",
                 "-u", "root", "-m", str(max_expl), "--explanation", str(out)],
                capture_output=True, text=True, timeout=self.timeout,
            )
            return out.read_text(encoding="utf-8") if out.exists() else ""

    # ── the gate ───────────────────────────────────────────────────────────
    def check(self, entities, relations) -> GateResult:
        why = self.available()
        if why:
            return GateResult(accepted_entities=list(entities),
                              accepted_relations=list(relations), skipped=why)

        ents, rels = list(entities), list(relations)
        q_ents: list = []
        q_rels: list = []
        unsat_seen: set[str] = set()
        explanation = ""

        for _ in range(_MAX_PASSES):
            g = self.build_batch_graph(ents, rels)
            unsat = self._unsatisfiable(g)
            if not unsat:
                break
            unsat_seen |= unsat
            if not explanation:
                explanation = self._explain(g)

            by_label = {e.label: str(self._iri_for(e)) for e in ents}
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
            ents, rels = keep_ents, keep_rels

        return GateResult(
            accepted_entities=ents,
            accepted_relations=rels,
            quarantined_entities=q_ents,
            quarantined_relations=q_rels,
            unsatisfiable=sorted(unsat_seen),
            explanation=explanation,
        )

    # ── subsumption edges ──────────────────────────────────────────────────
    #
    # This is where the gate earns its keep. Extracted relations are already
    # filtered by the category-pair table, but is_a edges are not: the curated
    # CSV and the FCA lattice bypass the extraction schema entirely. And the
    # table is blind to same-category disjointness — `Wound base`, `Wound edge`
    # and `Wound pocket` are all MaterialEntity yet pairwise disjoint, so an edge
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
        return g

    def check_edges(self, edges) -> EdgeGateResult:
        """Reason over candidate subsumption edges; quarantine the inconsistent ones."""
        why = self.available()
        if why:
            return EdgeGateResult(accepted=list(edges), skipped=why)

        idx = self._label_index()
        kept = list(edges)
        dropped: list = []
        unsat_seen: set[str] = set()
        explanation = ""

        def resolve(label: str) -> str:
            hit = idx.get(str(label).strip().lower())
            return str(hit) if hit is not None else BATCH_NS + _slug(str(label))

        for _ in range(_MAX_PASSES):
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
            still, now_bad = [], []
            for child, parent in kept:
                (now_bad if resolve(child) in unsat else still).append((child, parent))
            if not now_bad:
                break                       # cannot attribute further
            dropped += now_bad
            kept = still

        return EdgeGateResult(
            accepted=kept,
            quarantined=dropped,
            unsatisfiable=sorted(unsat_seen),
            explanation=explanation,
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
        }, indent=2), encoding="utf-8")
        return path
