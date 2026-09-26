import os
import json
import urllib.request
import urllib.error
from dotenv import load_dotenv

# Always load the .env from ai_assistant/ dir, regardless of where this is imported from
_ENV_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
load_dotenv(dotenv_path=_ENV_PATH, override=True)

# Also check root .env
_ROOT_ENV = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), ".env")
if os.path.exists(_ROOT_ENV):
    load_dotenv(dotenv_path=_ROOT_ENV, override=False)

# Dynamic, grounded system prompt instructions
SYSTEM_INSTRUCTION = """You are AquaWatch AI, an intelligent satellite hydrology and water quality expert powered by Google Gemini.
You analyze live multispectral Sentinel-2 satellite telemetry (NDWI water index, NDTI turbidity index, NDCI chlorophyll-a index, and anomaly z-scores) combined with indexed peer-reviewed scientific literature.

GUIDELINES:
1. Provide accurate, clear, and comprehensive answers to user questions — ranging from technical spectral physics (Sentinel-2 band ratios 705nm/665nm) to water safety, recreational swimming risk, algae blooms, and water management.
2. Ground your answer in the provided LIVE DATA and SCIENTIFIC CONTEXT when relevant.
3. If an anomaly is present, explain what the spectral indicators mean in practical terms (e.g., NDCI > 0.15 signals elevated chlorophyll/algal proliferation; NDTI > 0.20 signals elevated suspended solids and turbidity).
4. For citizen and recreational doubts (e.g. "is it safe to swim?", "what does green water mean?"), provide practical safety-focused advice referencing WHO (World Health Organization) and EPA recreational water criteria.
5. Format your output cleanly in Markdown with bold key terms, bullet points, and section headers where appropriate.
6. Always return fresh, insightful, context-aware responses."""

AVAILABLE_MODELS = [
    "gemini-3.8-flash",
    "gemini-3.5-flash",
    "gemini-3.1-flash-lite",
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-flash-latest",
]


def _call_gemini_rest(model_name: str, prompt_text: str, api_key: str, timeout: int = 15) -> str:
    """Direct REST call to Gemini generateContent endpoint for speed and resilience."""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [{"text": prompt_text}]
            }
        ],
        "generationConfig": {
            "temperature": 0.2,
            "maxOutputTokens": 1500,
            "topP": 0.95
        }
    }
    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        resp_data = json.loads(response.read().decode('utf-8'))
        candidates = resp_data.get("candidates", [])
        if candidates:
            parts = candidates[0].get("content", {}).get("parts", [])
            if parts:
                return parts[0].get("text", "")
    return ""


def _invoke_with_model_fallback(formatted_prompt_args: dict) -> str:
    """Attempts invocation with primary fast Gemini model, falling back gracefully."""
    api_key = os.getenv("GEMINI_API_KEY", os.getenv("LLM_API_KEY", "")).strip().strip('"').strip("'")

    live_data = formatted_prompt_args.get("live_data", "{}")
    context = formatted_prompt_args.get("context", "")
    question = formatted_prompt_args.get("question", "")

    full_prompt = (
        f"{SYSTEM_INSTRUCTION}\n\n"
        f"---------------------\n"
        f"LIVE WATER TELEMETRY:\n{live_data}\n"
        f"---------------------\n"
        f"PEER-REVIEWED SCIENTIFIC CONTEXT (from ChromaDB Vector Store):\n{context if context else 'No additional literature context.'}\n"
        f"---------------------\n\n"
        f"USER QUESTION: {question}\n\n"
        f"DETAILED ANSWER:"
    )

    last_error = "Unknown error"
    if api_key:
        for model_name in AVAILABLE_MODELS:
            try:
                res = _call_gemini_rest(model_name, full_prompt, api_key, timeout=12)
                if res and res.strip():
                    return res.strip()
            except Exception as e:
                last_error = f"{model_name} failed: {str(e)}"
                continue

    # Grounded fallback if network or all models unavailable
    wb_name = "the water body"
    try:
        if isinstance(live_data, str) and "water_body" in live_data:
            import ast
            parsed = ast.literal_eval(live_data)
            if isinstance(parsed, dict) and "water_body" in parsed:
                wb_name = parsed["water_body"]
    except Exception:
        pass

    q_lower = question.lower()
    if any(k in q_lower for k in ["swim", "bath", "safe", "danger", "recreation", "skin", "health"]):
        return (
            f"### ⚠️ Recreational Water Safety Assessment: {wb_name}\n\n"
            f"Based on WHO Guidelines for Safe Recreational Water Environments and EPA Criteria:\n\n"
            f"- **Primary Guidance:** Direct contact recreation (swimming, diving) is **not recommended** when water displays visible green discoloration, scums, or elevated chlorophyll-a (NDCI > 0.15).\n"
            f"- **Potential Health Risks:** High cyanobacterial concentrations can release dermatotoxins and microcystins, causing skin irritation, conjunctivitis, allergic reactions, or gastrointestinal distress if ingested.\n"
            f"- **Precautionary Measures:** Avoid immersion, keep domestic animals away from shorelines with surface mats, and wait for confirmation via laboratory algal toxin assays or Secchi depth > 1.2m."
        )

    return (
        f"### ⚠️ AI Service Temporarily Unavailable\n\n"
        f"**Telemetry & Scientific Assessment for:** *\"{question}\"*\n\n"
        f"- **Error Details:** Failed to connect to Gemini API. Error: {last_error}\n"
        f"- **API Key Used:** {api_key[:5]}... (Length: {len(api_key)})"
    )


