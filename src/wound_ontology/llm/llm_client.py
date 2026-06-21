from __future__ import annotations
import asyncio
import json
from pathlib import Path

import openai as openai_sdk
from openai import RateLimitError as _RateLimitError

_CQ_PATH = Path(__file__).resolve().parents[3] / "config" / "competency_questions.json"

def _build_cq_block() -> str:
    """Load competency_questions.json and return a compact prompt section."""
    try:
        data = json.loads(_CQ_PATH.read_text())
    except Exception:
        return ""
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
)

_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
_DEFAULT_MODEL = "deepseek/deepseek-v4-flash"


class LLMClient:
    """
    Single LLM interface for the whole pipeline via OpenRouter.

    All tasks (extraction, normalization, NaN fill, FCA naming) go through
    one model — swap the model_id to change provider/quality/cost trade-off.
    Default: DeepSeek Chat (best price/performance as of 2026-04).
    """

    def __init__(self, api_key: str, model_id: str = _DEFAULT_MODEL):
        self._client  = openai_sdk.AsyncOpenAI(
            api_key=api_key,
            base_url=_OPENROUTER_BASE_URL,
        )
        self.model_id = model_id
        # Circuit breaker — set by callers that want early abort on sustained failures.
        self.abort_event: asyncio.Event | None = None
        self._consec_errors: int = 0
        self._max_consec_errors: int = 0

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

    async def _call_json(self, prompt: str, schema: type, temperature=0.0, timeout=240):
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
            )
            raw = resp.choices[0].message.content.strip()
            # Remove code fences if the model wrapped JSON inside them.
            raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
            if hasattr(schema, "model_validate_json"):
                return schema.model_validate_json(raw)
            return schema.parse_raw(raw)

        return await asyncio.wait_for(_inner(), timeout=timeout)

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
          - predicate: "affects", target: "Subcutaneous Tissue"
          - predicate: "caused_by", target: "Sustained Mechanical Load"
        false_attributes:
          - predicate: "occurs_in", target: "Subcutaneous Tissue"  (wrong — affects two continuants, not a process)
          - predicate: "part_of", target: "Chronic Wound"  (wrong — use is_a for taxonomy)

        TEXT: {text}
        """
        result = await self._execute_with_retry(self._call_json, prompt, ExtractResponse, timeout=240)
        return result.entities

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

    async def fill_nan_batch(self, entity_attrs: dict[str, list[str]]) -> dict[str, list[str]]:
        if not entity_attrs:
            return {}
        body = "\n\n".join(
            f'Entity: "{entity}"\nCandidate attributes: {attrs}'
            for entity, attrs in entity_attrs.items()
        )
        prompt = f"""
        Act as a clinical ontologist. For each entity below, return ONLY the candidate attributes
        that are FACTUALLY and CLINICALLY true. Exclude attributes that are incorrect, uncertain,
        or not defining characteristics. Return results for every entity listed.

        {body}
        """
        result = await self._execute_with_retry(self._call_json, prompt, FillNanBatchResponse, temperature=0.0, timeout=240)
        return {r.object_name: r.confirmed_attributes for r in result.results}

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

    async def generate_semantic_name(self, intent_attributes, superclass_names) -> str:
        prompt = f"""
        You are a biomedical ontologist. These attributes describe a formal concept class:
        {list(intent_attributes)}

        Existing superclass names (avoid duplicates): {superclass_names}

        Generate ONE concise medical superclass name — maximum 5 words, noun phrase only.
        It must be a meaningful biomedical grouping, not a description of the attributes.
        """
        result = await self._execute_with_retry(self._call_json, prompt, SemanticNameResponse, temperature=0.3)
        return result.superclass_name
