"""Term and keyword list abstractions with config-file persistence.

Hierarchy
---------
BaseList
├── TermList      — exact full-string match (case-insensitive)
│   ├── BlockList       (config/blocklist.py   METHODOLOGY_BLOCKLIST)
│   └── WhiteList       (config/whitelist.py   WHITELIST)
└── KeywordList   — substring containment match (case-insensitive)
    ├── BlockKeywordList (config/blocklist.py   KEYWORD_BLOCKLIST)
    ├── WhiteKeywordList (config/whitelist.py   KEYWORD_WHITELIST)
    └── SuspiciousList   (config/suspicious_list.py SUSPICIOUS_KEYWORDS)
"""

from __future__ import annotations

import ast
import functools
import json
import re
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Iterator

from wound_ontology.utils.string_utils import normalize_term

_CONFIG_DIR = Path(__file__).resolve().parents[3] / "config"


# ── Generic file-level persistence helpers ────────────────────────────────────

def _declares(line: str, var_name: str) -> bool:
    """True if `line` opens the set literal for exactly `var_name`.

    The match is anchored, not a substring test. It was a substring test, and
    `WHITELIST` is a substring of `KEYWORD_WHITELIST` -- which is declared FIRST
    in config/whitelist.py, so every add and remove aimed at WHITELIST landed in
    the keyword list instead. That is not a near miss: the keyword list matches
    on a word inside a term, so whitelisting `skin` there exempts `skin graft`,
    `skin substitute` and everything else containing the word.

    Same family as the `cti` keyword bug and the `class_hierarchy_*` cache glob:
    a name matched loosely against a longer name that contains it.
    """
    return bool(_re_decl(var_name).match(line)) and "{" in line


@functools.lru_cache(maxsize=None)
def _re_decl(var_name: str) -> re.Pattern[str]:
    return re.compile(rf"\s*{re.escape(var_name)}\s*(?::|=)")


def _find_block_end(lines: list[str], var_name: str) -> int:
    """Return the line index of the closing brace of var_name's set literal."""
    in_block = False
    depth    = 0
    for i, line in enumerate(lines):
        if not in_block:
            if _declares(line, var_name):
                in_block = True
                depth += line.count("{") - line.count("}")
        else:
            depth += line.count("{") - line.count("}")
            if depth <= 0:
                return i
    raise RuntimeError(f"Could not find closing brace for {var_name!r}")


def _entry_value(line: str) -> str | None:
    """The one string this line holds, or None if it does not hold exactly one.

    Parsed, not sliced. The old code did `line.strip().rstrip('",').strip('"')`,
    which is wrong twice over. On a line holding several entries it returns
    `regression", "propensity", "logistic` and matches nothing -- so a packed
    literal could be added to but never removed from. And on the one
    METHODOLOGY_BLOCKLIST entry that contains quotes,
    `"\\"long hu hui\\" pi risk management platform"`, it keeps the backslashes
    and never matches the value the module actually holds.

    `ast.literal_eval` gets both right, and returns None for a packed line,
    which is the correct answer: that line does not hold exactly one entry.
    """
    text = line.strip()
    if not text.startswith(("'", '"')):
        return None
    try:
        value = ast.literal_eval(text.rstrip(",").strip())
    except (ValueError, SyntaxError):  # silent-ok: a line that is not one
        # quoted string is not an entry -- None is the answer, not a failure.
        return None
    return value if isinstance(value, str) else None


def _entry_line(term: str) -> str:
    """One entry, quoted the way the config files quote them.

    `json.dumps` rather than an f-string: `f'    "{t}",'` emits invalid Python
    the moment a term contains a double quote, and one blocklist entry does.
    `ensure_ascii=False` keeps `lésions endothéliales chroniques` readable
    instead of turning it into escapes.
    """
    return f"    {json.dumps(term, ensure_ascii=False)},"


BANNER = (
    "    # ╔══ GENERATED — do not edit by hand ════════════════════════════════════",
    "    # ║ Every entry below is a view of a `gate` verdict on a term's record in",
    "    # ║ data/cache/term_mapping_*.json (rule 40). Editing here is editing a",
    "    # ║ printout: the next export overwrites it and the decision is lost, with",
    "    # ║ nothing to say it ever existed. Change the record, then re-export with",
    "    # ║ Orchestrator.export_gate_lists(). Section headers come from each",
    "    # ║ entry's `gate.rule.section`, so `recluster` still regroups them.",
    "    # ╚══════════════════════════════════════════════════════════════════════",
)


