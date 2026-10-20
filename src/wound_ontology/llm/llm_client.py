from __future__ import annotations
import asyncio

import httpx
import json
from pathlib import Path

import openai as openai_sdk
from openai import RateLimitError as _RateLimitError

_CQ_PATH = Path(__file__).resolve().parents[3] / "config" / "competency_questions.json"

def _build_cq_block() -> str:
    """Load competency_questions.json and return a compact prompt section."""
    try:
        data = json.loads(_CQ_PATH.read_text())
    except FileNotFoundError:
        print(f"[LLMClient] WARNING: no competency questions at {_CQ_PATH}. "
              "The extraction prompt will carry NO ontology scope section.")
        return ""
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"[LLMClient] {_CQ_PATH} is not valid JSON ({exc}). Refusing to build a "
            "prompt with the scope section silently missing — fix the file."
        ) from exc
    in_lines: list[str] = []
    for theme in data.get("clinical_themes", []):
        cqs = theme.get("in_scope", [])
        if cqs:
            t = cqs[0].get("example_triple", [])
            triple_str = f'({t[0]} {t[1]} {t[2]})' if len(t) == 3 else ""
            in_lines.append(f'        ✓ {cqs[0]["question"]} → {triple_str}')
    out_lines = [
        f'        ✗ {cq["question"]} [{cq.get("category", "")}]'
        for cq in data.get("global_out_of_scope", [])[:4]
    ]
    lines = ["        IN SCOPE — ontology must answer:"] + in_lines
    lines += ["        OUT OF SCOPE — extract NOTHING for these:"] + out_lines
    return "\n".join(lines)

from wound_ontology.llm.schemas import (
    ExtractResponse, NormalizationResponse, FillNanResponse,
    FillNanBatchResponse, SemanticNameResponse, ScopeCheckResponse,
    MereRelationResult, MereRelationBatchResponse,
    OccursInTargetBatch,
    TypingResponse, RelationResponse,
    MappingVerdict, MappingVerdictBatch,
)

_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

#: The transport's own ceiling on a single request, in seconds. Every call site
#: passes its own budget (240s for extraction, 360s for the batch judgements)
#: and that wins per request; this is what applies when nobody says.
_DEFAULT_TIMEOUT = 300.0
_DEFAULT_MODEL = "deepseek/deepseek-v4-flash"


