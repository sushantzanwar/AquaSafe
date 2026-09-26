from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Dict, Any, Optional
import os
import sys
from dotenv import load_dotenv

load_dotenv()

# Import our RAG logic
# Adjusting sys.path to allow importing from the sibling 'rag' directory
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
from rag.assistant import generate_explanation_with_sources

app = FastAPI(title="AquaWatch AI Assistant API")

# Define the Pydantic models for our request payload
class AskRequest(BaseModel):
    analysis_id: str
    user_question: str
    live_data: Dict[str, Any]  # The JSON contract payload from the frontend/backend

class AskResponse(BaseModel):
    analysis_id: str
    question: str
    explanation: str
    sources: list = []

@app.post("/api/assistant/ask", response_model=AskResponse)
async def ask_assistant(request: AskRequest):
    """
    Endpoint for the Frontend to ask the AI Assistant a question about a specific analysis.
    The frontend passes the current live JSON data, and the assistant uses RAG to explain it.
    """
    if not os.getenv("GEMINI_API_KEY"):
        raise HTTPException(
            status_code=500, 
            detail="GEMINI_API_KEY environment variable is not set on the server."
        )

    try:
        # generate_explanation_with_sources automatically queries ChromaDB
        # for relevant scientific context and returns citation metadata.
        explanation, sources = generate_explanation_with_sources(
            live_json_data=request.live_data,
            scientific_context="",
            user_question=request.user_question
        )

        return AskResponse(
            analysis_id=request.analysis_id,
            question=request.user_question,
            explanation=explanation,
            sources=sources
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generating explanation: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    # Run using: python assistant_api.py
    uvicorn.run(app, host="0.0.0.0", port=8001)
