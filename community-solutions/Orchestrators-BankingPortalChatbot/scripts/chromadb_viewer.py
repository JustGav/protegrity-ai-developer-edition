"""
chromadb_viewer.py — Streamlit browser for the Banking Portal ChromaDB vector store.

Usage (from project root):
    streamlit run scripts/chromadb_viewer.py

Displays three tabs:
    Overview    — collection stats and metadata
    Browse      — per-customer document view
    Search      — semantic similarity search
"""

from __future__ import annotations

import os
import sys

# ── Resolve project root ──────────────────────────────────────────────
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR   = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, ROOT_DIR)

CHROMA_DIR      = os.path.join(ROOT_DIR, "chroma_db")
COLLECTION_NAME = "banking_kb"

import streamlit as st

st.set_page_config(
    page_title="ChromaDB Viewer — Banking Portal",
    page_icon="🗄️",
    layout="wide",
)


# ── ChromaDB connection (cached) ──────────────────────────────────────
@st.cache_resource(show_spinner="Connecting to ChromaDB …")
def get_collection():
    import chromadb
    client = chromadb.PersistentClient(path=CHROMA_DIR)
    try:
        return client.get_collection(COLLECTION_NAME)
    except Exception:
        st.error(
            f"Collection **{COLLECTION_NAME}** not found in `{CHROMA_DIR}`.\n\n"
            "Run the app once to build the index, or rebuild with:\n"
            "```\npython scripts/browse_chromadb.py rebuild\n```"
        )
        st.stop()


def collection_meta(col) -> dict:
    """Return count and all IDs/metadata without loading document bodies."""
    result = col.get(include=["metadatas"])
    return {
        "count":    len(result["ids"]),
        "ids":      result["ids"],
        "metadatas": result["metadatas"],
    }


# ── UI ────────────────────────────────────────────────────────────────

st.title("🗄️ ChromaDB Viewer — Banking Portal")
st.caption(f"Collection: **{COLLECTION_NAME}** · Path: `{CHROMA_DIR}`")
st.divider()

col = get_collection()
meta = collection_meta(col)

tab_overview, tab_browse, tab_search = st.tabs(["📊 Overview", "📄 Browse", "🔍 Search"])


# ═══════════════════════════════════════════════════════════════════════
# TAB 1 — OVERVIEW
# ═══════════════════════════════════════════════════════════════════════
with tab_overview:
    c1, c2, c3 = st.columns(3)
    c1.metric("Documents", meta["count"])
    c2.metric("Collection", COLLECTION_NAME)
    c3.metric("DB Path", os.path.basename(CHROMA_DIR))

    st.subheader("Indexed Documents")

    rows = []
    for doc_id, m in zip(meta["ids"], meta["metadatas"]):
        src  = m.get("source", "")
        stale = "⚠️ stale" if ROOT_DIR not in src else "✅ ok"
        rows.append({"Customer ID": doc_id, "Source File": os.path.basename(src), "Path Status": stale})

    import pandas as pd
    df = pd.DataFrame(rows)
    st.dataframe(df, use_container_width=True, hide_index=True)

    stale_count = sum(1 for r in rows if "⚠️" in r["Path Status"])
    if stale_count:
        st.warning(
            f"{stale_count} document(s) have stale source paths. "
            "Run `python scripts/browse_chromadb.py rebuild` to fix."
        )
    else:
        st.success("All source paths are current.")


# ═══════════════════════════════════════════════════════════════════════
# TAB 2 — BROWSE
# ═══════════════════════════════════════════════════════════════════════
with tab_browse:
    selected_id = st.selectbox(
        "Select a customer",
        options=sorted(meta["ids"]),
        index=0,
    )

    if selected_id:
        result = col.get(ids=[selected_id], include=["documents", "metadatas"])

        if result["ids"]:
            doc  = result["documents"][0]
            m    = result["metadatas"][0]

            col_l, col_r = st.columns([3, 1])
            with col_r:
                st.markdown("**Metadata**")
                st.json(m)
                st.metric("Characters", len(doc))
                st.metric("Lines", doc.count("\n") + 1)

            with col_l:
                st.markdown(f"**Document — {selected_id}**")
                st.code(doc, language=None)
        else:
            st.error(f"No document found for `{selected_id}`")


# ═══════════════════════════════════════════════════════════════════════
# TAB 3 — SEARCH
# ═══════════════════════════════════════════════════════════════════════
with tab_search:
    query     = st.text_input("Query", placeholder="e.g. credit card balance over limit")
    top_k     = st.slider("Top K results", min_value=1, max_value=min(15, meta["count"]), value=3)
    filter_id = st.selectbox(
        "Filter to customer (optional)",
        options=["— all customers —"] + sorted(meta["ids"]),
        index=0,
    )

    if st.button("Search", type="primary", disabled=not query.strip()):
        with st.spinner("Searching …"):
            where = (
                {"customer_id": filter_id}
                if filter_id != "— all customers —"
                else None
            )
            n_results = 1 if filter_id != "— all customers —" else top_k
            results = col.query(
                query_texts=[query],
                n_results=n_results,
                where=where,
                include=["documents", "metadatas", "distances"],
            )

        ids    = results["ids"][0]
        docs   = results["documents"][0]
        metas  = results["metadatas"][0]
        dists  = results["distances"][0]

        st.divider()
        st.markdown(f"**{len(ids)} result(s)** for *\"{query}\"*")

        for rank, (doc_id, doc, m, dist) in enumerate(zip(ids, docs, metas, dists), 1):
            similarity = max(0.0, 1 - dist)
            with st.expander(
                f"#{rank}  {doc_id}  —  distance: {dist:.4f}  (similarity ≈ {similarity:.4f})",
                expanded=(rank == 1),
            ):
                lcol, rcol = st.columns([3, 1])
                with rcol:
                    st.markdown("**Metadata**")
                    st.json(m)
                    st.metric("Distance", f"{dist:.4f}")
                    st.metric("Similarity ≈", f"{similarity:.4f}")
                with lcol:
                    # Show first 800 chars of matching doc
                    preview = doc[:800] + (f"\n… ({len(doc) - 800} more chars)" if len(doc) > 800 else "")
                    st.code(preview, language=None)
