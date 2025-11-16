# app/tasks/search/search_agent.py

import os
import json
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, field_validator
from fastapi import HTTPException
from openai import OpenAI


# --------- OpenAI Client Setup ---------

def _get_openai_client() -> OpenAI:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set in environment variables")
    return OpenAI(api_key=api_key)


client = _get_openai_client()


# --------- Feasure Search Library (MVP) ---------
"""
This is Feasure's internal "schema vocabulary" for the LLM.

Later, you can move this to a config file or DB; for now, it's a dict.
We will *hint* this to the model in the system prompt so it uses these IDs.
"""

FEASURE_SEARCH_LIBRARY: Dict[str, Any] = {
    "recordTypes": ["purchaseorder", "salesorder", "transaction"],

    "transactionTypes": {
        "purchaseorder": "PurchOrd",
        "salesorder": "SalesOrd",
    },

    # Common fields we want the LLM to favor.
    "fields": {
        "transaction": [
            "tranid",      # internal doc number
            "entity",      # customer / vendor
            "amount",
            "status",
            "trandate",
            "department",
            "class",
            "location",
        ]
    },

    # Status IDs for purchase orders (can expand over time).
    "purchaseorderStatus": {
        "pending_approval": "PurchOrd:A",
        "pending_receipt": "PurchOrd:B",
        "partially_received": "PurchOrd:C",
        "closed": "PurchOrd:H",
        # "open" is typically pending approval/receipt/partially received;
        # the agent can choose one or more of these for "open".
    },

    # Allowed date placeholders the model can use.
    "datePlaceholders": [
        "today",
        "yesterday",
        "7d_ago",
        "30d_ago",
        "90d_ago",
        "start_of_month",
        "start_of_last_month",
    ],
}


# --------- Pydantic Models ---------

ALLOWED_RECORD_TYPES = {"purchaseorder", "salesorder", "transaction"}

# Allowed operators in filters (MVP list; extend as needed)
ALLOWED_OPERATORS = {
    "anyof",
    "noneof",
    "is",
    "isnot",
    "greaterthan",
    "lessthan",
    "greaterthanorequalto",
    "lessthanorequalto",
    "onorafter",
    "onorbefore",
    "on",
}


class SearchSpec(BaseModel):
    """
    JSON spec that Feasure will accept to create a NetSuite saved search.
    This is intentionally close to NetSuite's search.create API.
    """
    action: Literal["create_saved_search"]
    recordType: str               # e.g. "purchaseorder"
    searchTitle: str              # title used when saving the search
    filters: List[Any]            # NetSuite-style filters array (triplets + "AND"/"OR")
    columns: List[str]            # list of field IDs for columns

    @field_validator("recordType")
    @classmethod
    def validate_record_type(cls, v: str) -> str:
        if v not in ALLOWED_RECORD_TYPES:
            raise ValueError(f"recordType '{v}' is not allowed")
        return v

    @field_validator("filters")
    @classmethod
    def validate_filters_not_empty(cls, v: List[Any]) -> List[Any]:
        if not v:
            raise ValueError("filters cannot be empty for saved search")
        return v

    @field_validator("columns")
    @classmethod
    def validate_columns_not_empty(cls, v: List[str]) -> List[str]:
        if not v:
            raise ValueError("columns cannot be empty for saved search")
        return v


class SearchBuilderResult(BaseModel):
    mode: Literal["search_builder"]
    search_spec: SearchSpec
    explanation: Optional[str] = None


# --------- Extra Safety: Validate Against Library ---------

def _validate_against_library(spec: SearchSpec) -> None:
    """
    Extra semantic validation beyond basic schema:
    - Columns must be in Feasure's known field list.
    - Filter field IDs must be known (except special ones like 'type').
    - Operators must come from an allow-list.
    """
    allowed_fields = set(FEASURE_SEARCH_LIBRARY["fields"]["transaction"])

    # 1) Validate columns
    for col in spec.columns:
        if col not in allowed_fields:
            raise HTTPException(
                status_code=400,
                detail=f"Column '{col}' is not allowed / not in Feasure library",
            )

    # 2) Validate filters
    i = 0
    while i < len(spec.filters):
        part = spec.filters[i]
        if isinstance(part, list) and len(part) >= 3:
            field_id = part[0]
            operator = part[1]

            # Allow 'type' as a special field even if not in fields list
            if field_id not in allowed_fields and field_id != "type":
                raise HTTPException(
                    status_code=400,
                    detail=f"Filter field '{field_id}' is not allowed / not in Feasure library",
                )

            if operator not in ALLOWED_OPERATORS:
                raise HTTPException(
                    status_code=400,
                    detail=f"Filter operator '{operator}' is not allowed",
                )

        i += 1


