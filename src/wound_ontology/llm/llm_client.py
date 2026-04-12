from __future__ import annotations
import asyncio
import google.genai as genai
from google.genai import types
from wound_ontology.llm.schemas import (
    ExtractResponse, NormalizationResponse, FillNanResponse, SemanticNameResponse
)


class LLMClient:
    def __init__(self, api_key):
        self.client = genai.Client(api_key=api_key)
        self.model_id = "gemini-3-flash-preview"

    async def _call_api(self, prompt, response_model, temperature=0.1, timeout=60):
        return await asyncio.wait_for(
            self.client.aio.models.generate_content(
                model=self.model_id,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=response_model,
                    temperature=temperature
                )
            ),
            timeout=timeout,
        )

    async def _execute_with_retry(self, operation_func, *args, **kwargs):
        max_retries = 5
        for attempt in range(max_retries):
            try:
                # We await the operation here
                return await operation_func(*args, **kwargs)
            except Exception as e: # Catch relevant errors (ServerError, etc.)
                if attempt < max_retries - 1:
                    wait = (attempt + 1) * 5
                    print(f"[LLM] Error. Retry {attempt+1} in {wait}s...")
                    # NON-BLOCKING sleep: allows other tasks to run
                    await asyncio.sleep(wait)
                else:
                    raise e


    @staticmethod
    def _build_predicate_block(predicates: list[str], definitions: dict) -> str:
        """
        Builds the predicate section of the extraction prompt dynamically.
        For each predicate in *predicates*, looks up its entry in *definitions*
        (which follows the PREDICATE_DEFINITIONS schema in config/settings.py).
        Falls back to a minimal line when a predicate has no entry.
        """
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

    async def extract_entities(self, text, predicates, targets, attributes, predicate_definitions=None):
        """
        Extracts clinical entities using a strict Pydantic response schema.

        predicate_definitions – dict keyed by predicate name, each with
                                'summary', 'yes' (examples), 'no' (rules).
                                When provided the predicate block is built
                                dynamically; otherwise a generic header is used.
        """
        if predicate_definitions:
            predicate_block = self._build_predicate_block(predicates, predicate_definitions)
        else:
            predicate_block = f"        Use only these predicates: {predicates}"

        prompt = f"""
        Analyze the following clinical text to build a formal wound ontology compliant with BFO and RO standards.
        The domain is clinical and surgical (medication, surgical treatment, physical therapy, etiology, pathophysiology, classifications).

        GOAL: Extract objects and their FORMAL ATTRIBUTES. Every attribute is a composite of a predicate and a target.

        ══ PREDICATE DEFINITIONS AND RULES ══

{predicate_block}

        ══ CONSTRAINTS ══
        1. Use only these predicates: {predicates}
        2. Reuse existing targets whenever possible: {targets}. Targets are singular nouns, adjectives, or short noun phrases.
        3. Add confirmed attributes to true_attributes, denied to false_attributes.
        4. Classify existing attributes where possible: {attributes}
        5. MUTUAL EXCLUSION: If you assign is_a: X for an entity, you MUST NOT also assign part_of: X for the same target X. Taxonomic subclass (is_a) and mereological containment (part_of) are mutually exclusive for the same pair.

        ══ EXAMPLE ══
        Object: "Surgical Site Infection"
        true_attributes:
          - predicate: "is_a", target: "Infectious Complication"    ← subtype relationship
          - predicate: "occurs_in", target: "Surgical Site"         ← location
          - predicate: "caused_by", target: "Bacterial Contamination"
        false_attributes:
          - predicate: "part_of", target: "Infectious Complication" ← WRONG: is_a, not part_of
          - predicate: "is_a", target: "Surgical Instrument"

        TEXT: {text}
        """

        response = await self._execute_with_retry(self._call_api, prompt, ExtractResponse)

        return response.parsed.entities


    async def create_normalization_mapping(self, terms, standards):
        """
        Maps original medical terms to standardized clinical terms.
        """

        prompt = f"""
        You are provided a batch of medical terms which have to be normalized for a clinical ontology.
        Terms that refer to the same concept MUST map to the same single standard — regardless of word form.
        For example: 'infected', 'infection', 'infective' all refer to the same concept and must all map to one standard (e.g. 'infected').

        INPUT STANDARDS (reuse these whenever a term matches conceptually): {standards}
        TERMS TO PROCESS: {terms}

        STRICT RULES:
        1. COLLAPSE SAME-CONCEPT TERMS: If two or more terms refer to the same clinical concept (even across word forms — noun, adjective, verb, adverb), they MUST share one standard. Pick the most natural adjective or noun form used in clinical text.
        2. If a term matches an INPUT STANDARD conceptually, you MUST reuse that standard exactly.
        3. Do NOT invent a new term if an existing standard covers the concept.
        4. Only create a new standard if no existing standard covers the concept.
        """

        response = await self._execute_with_retry(self._call_api, prompt, NormalizationResponse, timeout=120)

        return {item.original: item.standard for item in response.parsed.mappings}


    async def fill_nan(self, object_name: str, attributes: list[str]) -> list[str]:
        """
        Resolves NaNs by verifying which attributes apply to a given object.
        Used by _Matrix.fill_nan.
        Output: list of confirmed attributes
        """
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
        response = await self._execute_with_retry(self._call_api, prompt, FillNanResponse, temperature=0.0)

        return response.parsed.confirmed_attributes


    async def generate_semantic_name(self, intent_attributes,superclass_names):
        """
        Generates a concise medical superclass name.
        """
        prompt = f"""
        These medical attributes describe a class: {list(intent_attributes)}
        These are the superclass names already found: {superclass_names}
        Generate ONE short medical superclass name (max 5 words, noun only). Be explicit enough to avoid any duplicates.
        """

        response = await self._execute_with_retry(self._call_api,prompt, SemanticNameResponse, temperature=0.3)


        return response.parsed.superclass_name

    def close(self):
        self.client.close()
