"""Global configuration and environment variables."""

import os
from pathlib import Path

# ============================================================
# Core Models (AWS Bedrock)
# ============================================================
MODEL_ID = os.environ.get("MODEL_ID", "us.meta.llama3-3-70b-instruct-v1:0")
REGION = os.environ.get("AWS_REGION", "us-east-1")

# ============================================================
# Embedding Model
# ============================================================
EMBEDDING_MODEL_ID = os.environ.get("EMBEDDING_MODEL_ID", "amazon.titan-embed-text-v1")

# ============================================================
# Chunking & PDF Processing
# ============================================================
CHUNK_SIZE = int(os.environ.get("CHUNK_SIZE", 1200))
CHUNK_OVERLAP = int(os.environ.get("CHUNK_OVERLAP", 200))
MAX_PAGES = int(os.environ.get("MAX_PAGES", 20))
MAX_CHUNKS = int(os.environ.get("MAX_CHUNKS", 60))

# ============================================================
# LLM Generation Limits
# ============================================================
LLAMA_MAX_GEN = int(os.environ.get("LLAMA_MAX_GEN", 800))
CLAUDE_MAX_TOKENS = int(os.environ.get("CLAUDE_MAX_TOKENS", 800))

# ============================================================
# Memory Management
# ============================================================
SAVE_MEMORY = os.environ.get("SAVE_MEMORY", "1") != "0"
MAX_MEMORY_TO_LOAD = int(os.environ.get("MAX_MEMORY_TO_LOAD", 5))
MEMORY_DIR = Path("memories")
MEMORY_DIR.mkdir(exist_ok=True)

# ============================================================
# Feature Flags & Debug Mode
# ============================================================
DEBUG = os.environ.get("DEBUG", "0") == "1"
ENABLE_TOOL_PLANNER = os.environ.get("ENABLE_TOOL_PLANNER", "0") == "1"
USE_ORCHESTRATOR = os.environ.get("USE_ORCHESTRATOR", "1") == "1"