def write_generated_list(path: Path, var_name: str,
                         sections: list[tuple[str, list[str]]]) -> int:
    """Rewrite `var_name`'s literal in `path` from `sections`, and check it.

    `sections` is `[(header label, [terms])]`, emitted in the order given with
    the terms sorted inside each. The whole literal body is replaced, so this is
    the one writer: a hand edit between exports is a decision with no record and
    the banner says so.

    Verified by re-parsing the file we just wrote and comparing the set, because
    a generated view that silently generates the wrong thing is worse than one
    that refuses (rule 30).
    """
    lines = path.read_text().splitlines()
    try:
        start = next(i for i, l in enumerate(lines) if _declares(l, var_name))
    except StopIteration:
        raise RuntimeError(f"{path.name} does not declare {var_name!r}")
    end = _find_block_end(lines, var_name)

    body: list[str] = list(BANNER)
    wanted: set[str] = set()
    for label, terms in sections:
        if label:
            body.append(f"    # {label.lstrip('# ').rstrip()}"
                        if not label.lstrip().startswith("#") else f"    {label.strip()}")
        for t in sorted(terms, key=str.lower):
            body.append(_entry_line(t))
            wanted.add(t)
    path.write_text("\n".join(lines[:start + 1] + body + lines[end:]) + "\n")

    reread = path.read_text().splitlines()
    got = {v for l in reread[reread.index(lines[start]) + 1:
                             _find_block_end(reread, var_name)]
           if (v := _entry_value(l)) is not None}
    if got != wanted:
        raise RuntimeError(
            f"{var_name}: the export did not read back — "
            f"{len(wanted - got)} missing, {len(got - wanted)} unexpected "
            f"({sorted(wanted - got)[:3]} / {sorted(got - wanted)[:3]}). File: {path}")
    return len(wanted)


GATE_LISTS = (("out", "blocklist.py", "METHODOLOGY_BLOCKLIST"),
              ("in",  "whitelist.py",  "WHITELIST"))


def export_gate_lists(gate, config_dir: Path | None = None,
                      *, quiet: bool = False) -> dict[str, int]:
    """Rewrite the two exact curation lists from `gate`. The lists are a VIEW.

    Grouping comes from each entry's `gate.rule.section`, captured off the files
    before the first export, so `recluster` still regroups them and a 207-section
    blocklist does not come back as one undifferentiated block. Entries with no
    section -- anything a pass or the curator added since -- collect under one
    header naming the source that decided them.
    """
    config_dir = config_dir or _CONFIG_DIR
    written: dict[str, int] = {}
    for verdict, filename, var in GATE_LISTS:
        by_section: dict[str, list[str]] = {}
        for term, source in gate.gated(verdict).items():
            rule = gate.peek_gate(term).get("rule") or {}
            label = rule.get("section") or f"# ── decided by {source}, no section ──"
            by_section.setdefault(label, []).append(term)
        ordered = sorted(by_section.items(),
                         key=lambda kv: (kv[0].startswith("# ── decided by"), kv[0]))
        written[var] = write_generated_list(config_dir / filename, var, ordered)
    if not quiet:
        print("[gate] exported " + ", ".join(f"{v:,} to {k}" for k, v in written.items()))
    return written


def _pylist_add(path: Path, var_name: str, current: frozenset[str],
                new_terms: set[str]) -> int:
    """Append truly-new terms into a Python set/frozenset literal."""
    truly_new = sorted(t.lower() for t in new_terms if t.lower() not in current)
    if not truly_new:
        return 0
    lines      = path.read_text().splitlines()
    insert_at  = _find_block_end(lines, var_name)
    stub       = ["    # ── added interactively ─────────────────────────────────────────────"]
    stub      += [_entry_line(t) for t in truly_new]
    lines      = lines[:insert_at] + stub + lines[insert_at:]
    path.write_text("\n".join(lines) + "\n")
    return len(truly_new)


def _pylist_remove(path: Path, var_name: str, terms: set[str]) -> int:
    """Remove terms from a Python set/frozenset literal."""
    to_remove  = {t.strip().lower() for t in terms}
    lines      = path.read_text().splitlines()
    in_block   = False
    depth      = 0
    filtered:  list[str] = []
    removed    = 0
    for line in lines:
        if not in_block:
            if _declares(line, var_name):
                in_block = True
                depth += line.count("{") - line.count("}")
            filtered.append(line)
            continue
        depth += line.count("{") - line.count("}")
        if depth <= 0:
            in_block = False
            filtered.append(line)
            continue
        val = _entry_value(line)
        if val is not None and val in to_remove:
            removed += 1
            continue
        filtered.append(line)
    path.write_text("\n".join(filtered) + "\n")
    return removed


