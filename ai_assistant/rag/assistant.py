import os
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain.prompts import ChatPromptTemplate
from langchain.schema.runnable import RunnablePassthrough
from langchain.schema.output_parser import StrOutputParser

# Make sure the user has their GEMINI_API_KEY set in their environment variables
# os.environ["GEMINI_API_KEY"] = "your_api_key_here"

# 1. Initialize the Gemini 1.5 Flash model
llm = ChatGoogleGenerativeAI(
    model="gemini-1.5-flash",
    temperature=0.1, # Low temperature to prevent hallucinations
    max_tokens=500   # Keep responses concise and token usage low
)

# 2. Create a strict prompt template to force the model to ground its answers
PROMPT_TEMPLATE = """
You are AquaWatch, a scientific AI assistant designed to explain remote-sensing water anomaly data. 
Your goal is to explain WHY a water body was flagged by our system.

You will be provided with:
1. LIVE DATA: The real-time JSON output from our detection models.
2. SCIENTIFIC CONTEXT: Extracts from scientific papers explaining indices like NDCI, NDTI, etc.

CRITICAL INSTRUCTIONS:
- ONLY use the provided live data and scientific context to answer. 
- Do NOT hallucinate or invent numbers. 
- If the context does not contain the answer, say "I do not have enough scientific context to explain this."
- Keep your explanation clear, professional, and accessible to a non-scientist (like a local official).

---------------------
LIVE DATA:
{live_data}
---------------------
SCIENTIFIC CONTEXT:
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
    # Example live data (this would come from our mock server)
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
    
    question = "Why was Ambazari Lake flagged as a high anomaly?"
    
    print("Testing Gemini RAG Pipeline (requires GEMINI_API_KEY)...\n")
    try:
        if not os.getenv("GEMINI_API_KEY"):
            print("ERROR: GEMINI_API_KEY environment variable is not set. Please set it to run the test.")
        else:
            answer = generate_explanation(dummy_live_data, dummy_context, question)
            print(answer)
    except Exception as e:
        print(f"Error connecting to Gemini: {e}")
