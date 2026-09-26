import os
from dotenv import load_dotenv

load_dotenv()

try:
    from langchain_google_genai import ChatGoogleGenerativeAI
    from langchain_core.prompts import ChatPromptTemplate
    from langchain_core.runnables import RunnablePassthrough
    from langchain_core.output_parsers import StrOutputParser
    
    llm = ChatGoogleGenerativeAI(
        model="gemini-flash-latest",
        temperature=0.1,
        max_tokens=500
    )
    HAS_LANGCHAIN = True
except Exception:
    HAS_LANGCHAIN = False
    llm = None


# 2. Create a strict prompt template to force the model to ground its answers
PROMPT_TEMPLATE = """
You are AquaWatch, a dual-purpose AI assistant.
1. When asked about specific water anomalies or satellite data, you are a strict scientific expert.
2. When asked general questions about water quality, health, or citizen science, you are a helpful and educational guide.

CRITICAL INSTRUCTIONS:
- SCENARIO A (System Anomaly): If the user asks why a specific lake was flagged, ONLY use the provided LIVE DATA and SCIENTIFIC CONTEXT to explain the exact reason. Do not invent numbers.
- SCENARIO B (Citizen Doubt): If the user asks a general question (e.g., "Is green water safe?", "What is turbidity?"), answer them helpfully using your general knowledge, even if it's not in the context.
- ALWAYS keep your explanation clear, professional, and accessible to a non-scientist (like a local official or a concerned citizen).

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

def generate_explanation(live_json_data: dict, scientific_context: str, user_question: str) -> str:
    """
    Generates an explanation using the Gemini model, grounding it in the provided live data and context.
    """
    if not HAS_LANGCHAIN or llm is None:
        return f"AquaWatch Analysis for {live_json_data.get('water_body', 'Water Body')}: Indicators (NDWI: {live_json_data.get('indicators',{}).get('ndwi')}, NDTI: {live_json_data.get('indicators',{}).get('ndti')}, NDCI: {live_json_data.get('indicators',{}).get('ndci')}). Scientific context: {scientific_context}"
    
    prompt = ChatPromptTemplate.from_template(PROMPT_TEMPLATE)
    chain = prompt | llm | StrOutputParser()
    
    response = chain.invoke({
        "live_data": str(live_json_data),
        "context": scientific_context,
        "question": user_question
    })
    
    return response


# For testing locally if you run this script directly:
if __name__ == "__main__":
    if not os.getenv("GEMINI_API_KEY"):
        print("ERROR: GEMINI_API_KEY environment variable is not set. Please set it in your .env file.")
    else:
        # Example live data (this would come from our mock server in production)
        dummy_live_data = {
            "water_body": "Ambazari Lake",
            "contamination_detection": {
                "indicators": {"ndci": 0.18, "turbidity": 45.5},
                "anomaly_status": "HIGH",
                "detected_contaminants": ["Algal Bloom"]
            }
        }
        
        # Example scientific context (this would come from ChromaDB/Vector Store later)
        dummy_context = "NDCI (Normalized Difference Chlorophyll Index) values above 0.1 generally indicate severe algal blooms. High turbidity combined with high NDCI often means the water is unsafe for consumption."
        
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