def _pylist_dedupe(path: Path, var_name: str) -> list[str]:
    """Drop repeat entry lines from a set literal. Returns the values dropped.

    A set literal collapses repeats on load, so a duplicated line costs nothing
    at runtime and is invisible to `len(list)` -- WHITELIST carried 2683 lines
    for 2679 distinct values and nothing ever said so. It is not harmless in the
    file: `remove` deletes every matching line, so one term costs two removals
    and a count-based check disagrees with a membership-based one. It also makes
    the file lie to anyone reading it.

    The FIRST occurrence is kept, so a term stays under the comment heading it
    was first filed under.
    """
    lines = path.read_text().splitlines()
    out: list[str] = []
    seen: set[str] = set()
    dropped: list[str] = []
    in_block = False
    depth = 0
    for line in lines:
        if not in_block:
            if _declares(line, var_name):
                in_block = True
                depth += line.count("{") - line.count("}")
            out.append(line)
            continue
        depth += line.count("{") - line.count("}")
        if depth <= 0:
            in_block = False
            out.append(line)
            continue
        val = _entry_value(line)
        if val is not None:
            if val in seen:
                dropped.append(val)
                continue
            seen.add(val)
        out.append(line)
    if dropped:
        path.write_text("\n".join(out) + "\n")
    return dropped


# ── Abstract bases ────────────────────────────────────────────────────────────

class BaseList(ABC):
    """Persistent list base: load from config file, save back, add/remove terms.

    `add` and `remove` live here rather than in the five subclasses, which held
    byte-identical copies of them. Duplication is what lets one copy drift, and
    it is also what would have made the verification below five things to keep
    in step instead of one.
    """

    #: Set by every concrete subclass: the config file, and the name of the set
    #: literal inside it that this list persists to.
    _PATH: Path
    _VAR_NAME: str

    def __init__(self) -> None:
        self._terms: frozenset[str] = frozenset()

    # ── Subclass contract ─────────────────────────────────────────────────────

    @abstractmethod
    def load(self) -> None:
        """(Re-)load terms from the config file into _terms."""

    @abstractmethod
    def match(self, term: str) -> bool:
        """Return True if term is matched by this list."""

    # ── Persistence, verified ─────────────────────────────────────────────────

    def add(self, terms: set[str]) -> int:
        """Write truly-new terms to the config file. Returns count added.

        The count is what the writer believes it wrote. The check afterwards is
        what the file actually holds.
        """
        self.load()
        n = _pylist_add(self._PATH, self._VAR_NAME, self._terms, terms)
        self.load()
        missing = sorted(t.strip().lower() for t in terms
                         if t.strip().lower() not in self._terms)
        if missing:
            raise RuntimeError(self._write_failed("add", missing))
        self.dedupe()
        return n

    def remove(self, terms: set[str]) -> int:
        """Remove terms from the config file. Returns the count of lines removed.

        Lines, not terms: a value written on two lines -- `wound` and `burn`
        both were, in KEYWORD_WHITELIST -- costs two line removals for one term.
        Which is why the check below is set membership and not a count.
        """
        self.load()
        wanted = {t.strip().lower() for t in terms} & set(self._terms)
        n = _pylist_remove(self._PATH, self._VAR_NAME, terms)
        self.load()
        left = sorted(t for t in wanted if t in self._terms)
        if left:
            raise RuntimeError(self._write_failed("remove", left))
        self.dedupe()
        return n

    def dedupe(self) -> list[str]:
        """Drop repeat entry lines from this list's literal, keeping the first.

        Called after every add and remove, so the config files self-heal as the
        pipeline touches them rather than needing a maintenance pass someone has
        to remember. Membership cannot change -- the literal is a set, so a
        repeat was already collapsed on load -- which is what makes it safe to
        run unattended.
        """
        dropped = _pylist_dedupe(self._PATH, self._VAR_NAME)
        if dropped:
            before = set(self._terms)
            self.load()
            if set(self._terms) != before:
                raise RuntimeError(
                    f"{self._VAR_NAME}: dedupe changed membership, which it must "
                    f"never do. Lost {sorted(before - set(self._terms))[:5]}")
            print(f"[{self._VAR_NAME}] removed {len(dropped)} duplicate line(s): "
                  f"{sorted(set(dropped))[:6]}")
        return dropped

    def _write_failed(self, verb: str, terms: list[str]) -> str:
        """The message that used to be a silent return of 0.

        KEYWORD_BLOCKLIST and SUSPICIOUS_KEYWORDS were written several entries
        to a line, and `_pylist_remove` only deletes a line holding exactly one
        quoted value -- so removing from either removed nothing, returned 0 and
        said nothing, while adding to them worked. Both are one entry per line
        now, and this is what says so if any list drifts back.
        """
        shown = terms[:10]
        return (
            f"{self._VAR_NAME}: {verb} did not take effect for "
            f"{len(terms)} term(s): {shown}" + (" ..." if len(terms) > 10 else "")
            + f". File: {self._PATH}. The usual cause is a set literal written "
              "with several entries on one line; the parser handles one entry "
              "per line. Before this check, the write simply did not happen "
              "and nothing said so."
        )

    # ── Shared interface ──────────────────────────────────────────────────────

    def reload(self) -> None:
        self.load()

    def __contains__(self, term: object) -> bool:
        return isinstance(term, str) and self.match(term)

    def __len__(self) -> int:
        return len(self._terms)

    def __iter__(self) -> Iterator[str]:
        return iter(sorted(self._terms))


