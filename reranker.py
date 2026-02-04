#!/usr/bin/env python3
"""
reranker.py - Preference-based Reranker for BFSI Answers

Generates multiple candidate answers and selects the most reliable one.
"""


VARIATIONS = [
    "Prefer concise, bullet-point style.",
    "Prefer detailed narrative with full sentences.",
    "Focus on key metrics and numbers.",
]


def generate_candidate_answers(
    query: str,
    internal_facts: list,
    external_facts: list,
    memory_facts: list,
    n: int = 3,
) -> list[str]:
    """
    Call synthesizer n times with different prompt variations.
    Returns list of candidate answer strings.
    """
    from orchestrator import synthesizer_agent

    candidates = []
    for i in range(n):
        var = VARIATIONS[i % len(VARIATIONS)] if i < len(VARIATIONS) else None
        synth = synthesizer_agent(
            internal_facts,
            external_facts,
            memory_facts,
            query,
            use_streaming=False,
            variation=var,
        )
        ans = synth.get("answer", "").strip()
        if ans and ans not in candidates:
            candidates.append(ans)
        elif ans:
            candidates.append(ans)
        if len(candidates) >= n:
            break
    if len(candidates) < n and candidates:
        while len(candidates) < n:
            candidates.append(candidates[0])
    return candidates[:n]


def rank_candidates(
    query: str,
    candidates: list[str],
    provenance: list | None = None,
    partials: list | None = None,
    external_snippets: list | None = None,
    verifier_fn=None,
    get_embedding_fn=None,
) -> str:
    """
    Rank candidates by verifier confidence + embedding similarity + length penalty.
    Returns best candidate.
    """
    if not candidates:
        return ""
    if len(candidates) == 1:
        return candidates[0]

    from verifier import verifier_agent

    provenance = provenance or []
    partials = partials or []
    external_snippets = external_snippets or []
    verifier_fn = verifier_fn or verifier_agent
    try:
        from local_pdf_qa import get_embedding
        get_embedding_fn = get_embedding_fn or get_embedding
    except ImportError:
        get_embedding_fn = None

    scored = []
    q_vec = get_embedding_fn(query) if get_embedding_fn else None
    max_len = max(len(c) for c in candidates) or 1

    for cand in candidates:
        ver = verifier_fn(cand, provenance, partials, external_snippets)
        conf = ver.get("confidence", 0.0)
        emb_sim = 0.5
        if q_vec and get_embedding_fn:
            c_vec = get_embedding_fn(cand)
            if c_vec:
                emb_sim = max(0, min(1, sum(a * b for a, b in zip(q_vec, c_vec))))
        length_penalty = min(1.0, len(cand) / max_len) if max_len else 1.0
        final_score = 0.5 * conf + 0.3 * emb_sim + 0.2 * length_penalty
        scored.append((final_score, cand))

    scored.sort(key=lambda x: x[0], reverse=True)
    return scored[0][1] if scored else candidates[0]
