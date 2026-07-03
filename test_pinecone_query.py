"""
Quick test: query Pinecone via the Conduit connector API.

Usage:
    python test_pinecone_query.py
"""
import json
import httpx

API = "http://localhost:8000"
CONN_ID = "pinecone-1"
INDEX_NAME = "semantic-reader-index"
DIMENSION = 768
TOP_K = 3

# Build a dummy 768-dim vector (all 0.1) — replace with a real embedding for meaningful results
vector = [0.1] * DIMENSION

query_payload = json.dumps({
    "index_name": INDEX_NAME,
    "vector": vector,
    "top_k": TOP_K,
})

resp = httpx.post(
    f"{API}/api/connectors/query",
    json={"conn_id": CONN_ID, "query": query_payload},
    timeout=15,
)

print(f"Status: {resp.status_code}")
print(json.dumps(resp.json(), indent=2))