# --------- Core Agent Function ---------

def build_search_from_prompt(prompt: str) -> SearchBuilderResult:
    """
    Core 'search agent' function.
    - Takes a natural-language prompt from a NetSuite user.
    - Uses Feasure's search library + OpenAI to produce a SearchBuilderResult.
    - Enforces strict JSON structure and allowed record types.
    """

    # Minimal JSON representation of the library for the model
    # (kept small so we don't blow up context).
    library_json = json.dumps(
        {
            "recordTypes": FEASURE_SEARCH_LIBRARY["recordTypes"],
            "transactionTypes": FEASURE_SEARCH_LIBRARY["transactionTypes"],
            "fields": FEASURE_SEARCH_LIBRARY["fields"],
            "purchaseorderStatus": FEASURE_SEARCH_LIBRARY["purchaseorderStatus"],
            "datePlaceholders": FEASURE_SEARCH_LIBRARY["datePlaceholders"],
        },
        indent=2,
    )

    system_instructions = (
        "You are Feasure, an AI assistant that designs NetSuite saved searches.\n"
        "Your job is to analyze the user's natural-language request and output a JSON object "
        "that describes a NetSuite saved search to create.\n\n"
        "You have access to the following NetSuite vocabulary (field IDs, record types, etc.):\n"
        f"{library_json}\n\n"
        "CRITICAL RULES:\n"
        "1. Output ONLY a single JSON object, no commentary, no markdown.\n"
        "2. The JSON MUST conform to this structure:\n"
        "{\n"
        '  \"mode\": \"search_builder\",\n'
        "  \"search_spec\": {\n"
        '    \"action\": \"create_saved_search\",\n'
        '    \"recordType\": \"purchaseorder\" | \"salesorder\" | \"transaction\",\n'
        '    \"searchTitle\": \"<short human-readable title>\",\n'
        "    \"filters\": [\n"
        "       // NetSuite-style filters, for example:\n"
        "       [\"type\", \"anyof\", \"PurchOrd\"],\n"
        "       \"AND\",\n"
        "       [\"status\", \"anyof\", \"PurchOrd:A\"],\n"
        "       \"AND\",\n"
        "       [\"amount\", \"greaterthan\", \"50000\"],\n"
        "       \"AND\",\n"
        "       [\"trandate\", \"onorafter\", \"30d_ago\"]\n"
        "    ],\n"
        "    \"columns\": [\"tranid\", \"entity\", \"amount\", \"status\", \"trandate\"]\n"
        "  },\n"
        "  \"explanation\": \"Short human-readable explanation of the search, in plain English.\"\n"
        "}\n\n"
        "3. Do NOT invent record types beyond the allowed list.\n"
        "4. Use the field IDs and status IDs from the vocabulary when possible.\n"
        "5. Use reasonable default columns so the search is immediately useful.\n"
        "6. When the user does not specify exact amounts or date ranges, infer sensible defaults.\n"
        "7. For date filters, you may use placeholders like \"30d_ago\", \"7d_ago\", \"today\"; "
        "   the backend/NetSuite will interpret them.\n"
        "8. Never return JavaScript or any code, only the JSON object described above.\n"
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
        # This error means the OpenAI call itself failed.
        raise HTTPException(status_code=502, detail=f"LLM call failed: {e}")

    raw_json = completion.choices[0].message.content

    try:
        data = json.loads(raw_json)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Invalid JSON from model: {e}")

    try:
        result = SearchBuilderResult.model_validate(data)
    except Exception as e:
        # The model returned JSON, but it didn't match our schema.
        raise HTTPException(
            status_code=400,
            detail=f"Search spec validation failed: {e}"
        )

    # Extra semantic validation against Feasure's library
    _validate_against_library(result.search_spec)

    return result
