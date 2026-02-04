#!/usr/bin/env python3
"""
app.py - BFSI Research Assistant Interface (Streamlit)

Research dashboard: upload PDFs, ask questions, view provenance and confidence.
"""

import os
import sys
from pathlib import Path
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))

import streamlit as st

UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)
DEBUG = os.environ.get("DEBUG", "0") == "1"
GLOBAL_UI_TIMEOUT = 30  # seconds


def _ensure_imports():
    """Import core functions from local_pdf_qa."""
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


def list_pdf_memories():
    """List all PDFs and their memory counts."""
    from local_pdf_qa import list_all_memory_files, load_memory_for_pdf, _pdf_memory_filename
    
    memory_info = {}
    for pdf_path in list_uploaded_pdfs():
        memory = load_memory_for_pdf(str(pdf_path))
        count = len(memory)
        memory_info[str(pdf_path)] = count
    return memory_info


def query_offline_memory(question, pdf_path):
    """Search offline memory for similar questions."""
    from local_pdf_qa import load_memory_for_pdf, find_relevant_memories_semantic
    
    memory = load_memory_for_pdf(str(pdf_path))
    if not memory:
        return None
    relevant = find_relevant_memories_semantic(question, memory, top_k=1)
    if relevant and relevant[0].get("_similarity", 0) > 0.7:
        return relevant[0]
    return None


