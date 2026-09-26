import os
from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI

load_dotenv()
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnablePassthrough
from langchain_core.output_parsers import StrOutputParser

# Make sure the user has their GEMINI_API_KEY set in their environment variables
# os.environ["GEMINI_API_KEY"] = "your_api_key_here"

# 1. Initialize the Gemini 1.5 Flash model
llm = ChatGoogleGenerativeAI(
    model="gemini-flash-latest",
    temperature=0.1, # Low temperature to prevent hallucinations
    max_tokens=500   # Keep responses concise and token usage low
)

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

prompt = ChatPromptTemplate.from_template(PROMPT_TEMPLATE)

def generate_explanation(live_json_data: dict, scientific_context: str, user_question: str) -> str:
    """
    Generates an explanation using the Gemini model, grounding it in the provided live data and context.
    """
    
    # We create a simple chain: Prompt -> LLM -> String Output
    chain = prompt | llm | StrOutputParser()
    
    # Execute the chain
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
