"""Per-PDF semantic memory management."""

import os
import json
import hashlib
from pathlib import Path
from config import MEMORY_DIR, DEBUG


def _pdf_memory_filename(pdf_path: str) -> str:
    """Deterministic memory filename: memories/memory_<basename>_<hash>.json"""
    abs_path = os.path.abspath(pdf_path)
    h = hashlib.sha256(abs_path.encode("utf-8")).hexdigest()[:10]
    base = os.path.basename(abs_path)
    return str(MEMORY_DIR / f"memory_{base}_{h}.json")


def load_memory_for_pdf(pdf_path: str):
    """Load memory list for this PDF. Returns [] if file does not exist."""
    path = _pdf_memory_filename(pdf_path)
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception as e:
        if DEBUG:
            print(f"[DEBUG] load_memory_for_pdf failed: {e}")
        return []


def append_memory_for_pdf(entry, pdf_path: str):
    """Append entry to this PDF's memory file. Uses atomic write."""
    path = _pdf_memory_filename(pdf_path)
    mem = load_memory_for_pdf(pdf_path)
    mem.append(entry)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(mem, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def list_all_memory_files():
    """List paths of all memory files in MEMORY_DIR."""
    if not MEMORY_DIR.exists():
        return []
    return sorted(str(p) for p in MEMORY_DIR.glob("memory_*.json"))


def clear_memory_for_pdf(pdf_path: str):
    """Clear memory for this PDF. Overwrites with empty list."""
    path = _pdf_memory_filename(pdf_path)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump([], f, indent=2)
    os.replace(tmp, path)