def main():
    """Main Streamlit application."""
    st.set_page_config(page_title="BFSI Research Assistant", layout="wide")
    st.title("BFSI Research Assistant")

    # Initialize session state
    if "offline_mode" not in st.session_state:
        st.session_state["offline_mode"] = False

    pdfs = list_uploaded_pdfs()
    pdf_options = [str(p) for p in pdfs]
    if not pdf_options:
        pdf_options = ["(No PDFs available)"]

    with st.sidebar:
        st.header("📚 Document Manager")
        
        # Available PDFs and Memory counts
        st.subheader("Available PDFs")
        memory_info = list_pdf_memories()
        for pdf_path, count in memory_info.items():
            st.caption(f"📄 {Path(pdf_path).name}: {count} Q&As")
        
        st.divider()
        
        # Upload new PDF
        uploaded = st.file_uploader("Upload PDF", type=["pdf"])
        if uploaded:
            dest = UPLOAD_DIR / uploaded.name
            with open(dest, "wb") as f:
                f.write(uploaded.getvalue())
            try:
                _, _, precompute_pdf_embeddings = _ensure_imports()
                precompute_pdf_embeddings(str(dest))
            except Exception as e:
                st.error(f"Precompute failed: {e}")
            st.success(f"Uploaded: {uploaded.name}")
            st.rerun()

        st.divider()

        # Select PDF
        selected = st.selectbox("Select PDF", pdf_options)
        
        # Offline/Online mode toggle
        st.subheader("⚙️ Mode")
        st.session_state["offline_mode"] = st.checkbox(
            "Offline mode (memory only, no LLM/API calls)",
            value=st.session_state["offline_mode"]
        )
        
        if st.session_state["offline_mode"]:
            st.info("💡 Offline: Instant results from memory. No external API calls.")
        else:
            st.info("🌐 Online: Live LLM analysis with SerpAPI augmentation.")

        st.divider()

        # Memory management
        if selected and selected != "(No PDFs available)":
            st.subheader("Memory Tools")
            if st.button("📖 View Full Memory"):
                st.session_state["show_memory"] = selected
            if st.button("🗑️ Clear Memory"):
                st.session_state["confirm_clear"] = selected

    # Clear memory confirmation
    if st.session_state.get("confirm_clear"):
        pdf_path = st.session_state["confirm_clear"]
        st.sidebar.warning(f"Clear memory for {os.path.basename(pdf_path)}?")
        col1, col2 = st.sidebar.columns(2)
        if col1.button("Yes, Clear", key="clear_yes"):
            try:
                _, clear_memory_for_pdf, _ = _ensure_imports()
                clear_memory_for_pdf(pdf_path)
                st.sidebar.success("Memory cleared.")
            except Exception as e:
                st.sidebar.error(str(e))
            st.session_state.pop("confirm_clear", None)
            st.rerun()
        if col2.button("Cancel", key="clear_cancel"):
            st.session_state.pop("confirm_clear", None)
            st.rerun()

    # Main query interface
    st.subheader("🔍 Query")
    question = st.text_input("Your question...", placeholder="Enter research question...")
    ask_clicked = st.button("Ask", type="primary")

    if ask_clicked and question and selected and selected != "(No PDFs available)":
        pdf_path = selected

        if st.session_state["offline_mode"]:
            # Offline mode: search memory instantly
            st.subheader("Answer (from Memory)")
            result = query_offline_memory(question, pdf_path)
            if result:
                st.write(result.get("answer", ""))
                st.caption(f"✓ From memory | Confidence: {result.get('confidence', 0):.2f}")
            else:
                st.info("Not found in memory. No LLM calls in offline mode.")
        else:
            # Online mode: use orchestrator with streaming
            with st.spinner("Analyzing..."):
                try:
                    from orchestrator import run_workflow
                    start_time = time.time()
                    result = run_workflow(question, pdf_path, use_streaming=False)
                    elapsed = time.time() - start_time
                    
                    if elapsed > GLOBAL_UI_TIMEOUT:
                        st.warning(f"⏱️ Query took {elapsed:.0f}s (timeout: {GLOBAL_UI_TIMEOUT}s)")
                    
                    if result and result.get("answer"):
                        st.subheader("Answer")
                        st.write(result["answer"])
                        
                        st.subheader("Sources")
                        prov = result.get("provenance", [])
                        if prov:
                            rows = []
                            for p in prov:
                                rows.append({
                                    "Type": p.get("type", "").upper(),
                                    "Source": os.path.basename(p.get("source", ""))[:40],
                                    "Snippet": (p.get("text", "") or "")[:100] + "...",
                                })
                            st.dataframe(rows, use_container_width='stretch')
                        else:
                            st.write("No sources.")
                        
                        st.subheader("Confidence")
                        conf = result.get("confidence", 0.0)
                        if conf > 0.8:
                            label = "🟢 High"
                        elif conf >= 0.5:
                            label = "🟡 Medium"
                        else:
                            label = "🔴 Low"
                        st.write(f"**{conf:.2f}** ({label})")
                        
                        if result.get("flags"):
                            st.caption(f"Flags: {', '.join(result.get('flags', []))}")
                    else:
                        st.error("No answer generated.")
                except Exception as e:
                    st.error(f"Error: {e}")
                    if DEBUG:
                        import traceback
                        st.error(traceback.format_exc())

    # Memory viewer
    if st.session_state.get("show_memory"):
        pdf_path = st.session_state["show_memory"]
        st.subheader(f"📖 Memory: {os.path.basename(pdf_path)}")
        load_memory_for_pdf, _, _ = _ensure_imports()
        memory = load_memory_for_pdf(pdf_path)
        
        if not memory:
            st.write("No stored Q&As.")
        else:
            st.write(f"**Total Q&As: {len(memory)}**")
            st.divider()
            
            # Memory preview
            rows = []
            for m in memory:
                rows.append({
                    "Q": m.get("question", "")[:60],
                    "Confidence": f"{m.get('confidence', 0):.2f}",
                    "Time": m.get("timestamp", "")[:10],
                })
            st.dataframe(rows, use_container_width='stretch')
            
            st.divider()
            
            # Expandable details
            for i, m in enumerate(memory):
                with st.expander(f"Q: {m.get('question', '')[:60]}..."):
                    st.write("**Answer:**")
                    st.write(m.get("answer", ""))
                    st.caption(f"Confidence: {m.get('confidence', 0):.2f} | {m.get('timestamp', '')}")
                    if m.get("provenance"):
                        st.write("**Sources:**")
                        for p in m["provenance"]:
                            st.write(f"- {p.get('type', '').upper()}: {p.get('source', '')}")
        
        if st.button("Close Memory View"):
            st.session_state.pop("show_memory", None)
            st.rerun()


if __name__ == "__main__":
    main()
