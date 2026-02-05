"""LLM synthesis and prompt generation."""

import json
import boto3
from config import (
    MODEL_ID,
    REGION,
    LLAMA_MAX_GEN,
    CLAUDE_MAX_TOKENS,
    DEBUG,
)


# --- Parsing helpers ---

def _parse_generation(raw_str):
    """Extract plain text from Bedrock response. Contract: top-level {"generation": "..."}."""
    if not raw_str:
        return ""
    try:
        parsed = json.loads(raw_str)
        if isinstance(parsed, dict) and "generation" in parsed:
            gen = parsed["generation"]
            return str(gen) if gen else ""  # Do not strip - preserve leading/trailing spaces
    except json.JSONDecodeError:
        pass
    return ""


def _append_stream_piece(final_text, piece):
    """
    Append a streaming piece to accumulated text. Insert a space when joining
    two word boundaries that Bedrock token-by-token streaming may have split
    without a space. Conservative: only when second piece starts with uppercase
    (new word) or first ends with sentence punctuation, to avoid splitting
    subwords ("invigorate") or acronyms ("MSMEs").
    """
    if not piece:
        return final_text
    if not final_text:
        return piece
    last = final_text[-1]
    first = piece[0]
    attach_punct = ".,!?;:)\"'"
    need_space = (
        not last.isspace() and last not in attach_punct and
        not first.isspace() and first not in attach_punct and
        (first.isupper() or last in ".!?")
    )
    return final_text + (" " if need_space else "") + piece


# --- Request preparation ---

def _prepare_request(prompt, model_id=None):
    """Prepare request body based on model type."""
    if model_id is None:
        model_id = MODEL_ID
    
    if "llama" in model_id.lower():
        return {"prompt": prompt, "max_gen_len": LLAMA_MAX_GEN, "temperature": 0.2, "top_p": 0.95}
    if "claude" in model_id.lower():
        return {"prompt": prompt, "max_tokens_to_sample": CLAUDE_MAX_TOKENS}
    return {"prompt": prompt}


# --- Bedrock invoke ---

def call_bedrock(prompt, model_id=None, region=None):
    """Synchronous Bedrock call. Returns plain text only."""
    if model_id is None:
        model_id = MODEL_ID
    if region is None:
        region = REGION
    
    client = boto3.client("bedrock-runtime", region_name=region)
    response = client.invoke_model(
        modelId=model_id,
        contentType="application/json",
        accept="application/json",
        body=json.dumps(_prepare_request(prompt, model_id=model_id)),
    )
    raw = response["body"].read().decode("utf-8")
    return _parse_generation(raw)


def call_bedrock_stream(prompt, model_id=None, region=None):
    """Streaming Bedrock call. Contract: event["chunk"]["bytes"] -> UTF-8 JSON with generation."""
    if model_id is None:
        model_id = MODEL_ID
    if region is None:
        region = REGION
    
    client = boto3.client("bedrock-runtime", region_name=region)
    if not hasattr(client, "invoke_model_with_response_stream"):
        return call_bedrock(prompt, model_id=model_id, region=region)
    response = client.invoke_model_with_response_stream(
        modelId=model_id,
        contentType="application/json",
        accept="application/json",
        body=json.dumps(_prepare_request(prompt, model_id=model_id)),
    )
    final_text = ""
    for event in response.get("body", []):
        try:
            chunk = event.get("chunk", {})
            raw_bytes = chunk.get("bytes")
            if raw_bytes is None:
                continue
            decoded = raw_bytes.decode("utf-8") if isinstance(raw_bytes, bytes) else str(raw_bytes)
            piece = _parse_generation(decoded)
            if piece:
                print(piece, end="", flush=True)
                final_text = _append_stream_piece(final_text, piece)
        except Exception as e:
            if DEBUG:
                print(f"[DEBUG] stream event error: {e}")
    print()
    return final_text.strip()


def call_bedrock_stream_gen(prompt, model_id=None, region=None):
    """
    Generator: yields token pieces from Bedrock streaming.
    Does not print to stdout (for Streamlit/UI consumption).
    Yields: str (each token piece)
    """
    if model_id is None:
        model_id = MODEL_ID
    if region is None:
        region = REGION
    
    client = boto3.client("bedrock-runtime", region_name=region)
    if not hasattr(client, "invoke_model_with_response_stream"):
        full = call_bedrock(prompt, model_id=model_id, region=region)
        if full:
            yield full
        return
    response = client.invoke_model_with_response_stream(
        modelId=model_id,
        contentType="application/json",
        accept="application/json",
        body=json.dumps(_prepare_request(prompt, model_id=model_id)),
    )
    for event in response.get("body", []):
        try:
            chunk = event.get("chunk", {})
            raw_bytes = chunk.get("bytes")
            if raw_bytes is None:
                continue
            decoded = raw_bytes.decode("utf-8") if isinstance(raw_bytes, bytes) else str(raw_bytes)
            piece = _parse_generation(decoded)
            if piece:
                yield piece
        except Exception as e:
            if DEBUG:
                print(f"[DEBUG] stream event error: {e}")


# --- Prompts ---

def make_chunk_prompt(chunk, question, idx, total):
    """Generate prompt for analyzing a single chunk."""
    return (
        "<|begin_of_text|><|start_header_id|>user<|end_header_id|>\n\n"
        "You are an expert analyst. Answer the question using ONLY the text in this chunk.\n\n"
        f"CHUNK {idx}/{total}:\n{chunk}\n\nQUESTION:\n{question}\n\n"
        "INSTRUCTIONS:\n"
        "- If the chunk does not contain information that answers the question, reply exactly: NOT RELEVANT\n"
        "- Otherwise: give a short partial answer (1-3 sentences) and one-line rationale.\n"
        "<|eot_id|><|start_header_id|>assistant<|end_header_id|>"
    )


