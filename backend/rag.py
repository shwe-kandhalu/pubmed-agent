import os
import chromadb
from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction

_DB_PATH = os.path.join(os.path.dirname(__file__), "chroma_db")
_client = chromadb.PersistentClient(path=_DB_PATH)
_ef = SentenceTransformerEmbeddingFunction(model_name="all-MiniLM-L6-v2")
_collection = _client.get_or_create_collection("literature", embedding_function=_ef)


def _chunk(text: str, size: int = 300, overlap: int = 50) -> list[str]:
    words = text.split()
    chunks, i = [], 0
    while i < len(words):
        chunk = " ".join(words[i : i + size])
        if len(chunk.strip()) > 40:
            chunks.append(chunk)
        i += size - overlap
    return chunks


def store_batch(ids: list[str], text: str) -> int:
    chunks = _chunk(text)
    if not chunks:
        return 0
    key = "_".join(ids[:5]).replace(":", "-")
    chunk_ids = [f"abs_{key}_{i}" for i in range(len(chunks))]
    metas = [{"ids": ",".join(ids), "type": "abstract"} for _ in chunks]
    _collection.upsert(documents=chunks, metadatas=metas, ids=chunk_ids)
    return len(chunks)


def store_paper(paper_id: str, text: str) -> int:
    chunks = _chunk(text)
    if not chunks:
        return 0
    key = paper_id.replace(":", "-")
    chunk_ids = [f"full_{key}_{i}" for i in range(len(chunks))]
    metas = [{"ids": paper_id, "type": "full_text"} for _ in chunks]
    _collection.upsert(documents=chunks, metadatas=metas, ids=chunk_ids)
    return len(chunks)


def retrieve(query: str, n_results: int = 6) -> list[dict]:
    total = _collection.count()
    if total == 0:
        return []
    results = _collection.query(
        query_texts=[query],
        n_results=min(n_results, total),
    )
    output = []
    for i, doc in enumerate(results["documents"][0]):
        meta = results["metadatas"][0][i]
        output.append({
            "ids": meta.get("ids", ""),
            "type": meta.get("type", ""),
            "text": doc,
        })
    return output


def count() -> int:
    return _collection.count()
