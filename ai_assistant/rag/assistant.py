import os
from dotenv import load_dotenv, find_dotenv

# Always load the .env from ai_assistant/ dir, regardless of where this is imported from
_ENV_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
load_dotenv(dotenv_path=_ENV_PATH, override=True)

try:
    from langchain_google_genai import ChatGoogleGenerativeAI
    from langchain_core.prompts import ChatPromptTemplate
    from langchain_core.output_parsers import StrOutputParser
    HAS_LANGCHAIN = True
except Exception:
    HAS_LANGCHAIN = False

# 2. Create a strict prompt template to force the model to ground its answers
PROMPT_TEMPLATE = """
You are AquaWatch, a dual-purpose AI assistant.
1. When asked about specific water anomalies or satellite data, you are a strict scientific expert.
2. When asked general questions about water quality, health, or citizen science, you are a helpful and educational guide.

CRITICAL INSTRUCTIONS:
- SCENARIO A (System Anomaly): If the user asks why a specific lake was flagged, ONLY use the provided LIVE DATA and SCIENTIFIC CONTEXT to explain the exact reason. Explain the anomaly as a shift from the historical baseline (e.g. "elevated turbidity-related spectral indicators relative to the baseline"). State the percentage of anomalous area if present.
- SCENARIO B (Citizen Doubt): If the user asks a general question, answer them helpfully using your general knowledge.
- TERMINOLOGY: Do NOT use the words "pollution" or "contamination" definitively unless confirmed by a lab. Instead use "spectral anomaly", "baseline deviation", "optical condition", or "anomalous area". State that "this indicates an unusual optical condition, but does not by itself confirm a specific contaminant. Field sampling is recommended."
- ALWAYS keep your explanation clear, professional, and accessible to a non-scientist.

---------------------
LIVE DATA (If applicable):
{live_data}
---------------------
SCIENTIFIC CONTEXT (If applicable):
{context}
---------------------

USER QUESTION: {question}

EXPLANATION:
"""

if HAS_LANGCHAIN:
    prompt = ChatPromptTemplate.from_template(PROMPT_TEMPLATE)
else:
    prompt = None

def _get_llm():
    """Lazily initialize the LLM so the API key is read at call time, not import time."""
    if not HAS_LANGCHAIN:
        return None
    try:
        return ChatGoogleGenerativeAI(
            model="gemini-3.8-flash",
            temperature=0.1,  # Low temperature to prevent hallucinations
            max_tokens=500    # Keep responses concise and token usage low
        )
    except Exception:
        return None

def generate_explanation(live_json_data: dict, scientific_context: str, user_question: str) -> str:
    """
    Generates an explanation using the Gemini model, grounding it in the provided live data and context.
    """
    if not HAS_LANGCHAIN or prompt is None:
        return f"AquaWatch Analysis for {live_json_data.get('water_body', 'Water Body')}: Indicators (NDWI: {live_json_data.get('indicators',{}).get('ndwi')}, NDTI: {live_json_data.get('indicators',{}).get('ndti')}, NDCI: {live_json_data.get('indicators',{}).get('ndci')}). Scientific context: {scientific_context}"

    try:
        llm = _get_llm()
        if llm is None:
            raise ValueError("LLM initialization failed or API key missing")
        chain = prompt | llm | StrOutputParser()
        response = chain.invoke({
            "live_data": str(live_json_data),
            "context": scientific_context,
            "question": user_question
        })
        return response
    except Exception as e:
        return f"AquaWatch Analysis for {live_json_data.get('water_body', 'Water Body')}: Indicators (NDWI: {live_json_data.get('indicators',{}).get('ndwi')}, NDTI: {live_json_data.get('indicators',{}).get('ndti')}, NDCI: {live_json_data.get('indicators',{}).get('ndci')}). Scientific context: {scientific_context}"


# For testing locally if you run this script directly:
if __name__ == "__main__":
    if not os.getenv("GEMINI_API_KEY"):
        print("ERROR: GEMINI_API_KEY environment variable is not set. Please set it in your .env file.")
    else:
        # Example live data (this would come from our mock server in production)
        dummy_live_data = {
            "water_body": "Ambazari Lake",
            "baseline_comparison": {
                "indicators": {"ndci": 0.18, "turbidity_proxy": 45.5},
                "anomaly_status": "HIGH",
                "anomalous_area_pct": 18
            }
        }
        
        # Example scientific context (this would come from ChromaDB/Vector Store later)
        dummy_context = "NDCI (Normalized Difference Chlorophyll Index) deviations above 0.1 generally indicate elevated chlorophyll relative to baseline. High turbidity combined with high NDCI often means the optical condition is anomalous and warrants field verification."
        
        print("\n--- AquaWatch RAG Assistant (Terminal Chat) ---")
        print("Type 'exit' or 'quit' to stop.\n")
        
        while True:
            question = input("You: ")
            if question.lower() in ['exit', 'quit']:
                print("Goodbye!")
                break
                
            print("\nAquaWatch is thinking...")
            try:
                answer = generate_explanation(dummy_live_data, dummy_context, question)
                print(f"AquaWatch: {answer}\n")
            except Exception as e:
                print(f"Error connecting to Gemini: {e}\n")
