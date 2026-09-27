"""LLM adjudication of the mappings that bind a store term to an existing class.

Anchor mappings are the irreversible ones. Mapping `Complication` onto WONT's
`Wound complication process` says the two name the same class forever after;
every downstream axiom then hangs off the ontology's IRI rather than a minted
twin. SapBERT proposes them, and SapBERT cannot be trusted with them alone.

Measured on the 53 anchor proposals of the 2026-09-05 build, the cosine numbers
have no usable threshold. Good and bad matches interleave:

    chronic wounds          -> Chronic wound            0.9785   correct
    clean wound class.grade -> clean-contaminated ...   0.9736   WRONG
    E. coli                 -> Escherichia coli         0.9708   correct
    Horizontal mattress s.  -> Vertical mattress s.     0.9604   WRONG

Raising the threshold loses the good matches before it loses the bad ones,
because the bad ones are *semantically close* — that is precisely why the
embedding likes them. What separates them is not distance but what the labels
actually differ BY:

    identical tokens (case/punctuation only) : 19 pairs,  0 wrong
    differ only by inflection (plurals)      :  9 pairs,  0 wrong
    differ by CONTENT                        : 25 pairs,  7 wrong

So SapBERT is exactly reliable on surface-form variance and exactly unreliable
once a real word changes. `label_difference` draws that line, and only the
content-differing pairs are sent to the model — with the ontology class's own
IAO_0000115 definition, since the label is what fooled the embedding in the
first place.

The model returns a verdict from a fixed enum and never an IRI (INSTRUCTIONS
rule 11: grounding is a lookup, not a generation). Only `same_class` survives as
a mapping. `narrower` and `broader` are not failures — they are candidate
subsumption edges, kept as a reported artifact rather than thrown away.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_WORD = re.compile(r"[a-z0-9]+")

#: Verdicts the model may return. Anything else is a refusal, not a guess.
VERDICTS = ("same_class", "narrower", "broader", "different")

#: The only verdict that becomes a mapping.
ACCEPTING_VERDICT = "same_class"


def _tokens(label: str) -> list[str]:
    return _WORD.findall(label.lower())


def _singular(token: str) -> str:
    """Strip a plural ending. Deliberately crude — it only has to fold the
    inflection pairs, and over-stripping would merely push a pair into the
    content bucket, where the model looks at it anyway."""
    if len(token) > 3 and token.endswith("ies"):
        return token[:-3] + "y"
    if len(token) > 3 and token.endswith(("ses", "xes", "zes", "ches", "shes")):
        return token[:-2]
    if len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def label_difference(a: str, b: str) -> str:
    """How two labels differ: 'identical' | 'inflection' | 'content'.

    'identical'  — the same words; only case, punctuation or spacing differ.
    'inflection' — the same words up to singular/plural.
    'content'    — at least one word is genuinely different.
    """
    ta, tb = sorted(_tokens(a)), sorted(_tokens(b))
    if ta == tb:
        return "identical"
    if sorted(_singular(t) for t in ta) == sorted(_singular(t) for t in tb):
        return "inflection"
    return "content"


@dataclass
class AdjudicationReport:
    """What was decided, and by what. Every pair lands in exactly one bucket."""

    accepted_without_model: dict[str, str] = field(default_factory=dict)
    accepted_by_model: dict[str, str] = field(default_factory=dict)
    refused: list[tuple[str, str, str, str]] = field(default_factory=list)
    subsumption_candidates: list[tuple[str, str, str, str]] = field(default_factory=list)

    def extend(self, other: "AdjudicationReport") -> "AdjudicationReport":
        """Fold another report in. Anchor and store-to-store pairs are adjudicated
        in separate calls because they get different evidence, but they are one
        decision set as far as the caller is concerned."""
        self.accepted_without_model.update(other.accepted_without_model)
        self.accepted_by_model.update(other.accepted_by_model)
        self.refused.extend(other.refused)
        self.subsumption_candidates.extend(other.subsumption_candidates)
        return self

    @property
    def asked(self) -> int:
        return (len(self.accepted_by_model) + len(self.refused)
                + len(self.subsumption_candidates))

    def summary(self) -> str:
        return (
            f"{len(self.accepted_without_model)} kept on surface form "
            f"(no model call); {self.asked} adjudicated -> "
            f"{len(self.accepted_by_model)} same class, "
            f"{len(self.subsumption_candidates)} subsumption candidate(s), "
            f"{len(self.refused)} refused"
        )


def triage(pairs: dict[str, str]) -> tuple[dict[str, str], dict[str, str]]:
    """Split anchor mappings into (surface-form, content-differing).

    The first group is accepted as-is; the second is what the model is asked
    about.
    """
    surface: dict[str, str] = {}
    content: dict[str, str] = {}
    for term, canonical in pairs.items():
        bucket = surface if label_difference(term, canonical) != "content" else content
        bucket[term] = canonical
    return surface, content


def pair_key(term: str, canonical: str) -> str:
    """The key a pair is remembered under, here and in `TermMappingAndGate`.

    One implementation, imported by both, because two copies of a key format is
    two chances for a verdict to be written where nothing will look for it.
    """
    from wound_ontology.mappers.term_mapping_and_gate import KEY_SEP
    return f"{term}{KEY_SEP}{canonical}"


#: Older name, kept because scripts import it.
_key = pair_key


def _loose(text: str) -> str:
    return " ".join(_tokens(text))


async def adjudicate(
    pairs: dict[str, str],
    llm,
    *,
    store_categories: dict[str, str] | None = None,
    ontology_categories: dict[str, str] | None = None,
    definitions: dict[str, str] | None = None,
    parents: dict[str, list[str]] | None = None,
    cache: dict[str, dict] | None = None,
    batch_size: int = 20,
    checkpoint=None,
    checkpoint_every: int = 10,
    label: str = "",
) -> AdjudicationReport:
    """Adjudicate anchor mappings, asking the model only where it is needed.

    Surface-form pairs are accepted without a call. Content-differing pairs are
    looked up in `cache` and, failing that, sent to the model in batches.

    The model is not optional. A pair that comes back with no verdict is retried
    once on its own, and if it is still undecided this raises: the alternative is
    a mapping that stands because nobody looked at it, which is the exact failure
    the whole step exists to prevent.

    `cache` is mutated in place with the new verdicts so the caller can persist
    them. A cached verdict was still a model verdict; it is only the second call
    that is skipped, not the judgement. Pass `cache=None` to re-ask everything,
    which is what to do after the ontology's definitions change.

    IT SAYS WHERE IT IS. This loop is sequential and network-bound, and it used
    to print nothing between its first line and its last. On 2026-09-26 a build
    sat in it for 3h40m without a word, and answering "is it still running?"
    took socket byte counters, because a healthy run and a dead one produce
    exactly the same output: none. Every chunk now reports its position, the
    verdicts so far, and the time it expects to need.

    `checkpoint()` is called every `checkpoint_every` chunks, for a caller that
    wants the verdicts on disk as they arrive. The same build banked **nothing**
    from four hours of adjudication because the only save was at the end, and
    the run never reached it.
    """
    import time
    from wound_ontology.utils.string_utils import smart_title

    report = AdjudicationReport()
    surface, content = triage(pairs)
    report.accepted_without_model.update(surface)
    if not content:
        return report

    store_cat = store_categories or {}
    onto_cat = ontology_categories or {}
    defs = definitions or {}
    parent_of = parents or {}
    cache = cache if cache is not None else {}

    def _record(term: str, canonical: str, verdict: str, reason: str) -> None:
        if verdict == ACCEPTING_VERDICT:
            report.accepted_by_model[term] = canonical
        elif verdict in ("narrower", "broader"):
            report.subsumption_candidates.append((term, canonical, verdict, reason))
        else:
            # `different`, and anything the model invented outside the enum. An
            # unrecognised verdict is not a guess to be resolved -- the mapping
            # simply does not stand, and the raw string is reported as given.
            report.refused.append((term, canonical, verdict, reason))

    pending: dict[str, str] = {}
    for term, canonical in content.items():
        hit = cache.get(_key(term, canonical))
        if hit:
            _record(term, canonical, hit["verdict"], hit.get("reason", ""))
        else:
            pending[term] = canonical

    async def _ask(chunk: dict[str, str]) -> dict[tuple[str, str], tuple[str, str]]:
        payload = [{
            "store_term": t,
            "ontology_class": c,
            "store_category": store_cat.get(smart_title(t.strip())),
            "ontology_category": onto_cat.get(c.strip()),
            "ontology_definition": defs.get(c.strip()),
            "ontology_parents": parent_of.get(c.strip()),
        } for t, c in chunk.items()]
        verdicts = await llm.adjudicate_mappings_batch(payload)
        # The model is told to echo the exact strings; when it paraphrases the
        # casing or punctuation anyway, match loosely rather than lose the answer.
        by_loose = {(_loose(t), _loose(c)): (t, c) for t, c in chunk.items()}
        out: dict[tuple[str, str], tuple[str, str]] = {}
        for v in verdicts:
            pair: tuple[str, str] | None = (v.store_term, v.ontology_class)
            if chunk.get(v.store_term) != v.ontology_class:
                pair = by_loose.get((_loose(v.store_term), _loose(v.ontology_class)))
            if pair is None:
                continue
            out[pair] = (v.verdict, v.reason)
        return out

    items = list(pending.items())
    answers: dict[tuple[str, str], tuple[str, str]] = {}
    chunks = (len(items) + batch_size - 1) // batch_size
    what = f" [{label}]" if label else ""
    if chunks:
        print(f"[Adjudicator]{what} {len(items):,} pair(s) to ask in "
              f"{chunks:,} chunk(s) of {batch_size}.")
    started = time.monotonic()
    for i, start in enumerate(range(0, len(items), batch_size), 1):
        chunk = dict(items[start:start + batch_size])
        fresh = await _ask(chunk)
        answers.update(fresh)
        # Into the cache HERE, not after the loop. A checkpoint that runs
        # while the verdicts are still in a local dict saves an empty record,
        # which is worse than not checkpointing: it looks like progress.
        for (t, c), (verdict, reason) in fresh.items():
            cache[_key(t, c)] = {"verdict": verdict, "reason": reason}
        gone = time.monotonic() - started
        left = gone / i * (chunks - i)
        print(f"[Adjudicator]{what} chunk {i:,}/{chunks:,} — "
              f"{len(answers):,} verdict(s), {gone/60:.1f} min gone, "
              f"~{left/60:.0f} min left", flush=True)
        if checkpoint is not None and i % checkpoint_every == 0:
            checkpoint()
            print(f"[Adjudicator]{what} checkpointed at chunk {i:,}.", flush=True)

    missing = {t: c for t, c in pending.items() if (t, c) not in answers}
    if missing:
        print(f"[Adjudicator] {len(missing)} pair(s) came back with no verdict — "
              f"re-asking them one batch at a time.")
        for term, canonical in missing.items():
            answers.update(await _ask({term: canonical}))

    still_missing = [(t, c) for t, c in pending.items() if (t, c) not in answers]
    if still_missing:
        listed = "\n".join(f"    {t!r} -> {c!r}" for t, c in still_missing)
        raise RuntimeError(
            f"[Adjudicator] {len(still_missing)} anchor mapping(s) were never "
            f"adjudicated — the model returned no verdict for them twice:\n{listed}\n"
            "These mappings bind a store term to an existing ontology class and "
            "must not stand unexamined. Fix the model access and re-run; do not "
            "apply this mapping."
        )

    for (term, canonical), (verdict, reason) in answers.items():
        # Already cached above for everything the chunk loop answered; the
        # re-ask pass below it is not, so this stays idempotent rather than
        # conditional.
        cache[_key(term, canonical)] = {"verdict": verdict, "reason": reason}
        _record(term, canonical, verdict, reason)

    return report
