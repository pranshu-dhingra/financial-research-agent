"""Agent layer: orchestration, synthesis, retrieval, and memory."""

from .synthesizer import (
    call_bedrock,
    call_bedrock_stream,
    call_bedrock_stream_gen,
    make_chunk_prompt,
    make_synthesis_prompt,
    make_partial_completion_synthesis_prompt,
    is_answer_incomplete,
    extract_missing_slots,
)
from .retriever import (
    find_relevant_chunks,
    find_relevant_chunks_token,
    find_relevant_memories_semantic,
)
from .memory import (
    load_memory_for_pdf,
    append_memory_for_pdf,
    clear_memory_for_pdf,
    list_all_memory_files,
)

__all__ = [
    "call_bedrock",
    "call_bedrock_stream",
    "call_bedrock_stream_gen",
    "make_chunk_prompt",
    "make_synthesis_prompt",
    "make_partial_completion_synthesis_prompt",
    "is_answer_incomplete",
    "extract_missing_slots",
    "find_relevant_chunks",
    "find_relevant_chunks_token",
    "find_relevant_memories_semantic",
    "load_memory_for_pdf",
    "append_memory_for_pdf",
    "clear_memory_for_pdf",
    "list_all_memory_files",
]