class TermList(BaseList):
    """Full-string match against a stored set of terms, normalised both sides.

    Subclasses must define:
      _DECL_SUFFIX  — the declaration suffix after the variable name,
                      e.g. ": set[str] = {" or ": frozenset[str] = frozenset({"
      _DECL_CLOSE   — the closing token, e.g. "}" or "})"
    """

    _DECL_SUFFIX: str
    _DECL_CLOSE: str

    @property
    def _normalized(self) -> frozenset[str]:
        """`_terms` under `normalize_term`, rebuilt whenever `_terms` is replaced."""
        if getattr(self, "_norm_src", None) is not self._terms:
            self._norm = frozenset(normalize_term(t) for t in self._terms)
            self._norm_src = self._terms
        return self._norm

    def match(self, term: str) -> bool:
        """Lowercase first, then `normalize_term` on both sides.

        Rule 13 says a name is normalised in exactly one way, and this was the
        one place that did not. The store writes terms through `normalize_term`,
        which turns a hyphen into a space, so a hyphenated list entry could never
        match a store term at all: `cell-based and adipose-derived therapies` sat
        on METHODOLOGY_BLOCKLIST while the store held `Cell Based And Adipose
        Derived Therapies`, and the block was a silent no-op.

        Measured over the 3559 store terms and 550 curated labels: 9 more terms
        block, none is freed, and no curated class label is affected. Seven are
        study methodology the list already meant to catch. The other two were
        blocklist entries that were simply wrong -- `transforming growth
        factor-beta` and `stromal cell-derived factor-1alpha` are signalling
        molecules central to wound healing -- and they are whitelisted rather
        than being activated by a matcher fix.
        """
        lower = term.strip().lower()
        base  = re.sub(r"\s*\([^)]*\)\s*$", "", lower).strip()
        if lower in self._terms or base in self._terms:
            return True
        return (normalize_term(lower) in self._normalized
                or normalize_term(base) in self._normalized)

    @staticmethod
    def _label_cluster(center, terms: list[str], embs, top_n: int = 3) -> str:
        """Return the top_n terms closest to the cluster centroid (dot product)."""
        import numpy as np
        sims = embs @ center
        idx  = np.argsort(sims)[::-1][:top_n]
        return " · ".join(terms[i] for i in idx)

    def recluster_sapbert(
        self,
        embedder,
        n_clusters: int = 40,
        dry_run: bool = False,
    ) -> None:
        """Rewrite this list's config variable using SapBERT K-means cluster labels."""
        import numpy as np
        from sklearn.cluster import MiniBatchKMeans

        self.load()
        terms = sorted(self._terms)
        if not terms:
            print(f"{self._VAR_NAME} is empty — nothing to cluster.")
            return

        print(f"Embedding {len(terms)} terms...")
        embs   = embedder.embed(terms)

        print(f"Running K-means with k={n_clusters} clusters...")
        km     = MiniBatchKMeans(n_clusters=n_clusters, random_state=42,
                                 n_init=5, batch_size=2048)
        labels = km.fit_predict(embs)

        clusters: dict[int, list[str]] = {i: [] for i in range(n_clusters)}
        for term, label in zip(terms, labels):
            clusters[label].append(term)

        cluster_labels: dict[int, str] = {}
        for cid in range(n_clusters):
            member_idx   = [i for i, l in enumerate(labels) if l == cid]
            subset_embs  = embs[member_idx]
            subset_terms = [terms[i] for i in member_idx]
            cluster_labels[cid] = self._label_cluster(
                km.cluster_centers_[cid], subset_terms, subset_embs
            )

        order = sorted(range(n_clusters), key=lambda c: -len(clusters[c]))

        print(f"\n=== SAPBERT CLUSTER SUMMARY ({self._VAR_NAME}) ===\n")
        for cid in order:
            print(f"  [{len(clusters[cid]):4d}]  {cluster_labels[cid]}")
        print(f"\n  TOTAL: {len(terms)} terms in {n_clusters} clusters\n")

        if dry_run:
            print("[dry-run] No file written.")
            return

        src   = self._PATH.read_text()
        lines = src.splitlines()
        start = next(i for i, l in enumerate(lines)
                     if _declares(l, self._VAR_NAME))
        end   = _find_block_end(lines, self._VAR_NAME)

        new_lines = [f"{self._VAR_NAME}{self._DECL_SUFFIX}"]
        for cid in order:
            members = sorted(clusters[cid])
            if not members:
                continue
            header = cluster_labels[cid]
            pad    = "─" * max(1, 72 - len(header))
            new_lines.append(f"    # ── {header} {pad}────")
            for t in members:
                escaped = t.replace("\\", "\\\\").replace('"', '\\"')
                new_lines.append(f'    "{escaped}",')
        new_lines.append(self._DECL_CLOSE)

        lines = lines[:start] + new_lines + lines[end + 1:]
        self._PATH.write_text("\n".join(lines) + "\n")
        print(f"[done] Rewrote {self._VAR_NAME} in {self._PATH.name}")


