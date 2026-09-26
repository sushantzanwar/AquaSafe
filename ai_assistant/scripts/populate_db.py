"""
populate_db.py
==============
One-time script to seed the ChromaDB vector store with
scientific water quality documents.

Run from the hackronyx root:
    .\.venv\Scripts\python ai_assistant\scripts\populate_db.py
"""
import sys
import os

# Make sure the ai_assistant packages are importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from ai_assistant.rag.vector_store import get_collection
from ai_assistant.knowledge_base.water_quality_docs import SCIENTIFIC_DOCUMENTS


def populate():
    print("Connecting to ChromaDB...")
    col = get_collection()

    existing_ids = set(col.get()["ids"])
    to_add_ids, to_add_docs, to_add_metas = [], [], []

    for doc in SCIENTIFIC_DOCUMENTS:
        if doc["id"] not in existing_ids:
            to_add_ids.append(doc["id"])
            to_add_docs.append(doc["text"])
            to_add_metas.append({"topic": doc["topic"]})

    if not to_add_ids:
        print("[OK] Already populated -- {} documents in store.".format(col.count()))
        return

    print("Embedding and inserting {} documents...".format(len(to_add_ids)))
    col.add(
        ids=to_add_ids,
        documents=to_add_docs,
        metadatas=to_add_metas
    )
    print("[OK] Done! Total documents in store: {}".format(col.count()))

    # Quick sanity check
    print("\nRunning test query: 'what does high NDCI mean?'")
    results = col.query(query_texts=["what does high NDCI mean?"], n_results=2)
    for doc in results["documents"][0]:
        print("  -> {}...".format(doc[:120]))


if __name__ == "__main__":
    populate()
