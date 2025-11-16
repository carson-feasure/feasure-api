# app/tasks/analysis/intent_router.py

import os
import json
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, field_validator
from fastapi import HTTPException
from openai import OpenAI


def _get_openai_client() -> OpenAI:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set in environment variables")
    return OpenAI(api_key=api_key)


client = _get_openai_client()


class IntentLabel(str, Enum):
    CHAT = "chat"                # general Q&A / explanation
    SEARCH_BUILDER = "search_builder"  # user wants a saved search built


class IntentResult(BaseModel):
    intent: IntentLabel
    confidence: float
    reasoning: Optional[str] = None

    @field_validator("confidence")
    @classmethod
    def validate_confidence(cls, v: float) -> float:
        if not (0.0 <= v <= 1.0):
            raise ValueError("confidence must be between 0 and 1")
        return v


def detect_intent(prompt: str) -> IntentResult:
    """
    Lightweight router:
    - Takes natural-language prompt.
    - Returns { intent: 'chat' | 'search_builder', confidence, reasoning }.
    """

    system_instructions = (
        "You are Feasure's intent router. Your job is to classify what the user wants "
        "based ONLY on their latest message.\n\n"
        "You MUST output a single JSON object with this exact structure:\n"
        "{\n"
        '  \"intent\": \"chat\" | \"search_builder\",\n'
        "  \"confidence\": 0.0-1.0,\n"
        "  \"reasoning\": \"short explanation of why you chose this intent\"\n"
        "}\n\n"
        "Definitions:\n"
        "- \"search_builder\": The user is asking to see, filter, or list NetSuite records "
        "   (e.g., \"show me all open purchase orders over 50k\", "
        "   \"find sales orders from last week\", \"build a report of invoices by customer\").\n"
        "- \"chat\": General questions, explanations, or anything that is NOT asking to create "
        "   a search or report (e.g., \"what is a saved search?\", "
        "   \"how do I set up NetSuite approvals?\", \"explain these results\").\n\n"
        "If you are unsure, prefer \"chat\" with a lower confidence.\n"
        "Never include any text outside of the JSON object."
    )

    try:
        completion = client.chat.completions.create(
            model="gpt-4.1-mini",
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system_instructions},
                {"role": "user", "content": prompt},
            ],
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Intent LLM call failed: {e}")

    raw_json = completion.choices[0].message.content

    try:
        data = json.loads(raw_json)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Invalid JSON from intent model: {e}")

    try:
        result = IntentResult.model_validate(data)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Intent validation failed: {e}")

    return result
