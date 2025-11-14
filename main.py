# main.py

import os
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from openai import OpenAI

# Initialize FastAPI app
app = FastAPI()

# Initialize OpenAI client
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    raise RuntimeError("OPENAI_API_KEY is not set in environment variables")

client = OpenAI(api_key=OPENAI_API_KEY)

# ---------- Request / Response Models ----------

class AIRequest(BaseModel):
    prompt: str

class AIResponse(BaseModel):
    reply: str

# ---------- Routes ----------

@app.get("/")
def root():
    return {"status": "ok", "service": "Feasure AI API"}

@app.post("/ai", response_model=AIResponse)
def ai_endpoint(body: AIRequest):
    """
    Basic AI endpoint.
    - Accepts: { "prompt": "some text" }
    - Returns: { "reply": "AI answer" }
    """

    try:
        completion = client.chat.completions.create(
            model="gpt-4.1-mini",  # cheap, good starter model
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are Feasure, an AI assistant that helps with ERP and NetSuite tasks. "
                        "Answer clearly and concisely."
                    ),
                },
                {"role": "user", "content": body.prompt},
            ],
        )

        reply_text = completion.choices[0].message.content
        return AIResponse(reply=reply_text)

    except Exception as e:
        # You can log the error here
        raise HTTPException(status_code=500, detail=str(e))