def make_synthesis_prompt(partials, question, prior_memory_text=None, external_context=None, external_provenance=None):
    """Generate prompt for synthesizing partial answers into final answer."""
    joined = "\n\n".join(f"PARTIAL {i+1}: {p}" for i, p in enumerate(partials))
    mem = f"PAST INTERACTIONS:\n{prior_memory_text}\n\n" if prior_memory_text else ""
    ext = ""
    if external_context:
        ext = f"EXTERNAL CONTEXT (live data):\n{external_context}\n\n"
        if external_provenance:
            urls = [p.get("url", "") for p in external_provenance if p.get("url")]
            if urls:
                ext += f"EXTERNAL SOURCES: {', '.join(urls)}\n\n"
    return (
        "<|begin_of_text|><|start_header_id|>user<|end_header_id|>\n\n"
        "You are a senior researcher combining partial answers into one clear answer.\n\n"
        f"{mem}{ext}PARTIAL ANSWERS:\n{joined}\n\n"
        "INSTRUCTIONS:\n"
        "- Merge into one final answer. If partials disagree, explain uncertainty.\n"
        "- If none contain an answer, say 'Not found in document'.\n"
        "- Respect any length or format requested in the question (e.g. 'in 3 lines', 'briefly').\n\n"
        f"FINAL QUESTION:\n{question}\n\nFINAL ANSWER:\n"
        "<|eot_id|><|start_header_id|>assistant<|end_header_id|>"
    )


def make_partial_completion_synthesis_prompt(internal_facts, external_facts, question, prior_memory_text=None):
    """Prompt for merging internal facts with external completion facts."""
    int_facts = "\n".join(internal_facts) if internal_facts else ""
    ext_facts = "\n".join(external_facts) if external_facts else ""
    mem = f"PAST INTERACTIONS:\n{prior_memory_text}\n\n" if prior_memory_text else ""
    return (
        "<|begin_of_text|><|start_header_id|>user<|end_header_id|>\n\n"
        "You are a senior researcher completing a partial answer using internal and external facts.\n\n"
        f"{mem}INTERNAL FACTS:\n{int_facts}\n\nEXTERNAL FACTS (COMPLETION):\n{ext_facts}\n\n"
        "INSTRUCTIONS:\n"
        "- Complete the answer using internal facts first.\n"
        "- Use external facts only for missing fields.\n"
        "- Do NOT hallucinate.\n"
        "- Merge into one clear, complete answer.\n\n"
        f"FINAL QUESTION:\n{question}\n\nFINAL ANSWER:\n"
        "<|eot_id|><|start_header_id|>assistant<|end_header_id|>"
    )


def is_answer_incomplete(query, internal_facts, answer_text):
    """
    Returns True if key entities or attributes in query
    are not covered by internal_facts.
    """
    import re
    
    if DEBUG:
        print(f"[DEBUG] is_answer_incomplete called with query: {query[:50]}..., answer: {answer_text[:50]}...")
    
    query_lower = query.lower()
    answer_lower = answer_text.lower()
    
    # Heuristics for incompleteness
    comparison_keywords = ["compare", "versus", "vs", "and", "both", "difference", "how does"]
    if any(kw in query_lower for kw in comparison_keywords):
        # Check if query has multiple entities
        # Simple: if "and" or "vs" and answer doesn't mention both parts
        entities = re.findall(r'\b[A-Z][a-z]+\b|\b\d+\b', query)  # Proper nouns or numbers
        if len(entities) > 1:
            # Check if answer covers all entities
            covered = sum(1 for e in entities if e.lower() in answer_lower)
            if covered < len(entities) * 0.5:  # Less than half covered
                return True
    
    # Check for important terms missing
    important_terms = ["market cap", "revenue", "profit", "assets", "liabilities", "price", "value"]
    query_terms = [t for t in important_terms if t in query_lower]
    if query_terms:
        # If answer indicates information not found for key terms
        if "not found" in answer_lower and any(t in answer_lower for t in query_terms):
            if DEBUG:
                print(f"[DEBUG] is_answer_incomplete: answer indicates missing info for {query_terms}")
            return True
        missing = [t for t in query_terms if t not in answer_lower]
        if missing:
            if DEBUG:
                print(f"[DEBUG] is_answer_incomplete: missing important terms {missing}")
            return True
    
    return False


def extract_missing_slots(query, internal_facts):
    """
    Extract key fields from query and return which are not found in internal_facts.
    Example: query: market cap vs revenue, internal_facts: revenue only → missing: ["market capitalization"]
    """
    import re
    
    query_lower = query.lower()
    facts_text = "\n".join(internal_facts).lower() if internal_facts else ""
    
    # Common financial terms
    financial_terms = {
        "market cap": ["market capitalization", "market cap", "market value"],
        "revenue": ["revenue", "sales", "income"],
        "profit": ["profit", "earnings", "net income"],
        "assets": ["assets", "total assets"],
        "liabilities": ["liabilities"],
        "price": ["price", "stock price", "share price"],
        "cap": ["capital", "capitalization"],
        "rate": ["rate", "interest rate"],
        "ratio": ["ratio", "ratios"],
    }
    
    missing = []
    for term, synonyms in financial_terms.items():
        if term in query_lower:
            if not any(syn in facts_text for syn in synonyms):
                missing.append(term)
    
    # Extract named entities (companies, etc.)
    entities = re.findall(r'\b[A-Z][a-z]+\b', query)
    for entity in entities:
        if entity.lower() not in facts_text:
            missing.append(entity)
    
    return missing
