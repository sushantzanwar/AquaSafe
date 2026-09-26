"""
AquaWatch Vector Store
======================
ChromaDB-based local vector store for scientific water quality documents.
Uses Sentence Transformers embeddings (all-MiniLM-L6-v2) so no external API is needed.
"""
import os
import chromadb
from chromadb.utils import embedding_functions

# Store the ChromaDB database inside ai_assistant/rag/chroma_db/
_DB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "chroma_db")
_COLLECTION_NAME = "aquawatch_water_quality"

# Use the built-in default embedding function (uses ONNX sentence transformer, no API key needed)
_ef = embedding_functions.DefaultEmbeddingFunction()


def get_collection():
    """Return the ChromaDB collection, creating it if needed."""
    client = chromadb.PersistentClient(path=_DB_DIR)
    collection = client.get_or_create_collection(
        name=_COLLECTION_NAME,
        embedding_function=_ef,
        metadata={"hnsw:space": "cosine"}
    )
    return collection


def is_populated() -> bool:
    """Check if the collection has any documents."""
    try:
        col = get_collection()
        return col.count() > 0
    except Exception:
        return False


def search(query: str, n_results: int = 3) -> str:
    """
    Search the vector store for documents relevant to the query.
    Returns a single string with the top-n passages concatenated.
    Falls back to an empty string if the store is empty or an error occurs.
    """
    text, _ = search_with_metadata(query, n_results)
    return text


def search_with_metadata(query: str, n_results: int = 3) -> tuple:
    """
    Search the vector store and return (passages_text, sources_list).
    Each item in sources_list contains {'topic': str, 'citation': str}.
    """
    try:
        col = get_collection()
        if col.count() == 0:
            return "", []
        results = col.query(
            query_texts=[query],
            n_results=min(n_results, col.count()),
            include=["documents", "metadatas"]
        )
        passages = results.get("documents", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]
        parts = []
        sources = []
        for meta, passage in zip(metadatas, passages):
            topic = meta.get("topic", "Hydrology Publication")
            citation = meta.get("citation", f"AquaWatch Indexed Corpus · {topic}")
            sources.append({"topic": topic, "citation": citation})
            parts.append(f"[{topic}]\n{passage}")
        return "\n\n".join(parts), sources
    except Exception as e:
        return f"[Vector store unavailable: {e}]", []