class LLMClient:
    """
    Single LLM interface for the whole pipeline via OpenRouter.

    All tasks (extraction, normalization, NaN fill, FCA naming) go through
    one model — swap the model_id to change provider/quality/cost trade-off.
    Default: DeepSeek Chat (best price/performance as of 2026-04).
    """

    def __init__(self, api_key: str, model_id: str = _DEFAULT_MODEL):
        # A TRANSPORT timeout, not just an `asyncio.wait_for` around the call.
        #
        # On 2026-09-26 the term-mapping build hung for 3h40m after two
        # timeout-and-retry cycles: no open sockets, no timers, 2.5 seconds of
        # CPU in two hours, the event loop parked in kqueue forever.
        # `asyncio.wait_for` does not abort a request, it CANCELS it and then
        # awaits the cancellation finishing -- and if the HTTP client's
        # teardown never finishes, `wait_for` hangs after its own timeout has
        # already fired. Nothing above it can help, because the await that
        # never returns is inside the timeout mechanism itself.
        #
        # A transport timeout fails the request at the socket, so a stall
        # becomes an ordinary exception the retry wrapper can see. `pool` is
        # the one that matters most here: a cancelled request can leave its
        # connection slot un-returned, and without a pool timeout the next
        # call waits for a free connection forever -- which is exactly the
        # shape of the hang, since no socket was ever opened for it.
        self._client  = openai_sdk.AsyncOpenAI(
            api_key=api_key,
            base_url=_OPENROUTER_BASE_URL,
            # The SDK retries twice by default, inside our own budget, which
            # both multiplies the wall time and makes the retry log a lie
            # about how many attempts were made. Retrying is this class's job.
            max_retries=0,
            timeout=httpx.Timeout(_DEFAULT_TIMEOUT, connect=30.0, pool=60.0),
        )
        self.model_id = model_id
        # Circuit breaker — set by callers that want early abort on sustained failures.
        self.abort_event: asyncio.Event | None = None
        self._consec_errors: int = 0
        self._max_consec_errors: int = 0

    @property
    def has_credentials(self) -> bool:
        """Whether this client could reach the model at all.

        Steps that cannot degrade gracefully without the model check this up
        front and raise, rather than discovering it mid-run after an hour of
        embedding work.
        """
        return bool(getattr(self._client, "api_key", ""))

    # ── Retry wrapper ──────────────────────────────────────────────────────────

    async def _execute_with_retry(self, func, *args, **kwargs):
        max_retries = 5
        for attempt in range(max_retries):
            if self.abort_event and self.abort_event.is_set():
                raise RuntimeError("[Circuit breaker] Abort triggered")
            try:
                result = await func(*args, **kwargs)
                if attempt > 0:
                    print(f"[LLM] Recovered after {attempt} retr{'y' if attempt == 1 else 'ies'}.")
                self._consec_errors = 0
                return result
            except Exception as exc:
                # If callers requested a hard failure threshold, enforce it here.
                if self._max_consec_errors > 0:
                    self._consec_errors += 1
                    if self._consec_errors >= self._max_consec_errors:
                        if self.abort_event:
                            self.abort_event.set()
                        raise RuntimeError(
                            f"[Circuit breaker] {self._consec_errors} consecutive failures — aborting"
                        ) from exc
                if attempt < max_retries - 1:
                    if isinstance(exc, _RateLimitError):
                        wait = 60 + attempt * 30
                        print(f"[LLM] Rate limited (429). Retry {attempt + 1} in {wait}s...")
                    else:
                        wait = (attempt + 1) * 5
                        print(f"[LLM] Error ({type(exc).__name__}). Retry {attempt + 1} in {wait}s...")
                    await asyncio.sleep(wait)
                else:
                    raise exc

    # ── Core call ──────────────────────────────────────────────────────────────

    #: Output budget for the batch judgements (scope, mapping adjudication).
    #: Without one, OpenRouter reserves credit for the model's whole output
    #: window -- 131,072 tokens -- per request in flight, and on 2026-09-28 a
    #: pass of eight parallel batches ran into the account's in-flight budget
    #: with 402s long before the credit was actually spent. Measured on 25-term
    #: scope batches: 3,238 / 12,136 / 13,379 output tokens, almost all of it
    #: reasoning, so the cap leaves 2.4x the largest. A reply that hits it ends
    #: in `finish_reason == "length"` and is raised, never parsed half-written.
    BATCH_MAX_TOKENS = 32_768

    async def _call_json(self, prompt: str, schema: type, temperature=0.0, timeout=240,
                         max_tokens: int | None = None):
        """POST to OpenRouter, enforce JSON mode, parse into Pydantic schema."""
        schema_json = (
            schema.model_json_schema()
            if hasattr(schema, "model_json_schema")
            else schema.schema()
        )
        schema_hint = json.dumps(schema_json, indent=2)
        full_prompt = (
            f"{prompt}\n\n"
            f"Respond with valid JSON only — no markdown fences — "
            f"matching this schema exactly:\n{schema_hint}"
        )

        async def _inner():
            resp = await self._client.chat.completions.create(
                model=self.model_id,
                messages=[{"role": "user", "content": full_prompt}],
                response_format={"type": "json_object"},
                temperature=temperature,
                timeout=timeout,
                **({"max_tokens": max_tokens} if max_tokens else {}),
            )
            if max_tokens and resp.choices[0].finish_reason == "length":
                raise RuntimeError(f"the reply hit the {max_tokens:,}-token cap and "
                                   f"was cut off; raise BATCH_MAX_TOKENS")
            raw = resp.choices[0].message.content.strip()
            # Remove code fences if the model wrapped JSON inside them.
            raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
            if hasattr(schema, "model_validate_json"):
                return schema.model_validate_json(raw)
            return schema.parse_raw(raw)

        # The per-call budget goes to the TRANSPORT, which can enforce it
        # without cancellation. `wait_for` stays as a backstop, with slack, so
        # that it fires only if the transport somehow did not -- and if it ever
        # does fire, that is a defect worth seeing rather than a normal timeout.
        return await asyncio.wait_for(_inner(), timeout=timeout + 30)

    # ── Prompt builders ────────────────────────────────────────────────────────

    @staticmethod
    def _build_predicate_block(predicates: list[str], definitions: dict) -> str:
        lines = []
        for pred in predicates:
            defn = definitions.get(pred)
            if defn is None:
                lines.append(f"        {pred} — (no definition provided)")
                continue
            lines.append(f"        {pred} — {defn['summary']}")
            for ex in defn.get("yes", []):
                lines.append(f"          ✓ \"{ex}\"")
            for rule in defn.get("no", []):
                lines.append(f"          ✗ {rule}")
        return "\n".join(lines)

    # ── Public task interface ──────────────────────────────────────────────────

    async def extract_entities(self, text, predicates, targets, attributes, predicate_definitions=None):
        predicate_block = (
            self._build_predicate_block(predicates, predicate_definitions)
            if predicate_definitions
            else f"        Use only these predicates: {predicates}"
        )
        cq_block = _build_cq_block()
        prompt = f"""
        Analyze the following clinical text to build a formal wound ontology compliant with BFO and RO standards.
        The domain is clinical and surgical (medication, surgical treatment, physical therapy, etiology, pathophysiology, classifications).

        GOAL: Extract objects and their FORMAL ATTRIBUTES. Every attribute is a composite of a predicate and a target.

        ══ ONTOLOGY SCOPE (COMPETENCY QUESTIONS) ══
{cq_block}

        ══ PREDICATE DEFINITIONS AND RULES ══

{predicate_block}

        ══ CONSTRAINTS ══
        1. Use ONLY these predicates — never invent others: {predicates}
        2. Reuse existing targets whenever possible: {targets}. Targets are singular nouns, adjectives, or short noun phrases.
        3. Add confirmed attributes to true_attributes, denied to false_attributes.
        4. Classify existing attributes where possible: {attributes}
        5. MUTUAL EXCLUSION: If you assign is_a: X for an entity, you MUST NOT also assign part_of: X for the same target X.
        6. DOMAIN FILTER: Extract ONLY wound-care concepts — wound types, conditions, anatomy, pathogens, biological processes, treatments. NEVER extract:
           • Study designs / trial types: Study, Trial, RCT, Systematic Review, Meta-analysis, Cohort Study, Case Series, Pilot Study, Cross-sectional Study, Observational Study
           • Study components / participants: Control Group, Intervention Group, Patient, Participant, Sample Size, Population, Follow-up, Outcome Measure, Endpoint, Inclusion Criteria, Exclusion Criteria
           • Statistical methods: Regression, Propensity Score, Odds Ratio, Hazard Ratio, AUC, ROC Curve, Confidence Interval, Sensitivity Analysis, Nomogram, Forest Plot
           • Bibliometric / database terms: PubMed, Scopus, PROSPERO, PRISMA, Cochrane, Embase, STROBE, Web of Science
           • ML / AI methods: Machine Learning, Deep Learning, Neural Network, Random Forest, SVM, Algorithm, Predictive Model
           • Healthcare admin / nursing / education: Nurse Training, Healthcare Professional, Clinical Guideline, Protocol, Education, Knowledge Score, Clinical Practice, Multidisciplinary Team
           • Cost / economic terms: Cost-effectiveness, Healthcare Cost, Economic Evaluation, Cost Analysis, Incremental Cost
           • Animal / in-vitro: Mouse Model, Rat Model, In Vitro, In Vivo, PCR, RNA Sequencing, Macrophage Polarization, Fibroblast Migration, Keratinocyte Proliferation
           • Generic process / admin terms: Management Strategy, Prevention Strategy, Risk Stratification, Assessment Tool, Survey, Questionnaire, Care Bundle, Standard of Care

        ══ EXAMPLE ══
        Object: "Pressure Injury"
        true_attributes:
          - predicate: "is_a", target: "Chronic Wound"
          - predicate: "part_of", target: "Subcutaneous Tissue"
        false_attributes:
          - predicate: "occurs_in", target: "Subcutaneous Tissue"  (wrong — occurs_in needs a process subject)
          - predicate: "part_of", target: "Chronic Wound"  (wrong — use is_a for taxonomy)

        TEXT: {text}
        """
        result = await self._execute_with_retry(self._call_json, prompt, ExtractResponse, timeout=240)
        return result.entities

    # ── Two-stage, schema-constrained extraction (C2) ──────────────────────
    #
    # Stage 1 asks for ONE categorical choice per term and nothing else.
    # Stage 2 is handed the categories and a licensing table derived from
    # MILD/WONT, so the relation is looked up rather than reasoned about.
    #
    # The model never emits an IRI. Grounding is an exact-label lookup against
    # the ontologies, which removes the hallucinated-identifier failure mode
    # entirely instead of trying to detect it after the fact.

    async def type_terms(self, text, with_definitions: bool = False):
        """Stage 1 — extract terms and give each exactly one BFO/MILD category.

        Returns (entities, rejected) where rejected is a list of
        (label, category, reason) for anything that failed validation.
        """
        from wound_ontology.llm.extraction_models import BFOCategory, ExtractedEntity
        from wound_ontology.llm.extraction_prompt import typing_prompt

        prompt = typing_prompt(text, with_definitions=with_definitions)
        result = await self._execute_with_retry(
            self._call_json, prompt, TypingResponse, timeout=240
        )

        valid = {c.value for c in BFOCategory}
        entities, rejected = [], []
        for t in result.terms:
            label = (t.label or "").strip()
            cat = (t.category or "").strip()
            if not label:
                rejected.append((t.label or "", cat, "empty label"))
                continue
            if cat not in valid:
                rejected.append((label, cat, "not a BFO/MILD category"))
                continue
            try:
                entities.append(ExtractedEntity(label=label, category=cat))
            except Exception as exc:
                rejected.append((label, cat, str(exc).splitlines()[0]))
        return entities, rejected

    async def extract_relations(self, text, entities):
        """Stage 2 — relations among already-typed terms.

        `entities` is the accepted output of stage 1. Returns the candidates the
        model proposed; category licensing is enforced by ExtractionResult.
        """
        from wound_ontology.llm.extraction_prompt import relation_prompt

        if len(entities) < 2:
            return []
        typed = {e.label: e.category.value for e in entities}
        prompt = relation_prompt(text, typed)
        result = await self._execute_with_retry(
            self._call_json, prompt, RelationResponse, timeout=240
        )
        return result.relations

    async def extract_two_stage(self, text, with_definitions: bool = False):
        """Full schema-constrained extraction for one document.

        Returns (ExtractionResult, report). Everything the schema refused is in
        the report rather than silently dropped, so extraction quality is
        measurable instead of assumed.
        """
        from wound_ontology.llm.extraction_models import (
            ExtractionResult, RelationType,
        )

        entities, rejected_terms = await self.type_terms(
            text, with_definitions=with_definitions
        )
        if not entities:
            return ExtractionResult(), {
                "rejected_terms": rejected_terms,
                "rejected_relations": [],
                "unknown_predicates": [],
            }

        candidates = await self.extract_relations(text, entities)

        known = {r.value for r in RelationType}
        unknown_predicates, wire_relations = [], []
        for c in candidates:
            pred = (c.predicate or "").strip()
            if pred not in known:
                unknown_predicates.append((c.subject, pred, c.object))
                continue
            wire_relations.append(
                {"subject": c.subject.strip(),
                 "predicate": pred,
                 "object": c.object.strip()}
            )

        result = ExtractionResult(
            entities=[e.model_dump() for e in entities],
            relations=wire_relations,
        )
        report = {
            "rejected_terms": rejected_terms,
            "rejected_relations": [
                (r.subject, r.predicate.value, r.object, why)
                for r, why in result.rejected_relations
            ],
            "unknown_predicates": unknown_predicates,
        }
        return result, report

    async def create_normalization_mapping(self, terms, standards) -> dict:
        prompt = f"""
        You are provided a batch of medical terms which have to be normalized for a clinical ontology.
        Terms that refer to the same concept MUST map to the same single standard — regardless of word form.

        INPUT STANDARDS (reuse these whenever a term matches conceptually): {standards}
        TERMS TO PROCESS: {terms}

        STRICT RULES:
        1. COLLAPSE SAME-CONCEPT TERMS: If two or more terms refer to the same clinical concept, they MUST share one standard.
        2. If a term matches an INPUT STANDARD conceptually, you MUST reuse that standard exactly.
        3. Do NOT invent a new term if an existing standard covers the concept.
        4. Only create a new standard if no existing standard covers the concept.

        This prompt is designed to preserve existing canonical labels and encourage
        the model to map synonyms to the same target.
        """
        result = await self._execute_with_retry(self._call_json, prompt, NormalizationResponse, timeout=240)
        return {item.original: item.standard for item in result.mappings}

    async def fill_nan(self, object_name: str, attributes: list[str]) -> list[str]:
        if not attributes:
            return []
        prompt = f"""
        Act as a clinical ontologist. Review the Formal Object {object_name}.
        Evaluate the following list of candidate attributes (predicates and targets).

        TASK:
        Return a JSON list of ONLY the attributes that are FACTUALLY and CLINICALLY true for {object_name}.
        If an attribute is incorrect, uncertain, or not a defining characteristic, EXCLUDE it.

        CANDIDATE ATTRIBUTES:
        {attributes}

        Return the results in the original string format provided.
        """
        result = await self._execute_with_retry(self._call_json, prompt, FillNanResponse, temperature=0.0)
        return result.confirmed_attributes

    async def fill_nan_batch(
        self, entity_attrs: dict[str, list[str]]
    ) -> dict[str, dict[str, list[str]]]:
        """Adjudicate undecided (entity, attribute) cells with a THREE-way verdict.

        Returns {entity: {"confirmed": [...], "denied": [...]}}. An attribute in
        neither list is left undecided by the caller. This matters: the previous
        prompt told the model to omit attributes that were "incorrect, uncertain,
        or not defining", and the caller then wrote 0 for everything omitted —
        so genuine uncertainty was recorded as a definite "does not hold".
        """
        if not entity_attrs:
            return {}
        body = "\n\n".join(
            f'Entity: "{entity}"\nCandidate attributes: {attrs}'
            for entity, attrs in entity_attrs.items()
        )
        prompt = f"""
        Act as a clinical ontologist. For each entity below, sort the candidate attributes
        into exactly one of three groups:

          confirmed_attributes – FACTUALLY and CLINICALLY true of this entity.
          denied_attributes    – factually FALSE of this entity. Use this only when you
                                 positively know the attribute does not hold.
          (omit entirely)      – you are UNSURE, or the attribute is neither clearly true
                                 nor clearly false. Omitting is the correct answer here and
                                 carries no penalty; the cell stays undecided.

        Do NOT put an attribute in denied_attributes merely because you are uncertain
        about it, and do NOT put one in confirmed_attributes merely because it is plausible.
        Return results for every entity listed.

        {body}
        """
        result = await self._execute_with_retry(self._call_json, prompt, FillNanBatchResponse, temperature=0.0, timeout=240)
        return {
            r.object_name: {"confirmed": r.confirmed_attributes,
                            "denied": r.denied_attributes}
            for r in result.results
        }

    async def classify_scope_batch(self, candidates: list[tuple[str, int, list[str]]]) -> list[str]:
        """
        Ask the LLM which entities in ``candidates`` are out of scope for a wound ontology.

        candidates: list of (entity_name, pmid_count, sample_true_attrs)
        Returns: list of entity names flagged as inappropriate.
        """
        lines = []
        for entity, freq, attrs in candidates:
            attr_str = ", ".join(attrs) if attrs else "no attributes"
            lines.append(f'- "{entity}" (freq={freq}): {attr_str}')
        body = "\n".join(lines)

        prompt = f"""
        You are curating a clinical wound care ontology.
        Below is a list of candidate entities extracted from PubMed abstracts.
        For each entity, decide whether it is INAPPROPRIATE (out of scope) for a wound ontology.

        An entity is INAPPROPRIATE if it is:
        - A study design or methodology term (e.g. Randomized Controlled Trial, Cohort Study, Meta-analysis)
        - A generic administrative or statistical concept (e.g. Sample Size, Outcome Measure, Data)
        - A study participant grouping (e.g. Control Group, Intervention Group, Patient, Participant)
        - A generic epidemiological term with no specific wound relevance (e.g. Mortality, Age, Hospital Stay)
        - An outcome measurement instrument not specific to wounds (e.g. Visual Analog Scale, Braden Scale)

        An entity is APPROPRIATE if it is:
        - A wound type, wound complication, or wound-related condition
        - A treatment, intervention, or procedure used in wound care
        - A pathogen, biological process, or tissue relevant to wound healing
        - An anatomical structure relevant to wounds
        - A risk factor or comorbidity specifically driving wound outcomes

        CANDIDATES:
        {body}
        """
        result = await self._execute_with_retry(self._call_json, prompt, ScopeCheckResponse, temperature=0.0, timeout=360)
        return result.inappropriate

    async def gate_scope_batch(
        self, candidates: list[tuple[str, int, list[str]]]
    ) -> tuple[dict[str, tuple[str, str]], list[str]]:
        """`({term: (verdict, reason)}, [echoes we could not place])`.

        candidates: (term, pmid_count, sample_true_attrs)

        A term missing from the answer is missing from the result. That is the
        whole difference from `classify_scope_batch`, which returns only the
        out-of-scope names and so cannot tell an in-scope judgement from an
        omission -- the caller then treated every omission as "in scope" and
        wrote it to the whitelist for good.

        The model's echo of a term is matched exactly, then case-insensitively,
        then through `normalize_term`, because a model asked about
        `Kaplan-Meier analysis` may answer about `Kaplan Meier analysis` and an
        exact-only match turns a judgement into a silent omission -- the same
        failure one layer along. It is also matched after pulling the first
        quoted span out of the echo: on 2026-09-25, 1,126 of 3,848 answers came
        back as the whole input LINE, `"high-risk cohort" (in 2 abstracts):
        is_a: material entity`, and the term is the quoted part of it.

        Whatever still does not place is RETURNED, not dropped: an echo naming
        nothing we asked about means the answer is about something else, and the
        caller says so instead of quietly losing it.
        """
        import re as _re
        from wound_ontology.utils.string_utils import normalize_term
        from wound_ontology.llm.schemas import GateBatchResponse

        lines = []
        for term, freq, attrs in candidates:
            attr_str = ", ".join(attrs) if attrs else "no attributes"
            lines.append(f'- "{term}" (in {freq} abstracts): {attr_str}')
        body = "\n".join(lines)

        prompt = f"""
        You are curating a clinical wound-care ontology. For EVERY term below,
        say whether the ontology should carry it as a class.

        OUT of scope:
        - study design or methodology (randomized controlled trial, cohort study,
          meta-analysis, propensity matching, Kaplan-Meier analysis)
        - statistics and reporting (sample size, confidence interval, odds ratio,
          p-value, PRISMA, registration numbers)
        - study participant groupings (control group, intervention arm,
          participants, patients)
        - generic administrative or bibliometric vocabulary (research, findings,
          data, Cochrane Library, tertiary care hospital)
        - a measurement instrument with no wound content (Likert scale)

        IN scope:
        - a wound, wound complication, or wound-related condition
        - a treatment, intervention, dressing, device, or drug used in wound care
        - a pathogen, biological process, tissue, cell type, or molecule that
          takes part in wound healing
        - an anatomical structure wounds occur in
        - a risk factor or comorbidity that drives wound outcomes
        - a clinical sign, symptom or quality of a wound -- INCLUDING pain,
          exudate, odour and their severities

        Two judgements that are easy to get wrong, so read them twice:
        - a MOLECULE or PROCESS named in a wound study (IL-6, TNF-alpha,
          collagen synthesis, angiogenesis, re-epithelialization) is IN scope;
          it is the biology, not the method.
        - a NAMED THERAPY OR AGENT (silver sulfadiazine, photobiomodulation,
          negative pressure wound therapy, VAC therapy) is IN scope even when the
          abstract is a trial of it.

        Answer with one entry per term, in the same order, each with a short
        reason. Do not omit any term.

        TERMS:
        {body}
        """
        result = await self._execute_with_retry(
            self._call_json, prompt, GateBatchResponse, temperature=0.0, timeout=360,
            max_tokens=self.BATCH_MAX_TOKENS)
        exact = {t: t for t, _, _ in candidates}
        folded = {t.strip().lower(): t for t, _, _ in candidates}
        normed = {normalize_term(t): t for t, _, _ in candidates}
        out: dict[str, tuple[str, str]] = {}
        unmatched: list[str] = []
        for v in result.verdicts:
            verdict = (v.verdict or "").strip().lower()
            if verdict not in ("in", "out"):
                unmatched.append(f"{v.term} (verdict {v.verdict!r})")
                continue
            def _place(echo: str) -> str | None:
                return (exact.get(echo)
                        or folded.get(echo.strip().lower())
                        or normed.get(normalize_term(echo)))

            term = _place(v.term)
            if term is None and (q := _re.search(r'"([^"]+)"', v.term)):
                term = _place(q.group(1))
            if term is None:
                unmatched.append(v.term)
                continue
            out[term] = (verdict, v.reason)
        return out, unmatched

    async def validate_mere_batch(
        self, triples: list[tuple[str, str]]
    ) -> list[MereRelationResult]:
        """
        Classify (child, part_of, parent) triples for a wound ontology.

        Returns list of MereRelationResult with verdict:
          keep  – valid anatomical/physical part_of
          is_a  – child is a subtype of parent, not a part
          drop  – relation is wrong in both directions
        """
        lines = [f'- ("{c}", part_of, "{p}")' for c, p in triples]
        prompt = f"""
        You are a biomedical ontologist curating a wound care ontology (BFO/RO).

        BFO rule: part_of connects CONTINUANTS (material entities, anatomical structures).
        A PROCESS or PROCEDURE cannot be part_of a material entity.

        Classify each triple with one of three verdicts:
          keep  – the child is physically/anatomically a PART of the parent
                  (e.g. "Wound Bed part_of Wound", "Dermis part_of Skin")
          is_a  – the child is a SUBTYPE/KIND of the parent, not a part
                  (e.g. "Pressure Injury is_a Wound", "Alveolar Bone Plate Avulsion is_a Alveolar Bone Injury")
          drop  – the relation is wrong in both directions; remove it
                  (e.g. "Alginate Hydrogel part_of Wound Management" — a dressing is not a part of a management concept)

        TRIPLES:
        {chr(10).join(lines)}

        Return JSON with "results": list of {{child, parent, verdict}}.
        Use the EXACT child and parent strings from the input — do not paraphrase.
        """
        result = await self._execute_with_retry(
            self._call_json, prompt, MereRelationBatchResponse,
            temperature=0.0, timeout=360,
        )
        return result.results

    async def generate_semantic_name(self, intent_attributes, superclass_names,
                                     extent_categories=(), parent_names=(),
                                     differentia=(), extent_sample=()) -> str:
        """Name a formal concept. Returns the name.

        `extent_categories` is shown so the name is of the right kind, but it is
        not asked back: what the group is comes from the concept's intent, and a
        category the model declares about its own new label is a claim, not a
        lookup. The caller checks the name against the ontologies instead.
        """
        from wound_ontology.llm.extraction_models import CATEGORY_GLOSS

        cats = sorted(extent_categories)

        # Naming runs top-down, so the parents are already named. A formal concept
        # named in isolation is a guess about what a set of attributes means; named
        # under a parent it is a much smaller question — what distinguishes THIS
        # group from the more general one it sits inside.
        place = ""
        if parent_names:
            place = f"""
        This class sits DIRECTLY BELOW: {', '.join(sorted(parent_names))}.
        It is a MORE SPECIFIC kind of that. Name the distinction, not the parent
        again: a subclass name may never be more general than its parent's, and
        must not be the parent's name.
        """
            if differentia:
                place += f"""
        What sets it apart from that parent: {sorted(differentia)}
        """
        else:
            place = """
        This is a TOP-LEVEL class: nothing in this analysis is more general than
        it. Name the widest thing all its members are.
        """

        members = ""
        if extent_sample:
            members = f"""
        Members of this class include: {sorted(extent_sample)[:12]}
        """

        kind = ""
        if cats:
            gloss = "\n".join(f"          {c}: {CATEGORY_GLOSS.get(c, '')}" for c in cats)
            kind = f"""
        Every member of this class is typed as: {', '.join(cats)}
{gloss}

        A superclass is the SAME KIND of thing as its members, only more general.
        Name a grouping of that kind. Do not name a disorder, a process or a
        quality as the superclass of material entities, or vice versa.
        """

        prompt = f"""
        You are a biomedical ontologist. These attributes describe a formal concept class:
        {list(intent_attributes)}
{members}{place}
        Names ALREADY USED in this analysis — yours must differ from every one of
        them, because each names a different class: {sorted(superclass_names)}
{kind}
        Generate ONE concise medical superclass name — maximum 5 words, noun phrase only.
        It must be a meaningful biomedical grouping, not a description of the
        attributes, and NOT the name of a BFO category: "Material entity",
        "Process", "Quality" and the like are the constraint, not an answer.
        Name what these members have in common as medicine would name it.
        """
        # A capped reply: without max_tokens OpenRouter reserves the model's whole
        # output window (131,072 tokens) against the credit, and on 2026-10-11 every
        # naming call was refused with 402 although each needed a few thousand.
        result = await self._execute_with_retry(self._call_json, prompt, SemanticNameResponse, temperature=0.3,
                                                max_tokens=self.BATCH_MAX_TOKENS)
        return result.superclass_name


    async def adjudicate_mappings_batch(
        self, candidates: list[dict]
    ) -> list[MappingVerdict]:
        """Decide whether each (store term, ontology class) pair names ONE class.

        SapBERT has already said the two labels are close; that question is
        settled and asking it again would only reproduce the error. What is asked
        here is the ontological one it cannot answer: same class, or one narrower
        than the other, or simply different.

        Each candidate is a dict with `store_term`, `ontology_class`, and
        optionally `store_category`, `ontology_category`, `ontology_definition`.
        The definition is the point of the exercise -- the LABEL is what fooled
        the embedding, so the class is judged by what the ontology says it is.

        Returns one verdict per pair. A pair the model omits is NOT decided, and
        the caller must treat it as such rather than defaulting either way.
        """
        if not candidates:
            return []

        blocks = []
        for i, c in enumerate(candidates, 1):
            lines = [f'{i}. store term    : "{c["store_term"]}"',
                     f'   ontology class: "{c["ontology_class"]}"']
            if c.get("store_category"):
                lines.append(f'   the store types the store term as: {c["store_category"]}')
            if c.get("ontology_category"):
                lines.append(f'   the ontology types the class as  : {c["ontology_category"]}')
            if c.get("ontology_definition"):
                lines.append(f'   the ontology DEFINES the class as: {c["ontology_definition"]}')
            elif c.get("ontology_parents"):
                lines.append("   the ontology gives no definition, but places the class under: "
                             + ", ".join(sorted(c["ontology_parents"])))
            else:
                lines.append("   the ontology gives no definition for this class.")
            blocks.append("\n".join(lines))
        body = "\n\n".join(blocks)

        prompt = f"""
        You are a biomedical ontologist curating a wound care ontology built on BFO.

        Each pair below was proposed by an embedding model as a SYNONYM match: the
        claim is that the store term and the existing ontology class are two names
        for the SAME class, and that the store term should therefore be absorbed
        into the existing one rather than minted as a new class beside it.

        The embedding is good at surface variance and bad at meaning. It has
        proposed pairs like "Horizontal mattress suture" / "Vertical mattress
        suture" and "clean wound classification grade" / "clean-contaminated wound
        classification grade" — labels that differ by a single word which is the
        whole distinction. Your job is to catch exactly those.

        Judge each pair by what the ontology DEFINITION says the class is, not by
        how similar the two labels look. For each pair return one verdict:

          same_class — the two are the same class under different names, including
                       abbreviation/expansion ("E. coli" / "Escherichia coli") and
                       ordinary lexical variants. Absorbing the store term loses
                       NOTHING.
          narrower   — the store term is a genuine SUBTYPE of the ontology class
                       ("Skin scarring" under "Scarring"). Real information would
                       be lost by merging them.
          broader    — the store term is more general than the ontology class
                       ("clean wound classification grade" is not the same as
                       "clean-contaminated wound classification grade"; where
                       neither contains the other, use `different`).
          different  — neither names the other, or they are siblings that merely
                       share most of their words.

        A BFO note that decides several of these: a PROCESS and the material
        entity it acts on are never the same class, however similar the labels.
        "Debridement" the procedure and "Debridement process" MAY be the same
        class stated twice; "Skin graft" the material and "Skin grafting" the
        process are NOT.

        When you are unsure, answer `different`. A refused mapping costs one
        duplicate class that a curator can merge later; a wrong `same_class`
        silently destroys a distinction and cannot be recovered.

        Give `reason` as one short clause. Use the EXACT store term and ontology
        class strings from the input — do not paraphrase them.

        PAIRS:
        {body}
        """
        result = await self._execute_with_retry(
            self._call_json, prompt, MappingVerdictBatch,
            temperature=0.0, timeout=360, max_tokens=self.BATCH_MAX_TOKENS,
        )
        return result.results
