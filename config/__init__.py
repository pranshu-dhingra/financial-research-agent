"""Configuration module for financial-research-agent."""

from .settings import *  # noqa

__all__ = [
    "MODEL_ID",
    "REGION",
    "CHUNK_SIZE",
    "CHUNK_OVERLAP",
    "MAX_PAGES",
    "MAX_CHUNKS",
    "LLAMA_MAX_GEN",
    "CLAUDE_MAX_TOKENS",
    "SAVE_MEMORY",
    "MAX_MEMORY_TO_LOAD",
    "DEBUG",
    "ENABLE_TOOL_PLANNER",
    "USE_ORCHESTRATOR",
    "MEMORY_DIR",
]