class KeywordList(BaseList):
    """Substring containment match against a stored set of lowercase keywords."""

    def match(self, term: str) -> bool:
        """True if any keyword occurs at a word start in `term`.

        Plain substring matching let a three-character entry whitelist a third of
        the vocabulary: `cti` matched "pra*cti*ces", "mortality predi*cti*on",
        "Antibacterial fun*cti*onality" and 284 other store terms, all of them
        exempted from the blocklist by coincidence. Measured on the live store,
        1191 of 3725 terms were keyword-whitelisted; 288 of those only through a
        mid-word hit.

        Requiring a word boundary at the START keeps what the lists are for --
        `burn` still matches "burn wound" and "burns", `wound` still matches
        "wound bed" -- while a keyword can no longer fire from inside another
        word. Twenty other entries of four characters or fewer carried the same
        hazard: `male` matched "fe*male*", `race` matched "t*race*ability".
        """
        lower = term.strip().lower()
        return any(_starts_a_word(kw, lower) for kw in self._terms)


# ── Concrete list classes ─────────────────────────────────────────────────────

class BlockList(TermList):
    """METHODOLOGY_BLOCKLIST from config/blocklist.py.

    Also owns the cluster-assignment rules used by cluster_blocklist.py.
    """

    _DECL_SUFFIX = ": set[str] = {"
    _DECL_CLOSE  = "}"

    # Cluster rules — ORDER MATTERS: first match wins.
    CLUSTER_RULES: list[tuple[str, list[str]]] = [
        ("Study design & trial types", [
            "randomized", "randomised", "controlled trial", "clinical trial", "rct",
            "cohort study", "cohort", "prospective study", "retrospective study",
            "observational study", "cross-sectional study", "cross-sectional",
            "case-control", "case control", "case series", "case report",
            "pilot study", "qualitative study", "longitudinal study",
            "umbrella review", "scoping review", "systematic review",
            "literature review", "meta-analysis", "network meta-analysis",
            "comparative study", "cadaveric study", "human study",
            "first-in-human", "single-arm", "multicenter", "multicentre",
            "multi-arm", "cluster randomized", "matched observational",
            "within-subject", "population-based study",
        ]),
        ("Bibliometric databases & reporting standards", [
            "pubmed", "medline", "scopus", "cochrane", "embase",
            "web of science", "prospero", "prisma", "strobe", "grade",
            "preferred reporting items",
        ]),
        ("Statistical & analytical methods", [
            "logistic regression", "linear regression", "cox regression",
            "cox proportional", "propensity score", "propensity",
            "regression analysis", "regression model", "regression",
            "odds ratio", "hazard ratio", "relative risk",
            "confidence interval", "forest plot", "funnel plot",
            "roc curve", "roc analysis", "receiver operating characteristic",
            "auc", "area under the curve", "area under the receiver",
            "sensitivity analysis", "subgroup analysis", "heterogeneity",
            "risk of bias", "calibration", "concordance index",
            "multivariate analysis", "univariate analysis",
            "lasso regression", "joinpoint regression", "spearman correlation",
            "correlation analysis", "descriptive statistics", "descriptive analysis",
            "chi-square", "chi-squared", "statistical analysis",
            "thematic analysis", "bibliometric analysis", "comparative analysis",
            "retrospective analysis", "retrospective cohort analysis",
            "retrospective review", "retrospective",
            "intention-to-treat", "per-protocol", "per protocol",
            "mixed-effects", "generalized linear", "competing risk",
            "binary-classification", "discriminative model",
            "decision curve", "diagnostic odds ratio", "diagnostic network",
            "nomogram", "nomogram model", "bayesian", "bayesian network",
            "bootstrap", "youden index", "dice score",
            "mathematical model", "biomechanical model",
            "transcriptomic analysis", "rna-sequencing analysis",
            "rna sequencing analysis", "pcr analysis", "in-silico pcr",
            "immunohistochemical", "immunohistochemistry",
            "histological", "microscopic analysis",
            "gene expression", "cytokine gene", "dna sequencing",
        ]),
        ("Machine learning & AI", [
            "machine learning", "deep learning", "neural network",
            "random forest", "support vector", "u-net",
            "artificial intelligence", "ai model", "ai-based", "ai-driven",
            "ai-assisted", "ai-supported", "ai pressure",
            "predictive model", "risk prediction model", "prognostic model",
            "decision-tree", "ensemble learning", "shap method",
            "automated analysis", "automated documentation",
            "shape analysis", "image analysis", "imagej",
            "automated", "autonomous",
        ]),
        ("Education, nursing & workforce", [
            "nurse", "nursing", "caregiver", "carer", "care worker",
            "education", "training", "curriculum", "graduate",
            "knowledge score", "knowledge gap", "knowledge,",
            "attitude score", "attitude towards", "attitude scale",
            "attitude", "practice guidelines", "clinical practice",
            "guideline adherence", "guideline implementation",
            "guidelines", "guideline", "clinical guideline",
            "educational", "provider training", "burn nurse",
            "community nurse", "registered nurse", "woc nurse",
            "community nursing", "burn nursing", "healthcare professional",
            "healthcare worker", "clinician", "physician", "doctor",
            "clinical staff", "healthcare provider",
            "continuing education", "competency assessment",
        ]),
        ("Health economics & cost", [
            "cost-effectiveness", "cost-utility", "cost analysis",
            "cost modelling", "cost savings", "healthcare cost",
            "health care cost", "hospitalization cost",
            "in-hospital cost", "drug costs", "economic evaluation",
            "health economic", "incremental cost", "cost",
        ]),
        ("Study participants & demographics", [
            "control group", "intervention group", "study group",
            "comparison group", "treatment group", "placebo group",
            "experimental group", "observation group", "reference group",
            "retrospective control", "historical control", "healthy control",
            "normal saline control", "empty control", "vehicle control",
            "behavioral management control",
            "silver sulfadiazine and gauze dressings (control",
            "per protocol (pp) population", "at-risk patient",
            "high-risk patient", "high-risk group", "low risk patient",
            "elderly patient", "elderly diabetic", "elderly icu",
            "elderly burn", "frail older", "disabled older",
            "geriatric", "older adult", "older age",
            "healthy individual", "healthy volunteer",
            "pediatric", "adult patient",
            "medicare patient", "included patients",
            "patient population", "population",
            "participant", "subject",
            "clinician participant", "group of clinicians",
            "group 1", "group 2", "group 3", "group 4",
            "group a", "group b", "group s",
            "cannabis-negative", "cannabis-positive",
            "chronic sci patient", "elderly",
        ]),
        ("Animal models & basic science", [
            "rat model", "mouse model", "murine model", "animal model",
            "murine", "humanized mouse", "diabetic mouse",
            "dss-induced murine", "dextran sulfate sodium",
            "in vitro", "in vivo", "ex vivo",
            "scratch assay", "wound healing assay", "transwell assay",
            "in vivo assay", "in vivo wound", "in vivo mice", "in vivo testing",
            "in vivo studies",
            "pcr", "qrt-pcr", "qpcr", "rt-pcr",
            "16s rrna", "rna sequencing", "rna-seq",
            "macrophage polarization", "macrophage reactivity",
            "macrophage heterogeneity", "m2 macrophage",
            "classically activated macrophage", "alternatively activated macrophage",
            "imbalance of m1",
            "fibroblast", "keratinocyte",
            "oxidative stress", "reactive oxygen species",
            "exosome", "exosomes", "hpmsc-exosomes", "exosome-rich",
            "cytokine", "pro-inflammatory cytokine", "anti-inflammatory cytokine",
            "chemokine", "bioactive cytokine",
            "cd31", "alpha-sma", "alpha smooth muscle actin",
            "cell migration", "cell line", "epithelial cells",
            "progenitor exhaustion", "snai1",
            "free radical", "antioxidant activity",
            "gene expression profile", "dna sequencing",
            "hs fibroblasts", "human dermal fibroblast",
            "human epidermal keratinocyte", "human skin fibroblast",
            "hypertrophic scar fibroblast",
            "intracellular",
            "patient-derived xenograft",
        ]),
        ("Generic assessment instruments & scales", [
            "scale score", "scoring scale", "assessment scale",
            "risk scale", "questionnaire", "survey",
            "instrument", "assessment tool", "risk assessment tool",
            "content validity index", "construct validity", "convergent validity",
            "content validity", "inter-observer reliability",
            "quality criteria for psychometric",
            "berg balance scale", "constant score", "constant-murley score",
            "hip outcome score", "harris hip score",
            "hospital for special surgery knee score",
            "international knee documentation committee",
            "knee injury and osteoarthritis outcome score",
            "foot and ankle outcome score",
            "aofas ankle-hindfoot score", "lysholm",
            "mayo elbow performance score",
            "patient-rated wrist evaluation",
            "quick disability of the arm",
            "disabilities of the arm",
            "asia motor score", "craig handicap",
            "physiotherapy evidence database",
            "satisfaction with life scale",
            "skin tear knowledge assessment",
            "tegner activity score", "youden index",
            "chronic illness resource utilization survey",
            "minimal clinically important difference",
            "resource utilisation group",
            "spa efficiency score",
            "scale-level content validity",
            "item-level content validity",
            "i-cvi",
            "simplified modified rankin score",
            "toronto equation",
            "tip-apex distance",
            "meniscal extrusion index",
        ]),
        ("Generic admin, protocol & strategy terms", [
            "protocol", "strategy", "approach", "management strategy",
            "management", "care bundle", "standard of care",
            "comprehensive", "collaborative", "multidisciplinary",
            "evidence-based", "targeted", "preventive strategy",
            "prevention strategy", "appropriate management",
            "effective management", "optimisation strategy",
            "surgical strategy", "clinical strategy", "intervention strategy",
            "personalized management", "combined interventional",
            "combined therapeutic", "coordinated same-day",
            "comprehensive treatment protocol", "comprehensive care",
            "comprehensive plan", "multi-level support",
            "comprehensive risk assessment",
            "standard treatment protocol",
            "study protocol", "anesthetic protocol",
            "conservative management", "conservative rehabilitation",
            "conservative approach", "conservative treatment",
            "conservative therapy", "conventional management",
            "conventional rehabilitation", "conventional technique",
            "conventional therapy",
            "damage control approach", "collaborative care model",
            "ortcc model",
        ]),
        ("Generic outcomes, endpoints & follow-up", [
            "follow-up", "follow up", "median follow-up",
            "long-term follow-up", "close follow-up", "16-month follow-up",
            "2-year follow-up",
            "outcome", "primary outcome", "secondary outcome",
            "endpoint", "trial endpoint", "trial termination",
            "result", "finding", "clinical finding", "clinical outcome",
            "improved patient outcome", "favorable prognosis",
            "good prognosis", "poor prognosis", "adverse prognosis",
            "complete recovery", "enhanced recovery",
            "cure rate", "clinical cure rate", "clinical effective rate",
            "clinical improvement", "improve outcomes", "improved",
            "complication", "general complications", "clinical complication",
            "major complication",
        ]),
        ("Demographics, noise & generic descriptors", [
            "bias", "limitation", "accuracy", "precision", "sensitivity",
            "specificity", "high sensitivity",
            "age-related", "aging population", "demographic aging",
            "assessment", "clinical assessment", "clinical evaluation",
            "clinical examination", "clinical judgment",
            "clinical follow-up", "clinical improvement",
            "incidence", "incidence density", "cumulative incidence",
            "mortality rate", "all-cause mortality", "all-cause death",
            "cvd mortality", "adult mortality rate",
            "complication rate", "cure rate",
            "side effect", "adverse prognosis",
            "embarrassment", "emotional support",
            "social support", "self-efficacy",
            "data", "dataset", "medical record", "electronic medical record",
            "electronic health record", "electronic patient record",
            "hospital episode statistics", "national electronic injury",
            "french administrative healthcare database",
            "mimic-iv database", "database",
            "article", "publication bias", "bibliometric",
            "consensus", "guidance document",
            "study protocol noncompliance", "protocol deviation",
            "survey data",
        ]),
    ]

    _PATH     = _CONFIG_DIR / "blocklist.py"
    _VAR_NAME = "METHODOLOGY_BLOCKLIST"

    def load(self) -> None:
        import importlib, config.blocklist as _m
        importlib.reload(_m)
        self._terms = frozenset(_m.METHODOLOGY_BLOCKLIST)

    # ── Clustering ────────────────────────────────────────────────────────────

    @classmethod
    def assign_cluster(cls, term: str) -> str:
        lower = term.lower()
        for label, keywords in cls.CLUSTER_RULES:
            # Word-start, not plain containment. `rct` is a cluster keyword and
            # occurs inside "infa*rct*ion", so "myocardial infarction" was filed
            # under "Study design & trial types". Labelling only -- but it is
            # the same loose match as rule 27, in a third place.
            if any(_starts_a_word(kw, lower) for kw in keywords):
                return label
        return "Uncategorized"

    def cluster(self) -> dict[str, list[str]]:
        result: dict[str, list[str]] = {label: [] for label, _ in self.CLUSTER_RULES}
        result["Uncategorized"] = []
        for term in sorted(self._terms):
            result[self.assign_cluster(term)].append(term)
        return result

    def cluster_report(self) -> None:
        clusters = self.cluster()
        print("\n=== BLOCKLIST CLUSTER SUMMARY ===\n")
        total = 0
        for label, terms in clusters.items():
            print(f"  [{len(terms):4d}]  {label}")
            total += len(terms)
        print(f"\n  TOTAL: {total} terms\n")
        uncategorized = clusters.get("Uncategorized", [])
        if uncategorized:
            print(f"=== UNCATEGORIZED ({len(uncategorized)}) ===")
            for t in sorted(uncategorized):
                print(f"  {t}")

    def recluster(self, dry_run: bool = False) -> None:
        """Rewrite METHODOLOGY_BLOCKLIST in blocklist.py with cluster-headed sections."""
        self.load()
        clusters = self.cluster()
        self.cluster_report()

        if dry_run:
            print("[dry-run] No file written.")
            return

        src   = self._PATH.read_text()
        lines = src.splitlines()
        start = next(
            i for i, l in enumerate(lines)
            if _declares(l, self._VAR_NAME)
        )
        end = _find_block_end(lines, self._VAR_NAME)

        new_lines = [f"{self._VAR_NAME}: set[str] = {{"]
        for label, terms in clusters.items():
            if not terms:
                continue
            sep = "─" * max(1, 74 - len(label))
            new_lines.append(f"    # ── {label} {sep}────")
            for t in sorted(terms):
                escaped = t.replace("\\", "\\\\").replace('"', '\\"')
                new_lines.append(f'    "{escaped}",')
        new_lines.append("}")

        lines = lines[:start] + new_lines + lines[end + 1:]
        self._PATH.write_text("\n".join(lines) + "\n")
        print(f"[done] Rewrote {self._VAR_NAME} in {self._PATH.name}")



