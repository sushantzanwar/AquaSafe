import os
from langchain_community.document_loaders import PyPDFLoader, DirectoryLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_chroma import Chroma

# Path configuration
KNOWLEDGE_BASE_DIR = os.path.join(os.path.dirname(__file__), "..", "knowledge_base")
CHROMA_DB_DIR = os.path.join(os.path.dirname(__file__), "..", "chroma_db")

def ingest_documents():
    """Reads PDFs from knowledge_base/, splits them, and saves to ChromaDB."""
    print(f"Checking for documents in {KNOWLEDGE_BASE_DIR}...")
    
    # Ensure the directory exists
    if not os.path.exists(KNOWLEDGE_BASE_DIR):
        print("Knowledge base folder not found. Creating one...")
        os.makedirs(KNOWLEDGE_BASE_DIR)
        print("Please drop your scientific PDFs into the knowledge_base folder and run this again.")
        return

    # Load all PDF files from the knowledge base directory
    loader = DirectoryLoader(KNOWLEDGE_BASE_DIR, glob="**/*.pdf", loader_cls=PyPDFLoader)
    documents = loader.load()

    if not documents:
        print("No PDFs found in the knowledge_base directory.")
        return

    print(f"Found {len(documents)} document pages. Splitting into chunks...")

    # Split documents into chunks so the LLM can digest them easily
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=1000, 
        chunk_overlap=200, 
        separators=["\n\n", "\n", " ", ""]
    )
    chunks = text_splitter.split_documents(documents)
    
    print(f"Created {len(chunks)} chunks. Generating embeddings and saving to ChromaDB...")

    # Use Gemini's embedding model to convert text chunks into searchable vectors
    # (Requires GEMINI_API_KEY environment variable)
    embeddings = GoogleGenerativeAIEmbeddings(model="models/embedding-001")

    # Save to Chroma DB locally
    vectorstore = Chroma.from_documents(
        documents=chunks, 
        embedding=embeddings, 
        persist_directory=CHROMA_DB_DIR
    )
    
    print(f"Success! {len(chunks)} chunks ingested into {CHROMA_DB_DIR}.")

if __name__ == "__main__":
    if not os.getenv("GEMINI_API_KEY"):
        print("ERROR: GEMINI_API_KEY environment variable is not set. Cannot generate embeddings.")
    else:
        ingest_documents()
