#!/usr/bin/env python3
"""
app.py - BFSI Research Assistant Interface (Streamlit)

Research dashboard: upload PDFs, ask questions, view provenance and confidence.
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import streamlit as st

UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)
DEBUG = os.environ.get("DEBUG", "0") == "1"


def _ensure_imports():
    from local_pdf_qa import (
        load_memory_for_pdf,
        clear_memory_for_pdf,
        precompute_pdf_embeddings,
    )
    return load_memory_for_pdf, clear_memory_for_pdf, precompute_pdf_embeddings


def list_uploaded_pdfs():
    """List PDFs in uploads directory and project root."""
    paths = []
    if UPLOAD_DIR.exists():
        paths.extend(UPLOAD_DIR.glob("*.pdf"))
    root = Path(__file__).parent
    paths.extend(p for p in root.glob("*.pdf") if p not in paths)
    return sorted(set(paths), key=lambda p: p.name)


def main():
    st.set_page_config(page_title="BFSI Research Assistant", layout="wide")
    st.title("BFSI Research Assistant")

    load_memory_for_pdf, clear_memory_for_pdf, precompute_pdf_embeddings = _ensure_imports()

    pdfs = list_uploaded_pdfs()
    pdf_options = [str(p) for p in pdfs]
    if not pdf_options:
        pdf_options = ["(No PDFs available)"]

    with st.sidebar:
        st.header("Document Manager")
        uploaded = st.file_uploader("Upload PDF", type=["pdf"])
        if uploaded:
            dest = UPLOAD_DIR / uploaded.name
            with open(dest, "wb") as f:
                f.write(uploaded.getvalue())
            try:
                precompute_pdf_embeddings(str(dest))
            except Exception as e:
                st.error(f"Precompute failed: {e}")
            st.success(f"Uploaded: {uploaded.name}")
            st.rerun()

        selected = st.selectbox("Select PDF", pdf_options)
        if selected and selected != "(No PDFs available)":
            if st.button("Show Memory for Selected PDF"):
                st.session_state["show_memory"] = selected
            if st.button("Clear Memory for Selected PDF"):
                st.session_state["confirm_clear"] = selected

    if st.session_state.get("confirm_clear"):
        pdf_path = st.session_state["confirm_clear"]
        st.sidebar.warning(f"Clear memory for {os.path.basename(pdf_path)}?")
        col1, col2 = st.sidebar.columns(2)
        if col1.button("Yes, Clear", key="clear_yes"):
            try:
                clear_memory_for_pdf(pdf_path)
                st.sidebar.success("Memory cleared.")
            except Exception as e:
                st.sidebar.error(str(e))
            st.session_state.pop("confirm_clear", None)
            st.rerun()
        if col2.button("Cancel", key="clear_cancel"):
            st.session_state.pop("confirm_clear", None)
            st.rerun()

    question = st.text_input("Question", placeholder="Enter research question...")
    live_mode = st.checkbox("Run live analysis (may incur model cost)", value=True)
    ask_clicked = st.button("Ask")

    if ask_clicked and question and selected and selected != "(No PDFs available)":
        pdf_path = selected
        if live_mode:
            with st.spinner("Running orchestrator..."):
                try:
                    from orchestrator import run_workflow
                    result = run_workflow(question, pdf_path, use_streaming=False)
                except Exception as e:
                    st.error(f"Error: {e}")
                    result = None
            if result:
                st.subheader("Answer")
                st.write(result["answer"])
                st.subheader("Sources")
                prov = result.get("provenance", [])
                if prov:
                    rows = []
                    for p in prov:
                        rows.append({
                            "type": p.get("type", ""),
                            "source": p.get("source", ""),
                            "category": p.get("category", ""),
                            "snippet": (p.get("text", "") or "")[:200] + ("..." if len(p.get("text", "") or "") > 200 else ""),
                        })
                    st.dataframe(rows, use_container_width=True)
                else:
                    st.write("No sources.")
                st.subheader("Confidence")
                conf = result.get("confidence", 0.0)
                if conf > 0.8:
                    label = "High"
                elif conf >= 0.5:
                    label = "Medium"
                else:
                    label = "Low"
                st.write(f"{conf:.2f} ({label})")
                if result.get("flags"):
                    st.caption(f"Flags: {', '.join(result['flags'])}")
                if DEBUG and result.get("trace"):
                    with st.expander("Debug: Orchestrator Trace"):
                        st.json(result["trace"])
        else:
            memory = load_memory_for_pdf(pdf_path)
            if not memory:
                st.info("No stored Q&As for this PDF. Run live analysis to build memory.")
            else:
                st.subheader("Stored Q&As (Offline)")
                n = min(10, len(memory))
                for i, m in enumerate(reversed(memory[-n:])):
                    with st.expander(f"Q: {m.get('question', '')[:60]}..."):
                        st.write("**Answer:**", m.get("answer", ""))
                        st.caption(f"Confidence: {m.get('confidence', 0):.2f} | {m.get('timestamp', '')}")
                        if m.get("provenance"):
                            st.write("**Provenance:**")
                            for p in m["provenance"]:
                                st.write(f"- [{p.get('type')}] {p.get('source', '')[:80]}")

    if st.session_state.get("show_memory"):
        pdf_path = st.session_state["show_memory"]
        st.subheader(f"Memory: {os.path.basename(pdf_path)}")
        memory = load_memory_for_pdf(pdf_path)
        if not memory:
            st.write("No stored Q&As.")
        else:
            rows = []
            for m in memory:
                rows.append({
                    "question": m.get("question", "")[:80],
                    "answer": m.get("answer", "")[:80],
                    "confidence": m.get("confidence", 0),
                    "timestamp": m.get("timestamp", ""),
                })
            st.dataframe(rows, use_container_width=True)
            for m in memory:
                with st.expander(f"Q: {m.get('question', '')[:60]}..."):
                    st.write("**Answer:**", m.get("answer", ""))
                    st.caption(f"Confidence: {m.get('confidence', 0):.2f} | {m.get('timestamp', '')}")
                    if m.get("provenance"):
                        st.write("**Provenance:**")
                        for p in m["provenance"]:
                            st.write(f"- [{p.get('type')}] {p.get('source', '')[:80]}")
        if st.button("Close Memory View"):
            st.session_state.pop("show_memory", None)
            st.rerun()


if __name__ == "__main__":
    main()
