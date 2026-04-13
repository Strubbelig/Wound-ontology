from __future__ import annotations
import asyncio
import json
from abc import ABC, abstractmethod

import google.genai as genai
from google.genai import types

import anthropic as anthropic_sdk
import openai as openai_sdk

from wound_ontology.llm.schemas import (
    ExtractResponse, NormalizationResponse, FillNanResponse,
    FillNanBatchResponse, SemanticNameResponse
)


# ── Base ───────────────────────────────────────────────────────────────────────

class BaseLLMClient(ABC):
    """Common retry wrapper + abstract task interface."""

    async def _execute_with_retry(self, operation_func, *args, **kwargs):
        max_retries = 5
        for attempt in range(max_retries):
            try:
                return await operation_func(*args, **kwargs)
            except Exception as e:
                if attempt < max_retries - 1:
                    wait = (attempt + 1) * 5
                    print(f"[LLM] Error. Retry {attempt + 1} in {wait}s...")
                    await asyncio.sleep(wait)
                else:
                    raise e

    @abstractmethod
    async def extract_entities(self, text, predicates, targets, attributes, predicate_definitions=None):
        ...

    @abstractmethod
    async def create_normalization_mapping(self, terms, standards) -> dict:
        ...

    @abstractmethod
    async def fill_nan(self, object_name: str, attributes: list[str]) -> list[str]:
        ...

    @abstractmethod
    async def fill_nan_batch(self, entity_attrs: dict[str, list[str]]) -> dict[str, list[str]]:
        ...

    @abstractmethod
    async def generate_semantic_name(self, intent_attributes, superclass_names) -> str:
        ...


# ── Gemini ─────────────────────────────────────────────────────────────────────

class GeminiClient(BaseLLMClient):
    """Handles extraction and NaN filling via Gemini Flash."""

    def __init__(self, api_key: str, model_id: str = "gemini-3-flash-preview"):
        self.client   = genai.Client(api_key=api_key)
        self.model_id = model_id

    async def _call(self, prompt, response_model, temperature=0.1, timeout=60):
        return await asyncio.wait_for(
            self.client.aio.models.generate_content(
                model=self.model_id,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=response_model,
                    temperature=temperature,
                ),
            ),
            timeout=timeout,
        )

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

    async def extract_entities(self, text, predicates, targets, attributes, predicate_definitions=None):
        predicate_block = (
            self._build_predicate_block(predicates, predicate_definitions)
            if predicate_definitions
            else f"        Use only these predicates: {predicates}"
        )
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
        5. MUTUAL EXCLUSION: If you assign is_a: X for an entity, you MUST NOT also assign part_of: X for the same target X.

        ══ EXAMPLE ══
        Object: "Surgical Site Infection"
        true_attributes:
          - predicate: "is_a", target: "Infectious Complication"
          - predicate: "occurs_in", target: "Surgical Site"
          - predicate: "caused_by", target: "Bacterial Contamination"
        false_attributes:
          - predicate: "part_of", target: "Infectious Complication"
          - predicate: "is_a", target: "Surgical Instrument"

        TEXT: {text}
        """
        response = await self._execute_with_retry(self._call, prompt, ExtractResponse)
        return response.parsed.entities

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
        """
        response = await self._execute_with_retry(self._call, prompt, NormalizationResponse, timeout=120)
        return {item.original: item.standard for item in response.parsed.mappings}

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
        response = await self._execute_with_retry(self._call, prompt, FillNanResponse, temperature=0.0)
        return response.parsed.confirmed_attributes

    async def fill_nan_batch(self, entity_attrs: dict[str, list[str]]) -> dict[str, list[str]]:
        """
        Evaluate NaN attributes for multiple entities in a single LLM call.
        entity_attrs: {entity_name: [missing_attr, ...]}
        Returns:      {entity_name: [confirmed_attr, ...]}
        """
        if not entity_attrs:
            return {}
        lines = []
        for entity, attrs in entity_attrs.items():
            lines.append(f'Entity: "{entity}"\nCandidate attributes: {attrs}')
        body = "\n\n".join(lines)
        prompt = f"""
        Act as a clinical ontologist. For each entity below, return ONLY the candidate attributes
        that are FACTUALLY and CLINICALLY true. Exclude attributes that are incorrect, uncertain,
        or not defining characteristics. Return results for every entity listed.

        {body}
        """
        response = await self._execute_with_retry(self._call, prompt, FillNanBatchResponse, temperature=0.0)
        return {r.object_name: r.confirmed_attributes for r in response.parsed.results}

    async def generate_semantic_name(self, intent_attributes, superclass_names) -> str:
        prompt = f"""
        These medical attributes describe a class: {list(intent_attributes)}
        These are the superclass names already found: {superclass_names}
        Generate ONE short medical superclass name (max 5 words, noun only). Be explicit enough to avoid any duplicates.
        """
        response = await self._execute_with_retry(self._call, prompt, SemanticNameResponse, temperature=0.3)
        return response.parsed.superclass_name


# ── Anthropic ─────────────────────────────────────────────────────────────────

