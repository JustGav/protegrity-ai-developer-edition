"""
browse_chromadb.py — Inspect the Banking Portal ChromaDB vector store.

Three modes:
  list      Print all document IDs and metadata
  show      Print the full stored document for one customer
  search    Run a semantic similarity search query
  rebuild   Rebuild the index from current KB files (fixes stale source paths)

Usage:
  python scripts/browse_chromadb.py list
  python scripts/browse_chromadb.py show CUST-100000
  python scripts/browse_chromadb.py search "credit card balance"
  python scripts/browse_chromadb.py search "credit card balance" --top 5
  python scripts/browse_chromadb.py rebuild
"""

from __future__ import annotations

import argparse
import os
import sys

# ── Resolve project root regardless of where the script is called from ──
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, ROOT_DIR)

CHROMA_DIR = os.path.join(ROOT_DIR, "chroma_db")
COLLECTION_NAME = "banking_kb"


def _get_collection():
    import chromadb
    client = chromadb.PersistentClient(path=CHROMA_DIR)
    return client.get_collection(COLLECTION_NAME)


# ── list ──────────────────────────────────────────────────────────────

def cmd_list():
    col = _get_collection()
    result = col.get(include=["metadatas"])
    ids = result["ids"]
    metas = result["metadatas"]

    print(f"\nCollection : {COLLECTION_NAME}")
    print(f"Documents  : {len(ids)}")
    print(f"DB path    : {CHROMA_DIR}")
    print()
    print(f"{'ID':<15}  {'Source file'}")
    print("-" * 80)
    for doc_id, meta in zip(ids, metas):
        src = meta.get("source", "—")
        # Flag stale paths
        stale = "" if ROOT_DIR in src else "  ⚠ stale path"
        print(f"{doc_id:<15}  {os.path.basename(src)}{stale}")
    print()


# ── show ──────────────────────────────────────────────────────────────

def cmd_show(customer_id: str):
    col = _get_collection()
    result = col.get(ids=[customer_id], include=["documents", "metadatas"])

    if not result["ids"]:
        print(f"ERROR: '{customer_id}' not found in the collection.")
        print("Run `python scripts/browse_chromadb.py list` to see valid IDs.")
        sys.exit(1)

    meta = result["metadatas"][0]
    doc = result["documents"][0]

    print(f"\n{'═' * 60}")
    print(f"  Customer : {customer_id}")
    print(f"  Source   : {meta.get('source', '—')}")
    print(f"{'═' * 60}\n")
    print(doc)
    print()


# ── search ────────────────────────────────────────────────────────────

def cmd_search(query: str, top_k: int = 3):
    col = _get_collection()
    results = col.query(
        query_texts=[query],
        n_results=min(top_k, col.count()),
        include=["documents", "metadatas", "distances"],
    )

    ids = results["ids"][0]
    docs = results["documents"][0]
    metas = results["metadatas"][0]
    dists = results["distances"][0]

    print(f"\nQuery  : \"{query}\"")
    print(f"Top-{top_k} results from '{COLLECTION_NAME}' ({col.count()} docs)\n")

    for rank, (doc_id, doc, meta, dist) in enumerate(zip(ids, docs, metas, dists), 1):
        similarity = 1 - dist  # cosine distance → similarity approximation
        print(f"{'─' * 60}")
        print(f"  Rank {rank}  |  {doc_id}  |  distance: {dist:.4f}  (similarity ≈ {similarity:.4f})")
        print(f"  Source : {os.path.basename(meta.get('source', '—'))}")
        print()
        # Print first 600 characters of the matching document
        preview = doc[:600]
        if len(doc) > 600:
            preview += f"\n  … ({len(doc) - 600} more chars)"
        print(preview)
        print()
    print(f"{'─' * 60}\n")


# ── rebuild ───────────────────────────────────────────────────────────

def cmd_rebuild():
    """Wipe and rebuild the index from the current KB files."""
    from common.rag_retriever import rebuild_index
    print(f"\nRebuilding ChromaDB index from:")
    print(f"  {os.path.join(ROOT_DIR, 'banking_data', 'knowledge_base')}\n")
    count = rebuild_index()
    print(f"Done — {count} documents indexed into '{COLLECTION_NAME}'.\n")
    print("Run `python scripts/browse_chromadb.py list` to verify.\n")


# ── CLI ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Browse the Banking Portal ChromaDB vector store.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="List all documents and metadata")

    p_show = sub.add_parser("show", help="Print full document for a customer")
    p_show.add_argument("customer_id", help="e.g. CUST-100000")

    p_search = sub.add_parser("search", help="Semantic similarity search")
    p_search.add_argument("query", help="Search query text")
    p_search.add_argument("--top", type=int, default=3, dest="top_k",
                          help="Number of results to return (default: 3)")

    sub.add_parser("rebuild", help="Rebuild index from current KB files")

    args = parser.parse_args()

    if args.command == "list":
        cmd_list()
    elif args.command == "show":
        cmd_show(args.customer_id)
    elif args.command == "search":
        cmd_search(args.query, args.top_k)
    elif args.command == "rebuild":
        cmd_rebuild()


if __name__ == "__main__":
    main()