class WhiteList(TermList):
    """WHITELIST from config/whitelist.py."""

    _PATH        = _CONFIG_DIR / "whitelist.py"
    _VAR_NAME    = "WHITELIST"
    _DECL_SUFFIX = ": frozenset[str] = frozenset({"
    _DECL_CLOSE  = "})"

    def load(self) -> None:
        import importlib, config.whitelist as _m
        importlib.reload(_m)
        self._terms = frozenset(_m.WHITELIST)


def _starts_a_word(keyword: str, text: str) -> bool:
    """True if `keyword` occurs in `text` at the start of a word."""
    start = 0
    while True:
        i = text.find(keyword, start)
        if i < 0:
            return False
        if i == 0 or not (text[i - 1].isalnum() or text[i - 1] == "_"):
            return True
        start = i + 1


class BlockKeywordList(KeywordList):
    """KEYWORD_BLOCKLIST from config/blocklist.py."""

    _PATH     = _CONFIG_DIR / "blocklist.py"
    _VAR_NAME = "KEYWORD_BLOCKLIST"

    def load(self) -> None:
        import importlib, config.blocklist as _m
        importlib.reload(_m)
        self._terms = frozenset(_m.KEYWORD_BLOCKLIST)


class WhiteKeywordList(KeywordList):
    """KEYWORD_WHITELIST from config/whitelist.py."""

    _PATH     = _CONFIG_DIR / "whitelist.py"
    _VAR_NAME = "KEYWORD_WHITELIST"

    def load(self) -> None:
        import importlib, config.whitelist as _m
        importlib.reload(_m)
        self._terms = frozenset(_m.KEYWORD_WHITELIST)


class SuspiciousList(KeywordList):
    """SUSPICIOUS_KEYWORDS from config/suspicious_list.py — flags terms for review."""

    _PATH     = _CONFIG_DIR / "suspicious_list.py"
    _VAR_NAME = "SUSPICIOUS_KEYWORDS"

    def load(self) -> None:
        import importlib, config.suspicious_list as _m
        importlib.reload(_m)
        self._terms = frozenset(_m.SUSPICIOUS_KEYWORDS)