class AnthropicClient(BaseLLMClient):
    """Handles FCA concept naming via Claude Sonnet — highest quality naming."""

    def __init__(self, api_key: str, model_id: str = "claude-sonnet-4-6"):
        self.client   = anthropic_sdk.AsyncAnthropic(api_key=api_key)
        self.model_id = model_id

    async def _call_json(self, prompt: str, schema: type, temperature=0.3, timeout=60) -> dict:
        async def _inner():
            msg = await self.client.messages.create(
                model=self.model_id,
                max_tokens=256,
                temperature=temperature,
                messages=[{"role": "user", "content": prompt}],
                tools=[{
                    "name": "respond",
                    "description": "Respond with structured JSON.",
                    "input_schema": schema.model_json_schema(),
                }],
                tool_choice={"type": "tool", "name": "respond"},
            )
            for block in msg.content:
                if block.type == "tool_use":
                    return schema(**block.input)
            raise ValueError("No tool_use block in Anthropic response")

        return await asyncio.wait_for(_inner(), timeout=timeout)

    # Only naming is routed here — the others delegate to avoid dead code
    async def generate_semantic_name(self, intent_attributes, superclass_names) -> str:
        prompt = f"""
        You are a biomedical ontologist. These attributes describe a formal concept class:
        {list(intent_attributes)}

        Existing superclass names (avoid duplicates): {superclass_names}

        Generate ONE concise medical superclass name — maximum 5 words, noun phrase only.
        It must be a meaningful biomedical grouping, not a description of the attributes.
        """
        result = await self._execute_with_retry(
            self._call_json, prompt, SemanticNameResponse, temperature=0.3
        )
        return result.superclass_name

    async def extract_entities(self, *a, **kw):
        raise NotImplementedError("Use GeminiClient for extraction.")

    async def create_normalization_mapping(self, *a, **kw):
        raise NotImplementedError("Use OpenAIClient for normalization.")

    async def fill_nan(self, *a, **kw):
        raise NotImplementedError("Use GeminiClient for NaN filling.")

    async def fill_nan_batch(self, *a, **kw):
        raise NotImplementedError("Use GeminiClient for NaN filling.")


# ── OpenAI ────────────────────────────────────────────────────────────────────

class OpenAIClient(BaseLLMClient):
    """Handles term normalization via GPT-4o mini — consistent synonym collapse."""

    def __init__(self, api_key: str, model_id: str = "gpt-4o-mini"):
        self.client   = openai_sdk.AsyncOpenAI(api_key=api_key)
        self.model_id = model_id

    async def _call_json(self, prompt: str, schema: type, temperature=0.1, timeout=120) -> object:
        async def _inner():
            response = await self.client.beta.chat.completions.parse(
                model=self.model_id,
                messages=[{"role": "user", "content": prompt}],
                response_format=schema,
                temperature=temperature,
            )
            return response.choices[0].message.parsed

        return await asyncio.wait_for(_inner(), timeout=timeout)

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
        """
        result = await self._execute_with_retry(self._call_json, prompt, NormalizationResponse, temperature=0.1)
        return {item.original: item.standard for item in result.mappings}

    async def extract_entities(self, *a, **kw):
        raise NotImplementedError("Use GeminiClient for extraction.")

    async def generate_semantic_name(self, *a, **kw):
        raise NotImplementedError("Use AnthropicClient for naming.")

    async def fill_nan(self, *a, **kw):
        raise NotImplementedError("Use GeminiClient for NaN filling.")

    async def fill_nan_batch(self, *a, **kw):
        raise NotImplementedError("Use GeminiClient for NaN filling.")


# ── Router ────────────────────────────────────────────────────────────────────

class LLMClient(BaseLLMClient):
    """
    Single LLM interface for the whole pipeline.

    Internally routes each task to the most suitable provider:
      - extraction + NaN fill → Gemini Flash  (fast, cheap, high volume)
      - normalization         → GPT-4o mini   (consistent synonym collapse)
      - FCA concept naming    → Claude Sonnet (highest quality, low volume)

    Falls back to Gemini for any task whose provider key is missing.
    """

    def __init__(
        self,
        google_api_key: str = "",
        anthropic_api_key: str = "",
        openai_api_key: str = "",
    ):
        self._gemini    = GeminiClient(google_api_key)
        self._anthropic = AnthropicClient(anthropic_api_key) if anthropic_api_key else None
        self._openai    = OpenAIClient(openai_api_key)       if openai_api_key    else None

    # ── Task routing ──────────────────────────────────────────────────────────

    async def extract_entities(self, text, predicates, targets, attributes, predicate_definitions=None):
        return await self._gemini.extract_entities(
            text, predicates, targets, attributes, predicate_definitions
        )

    async def create_normalization_mapping(self, terms, standards) -> dict:
        client = self._openai or self._gemini
        return await client.create_normalization_mapping(terms, standards)

    async def fill_nan(self, object_name: str, attributes: list[str]) -> list[str]:
        return await self._gemini.fill_nan(object_name, attributes)

    async def fill_nan_batch(self, entity_attrs: dict[str, list[str]]) -> dict[str, list[str]]:
        return await self._gemini.fill_nan_batch(entity_attrs)

    async def generate_semantic_name(self, intent_attributes, superclass_names) -> str:
        client = self._anthropic or self._gemini
        return await client.generate_semantic_name(intent_attributes, superclass_names)
