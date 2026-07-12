import chromadb
from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction

# In-memory, not persisted to disk: every chunk is scoped to a run_id and never queried
# again once that run's response finishes, so there's nothing worth persisting across restarts.
_client = chromadb.EphemeralClient()
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


def store_batch(ids: list[str], text: str, run_id: str) -> int:
    chunks = _chunk(text)
    if not chunks:
        return 0
    key = "_".join(ids[:5]).replace(":", "-")
    chunk_ids = [f"abs_{run_id}_{key}_{i}" for i in range(len(chunks))]
    metas = [{"ids": ",".join(ids), "type": "abstract", "run_id": run_id} for _ in chunks]
    _collection.upsert(documents=chunks, metadatas=metas, ids=chunk_ids)
    return len(chunks)


def store_paper(paper_id: str, text: str, run_id: str) -> int:
    chunks = _chunk(text)
    if not chunks:
        return 0
    key = paper_id.replace(":", "-")
    chunk_ids = [f"full_{run_id}_{key}_{i}" for i in range(len(chunks))]
    metas = [{"ids": paper_id, "type": "full_text", "run_id": run_id} for _ in chunks]
    _collection.upsert(documents=chunks, metadatas=metas, ids=chunk_ids)
    return len(chunks)


def retrieve(query: str, run_id: str, n_results: int = 6) -> list[dict]:
    # Over-fetch so that, after dropping abstract chunks superseded by full text below,
    # we still have enough candidates left to fill n_results.
    pool_size = max(n_results * 3, 15)
    results = _collection.query(
        query_texts=[query],
        n_results=pool_size,
        where={"run_id": run_id},
    )
    candidates = []
    for i, doc in enumerate(results["documents"][0]):
        meta = results["metadatas"][0][i]
        candidates.append({
            "ids": meta.get("ids", ""),
            "type": meta.get("type", ""),
            "text": doc,
        })

    full_text_papers = {c["ids"] for c in candidates if c["type"] == "full_text" and c["ids"]}

    def superseded(c: dict) -> bool:
        if c["type"] != "abstract":
            return False
        covered = {pid.strip() for pid in c["ids"].split(",")}
        return bool(covered & full_text_papers)

    return [c for c in candidates if not superseded(c)][:n_results]


def count() -> int:
    return _collection.count()