def generate_explanation_with_sources(live_json_data: dict, scientific_context: str, user_question: str) -> tuple:
    """
    Generates an explanation using Gemini (with fallback) and returns (explanation, sources_list).
    Automatically retrieves relevant scientific context and citation metadata from ChromaDB.
    """
    sources = []
    try:
        from ai_assistant.rag.vector_store import search_with_metadata, is_populated
        if is_populated():
            retrieved, sources = search_with_metadata(user_question, n_results=3)
            if retrieved:
                scientific_context = retrieved + (
                    ("\n\n[Additional Context]\n" + scientific_context) if scientific_context else ""
                )
    except Exception:
        pass

    explanation = _invoke_with_model_fallback(
        formatted_prompt_args={
            "live_data": str(live_json_data),
            "context": scientific_context,
            "question": user_question
        }
    )

    return explanation, sources


def generate_explanation(live_json_data: dict, scientific_context: str, user_question: str) -> str:
    """Backward-compatible wrapper returning only the explanation string."""
    explanation, _ = generate_explanation_with_sources(live_json_data, scientific_context, user_question)
    return explanation


def generate_dynamic_questions(analysis_data: dict) -> list:
    """
    Uses Gemini to dynamically generate 4 contextual questions tailored to the active lake's telemetry.
    """
    wb = analysis_data.get('water_body', 'this water body')
    ind = analysis_data.get('indicators', {})
    anom = analysis_data.get('anomaly', {})

    api_key = os.getenv("GEMINI_API_KEY", os.getenv("LLM_API_KEY", "")).strip().strip('"').strip("'")
    if api_key:
        q_prompt = (
            f"Given the following live water quality telemetry for {wb}:\n"
            f"Indicators: {ind}\n"
            f"Anomaly Status: {anom}\n"
            f"Generate 4 short, interesting, natural questions a user or water manager would ask about this specific lake.\n"
            f"Return ONLY the 4 questions, one per line, with no numbering, bullet points, or prefixes."
        )
        for model_name in AVAILABLE_MODELS:
            try:
                res = _call_gemini_rest(model_name, q_prompt, api_key, timeout=8)
                if res and res.strip():
                    lines = [line.strip().lstrip("0123456789.-*• ") for line in res.split("\n") if line.strip()]
                    if len(lines) >= 3:
                        return lines[:4]
            except Exception:
                continue

    return [
        f"What does the current NDCI reading mean for {wb}?",
        f"What drives turbidity and SPM levels in {wb}?",
        f"Is it safe for swimming or recreation in {wb} right now?",
        f"How does the current reading compare to historical baseline?"
    ]


if __name__ == "__main__":
    dummy_live = {"water_body": "Futala Lake", "indicators": {"ndci": 0.38, "ndti": 0.25}}
    ans, src = generate_explanation_with_sources(dummy_live, "", "Is it dangerous if I swim in green water?")
    print("Answer:\n", ans)
    print("Sources:", src)
