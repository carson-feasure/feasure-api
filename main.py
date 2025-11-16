# main.py

import os
from typing import Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from openai import OpenAI

from app.tasks.intent.intent_router import (
    detect_intent,
    IntentLabel,
    IntentResult,
)
from app.tasks.search.search_agent import (
    build_search_from_prompt,
    SearchSpec,
)


app = FastAPI()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    raise RuntimeError("OPENAI_API_KEY is not set in environment variables")

client = OpenAI(api_key=OPENAI_API_KEY)


# ---------- Models ----------

class AIRequest(BaseModel):
    prompt: str
    # Optional override: for testing you can force a mode
    force_mode: Optional[str] = None


class AIResponse(BaseModel):
    mode: str
    reply: Optional[str] = None
    search_spec: Optional[SearchSpec] = None
    explanation: Optional[str] = None
    intent_confidence: Optional[float] = None


# ---------- Chat helper ----------

def call_llm_for_chat(prompt: str) -> str:
    completion = client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[
            {
                "role": "system",
                "content": (
                    "You are Feasure, an AI assistant that helps with ERP and NetSuite tasks. "
                    "Answer clearly and concisely."
                ),
            },
            {"role": "user", "content": prompt},
        ],
    )
    return completion.choices[0].message.content


# ---------- Routes ----------

@app.get("/")
def root():
    return {"status": "ok", "service": "Feasure AI API"}


@app.post("/ai", response_model=AIResponse)
def ai_endpoint(body: AIRequest):
    """
    Unified endpoint:
    - Step 1: detect intent (unless force_mode override).
    - Step 2: dispatch to the correct agent (chat vs search_builder).
    """

    try:
        # Optional override, useful for manual testing
        if body.force_mode == "chat":
            reply = call_llm_for_chat(body.prompt)
            return AIResponse(mode="chat", reply=reply)

        if body.force_mode == "search_builder":
            sb_result = build_search_from_prompt(body.prompt)
            return AIResponse(
                mode="search_builder",
                search_spec=sb_result.search_spec,
                explanation=sb_result.explanation,
            )

        # --- Normal agentic path: use intent router ---
        intent: IntentResult = detect_intent(body.prompt)

        if intent.intent == IntentLabel.SEARCH_BUILDER:
            sb_result = build_search_from_prompt(body.prompt)
            return AIResponse(
                mode="search_builder",
                search_spec=sb_result.search_spec,
                explanation=sb_result.explanation,
                intent_confidence=intent.confidence,
            )

        # Default: chat
        reply = call_llm_for_chat(body.prompt)
        return AIResponse(
            mode="chat",
            reply=reply,
            intent_confidence=intent.confidence,
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
