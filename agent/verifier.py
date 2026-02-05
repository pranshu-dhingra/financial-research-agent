#!/usr/bin/env python3
"""
verifier.py - BFSI-aware Verifier and Confidence Scoring

Evaluates answer quality, quantifies uncertainty, detects contradictions.
Epistemic conscience of the system.
"""

import re
from datetime import datetime

# Source quality weights (BFSI domain-aware)
SOURCE_WEIGHTS = {
    "internal": 1.0,
    "regulatory": 0.9,
    "financials": 0.8,
    "market": 0.8,
    "macro": 0.85,
    "credit": 0.85,
    "news": 0.7,
    "generic": 0.5,
}


def _source_weight(category: str | None, tool: str | None) -> float:
    """Map provenance item to source quality weight."""
    cat = (category or "generic").lower()
    return SOURCE_WEIGHTS.get(cat, SOURCE_WEIGHTS.get("generic", 0.5))


def _extract_numbers(text: str) -> list[float]:
    """Extract numeric values (percentages, decimals) from text. Skip single digits in words."""
    numbers = []
    # Match patterns like 12.5%, 15.3, 1,234.56 - require decimal or % to avoid "1" in "CET1"
    for m in re.finditer(r"\b(\d{1,3}(?:,\d{3})*(?:\.\d+)?)\s*%", text):
        s = m.group(1).replace(",", "")
        try:
            numbers.append(float(s))
        except ValueError:
            pass
    if not numbers:
        for m in re.finditer(r"\b(\d{1,3}(?:,\d{3})*\.\d+)\b", text):
            s = m.group(1).replace(",", "")
            try:
                numbers.append(float(s))
            except ValueError:
                pass
    return numbers


def _check_numeric_contradiction(provenance: list) -> bool:
    """Detect conflicting numeric values across provenance (e.g. two different CET1 values)."""
    if len(provenance) < 2:
        return False
    numbers_per_source = [_extract_numbers(p.get("text", "") or "") for p in provenance]
    numbers_per_source = [n for n in numbers_per_source if n]
    if len(numbers_per_source) < 2:
        return False
    first_vals = [n[0] for n in numbers_per_source if n]
    if len(first_vals) < 2:
        return False
    if max(first_vals) - min(first_vals) > 0.5:
        return True
    return False


def _check_outdated_dates(text: str) -> bool:
    """Simple check for future dates or very old stats."""
    year_matches = re.findall(r"\b(20[0-9]{2})\b", text)
    if not year_matches:
        return False
    current_year = datetime.utcnow().year
    years = [int(y) for y in year_matches]
    if any(y > current_year for y in years):
        return True
    if any(y < current_year - 5 for y in years):
        return True
    return False


def _coverage_score(answer: str, provenance: list) -> float:
    """Estimate percentage of answer sentences with provenance support."""
    if not answer or not provenance:
        return 0.0
    sentences = [s.strip() for s in re.split(r"[.!?]+", answer) if s.strip() and len(s.strip()) > 10]
    if not sentences:
        return 1.0
    prov_text = " ".join(p.get("text", "") or "" for p in provenance).lower()
    covered = sum(1 for s in sentences if any(w in prov_text for w in s.lower().split()[:3]))
    return covered / len(sentences) if sentences else 1.0


def verifier_agent(
    answer: str,
    provenance: list,
    partials: list | None = None,
    external_snippets: list | None = None,
    flags_override: list | None = None,
) -> dict:
    """
    Evaluate answer quality and compute confidence.
    Returns: {confidence, flags, explanation}
    """
    partials = partials or []
    external_snippets = external_snippets or []
    flags = flags_override or []

    max_internal_sim = 0.0
    internal_count = 0
    external_count = 0
    source_scores = []

    for p in provenance:
        if p.get("type") == "internal":
            internal_count += 1
            sim = p.get("similarity")
            if sim is not None:
                max_internal_sim = max(max_internal_sim, sim)
            source_scores.append(SOURCE_WEIGHTS["internal"])
        elif p.get("type") == "external":
            external_count += 1
            cat = p.get("category") or "generic"
            tool = p.get("tool", "")
            w = _source_weight(cat, tool)
            source_scores.append(w)
            if cat == "generic" and "web_search" in str(tool).lower():
                pass

    if external_count > 0 and all(s <= 0.5 for s in source_scores if s < 1.0):
        flags.append("ONLY_GENERIC_WEB")

    if _check_numeric_contradiction(provenance):
        flags.append("NUMERIC_CONTRADICTION")

    for p in provenance:
        text = p.get("text", "") or ""
        if _check_outdated_dates(text):
            flags.append("OUTDATED_EXTERNAL_DATA")
            break

    coverage = _coverage_score(answer, provenance)
    if coverage < 0.5 and len(provenance) > 0:
        flags.append("LOW_EVIDENCE_COVERAGE")

    if "insufficient" in answer.lower() or "not found" in answer.lower():
        pass
    elif internal_count == 0 and external_count == 0:
        flags.append("POTENTIAL_HALLUCINATION")
    elif coverage < 0.3:
        flags.append("POTENTIAL_HALLUCINATION")

    source_quality = sum(source_scores) / len(source_scores) if source_scores else 0.0
    consistency_score = 1.0
    if "NUMERIC_CONTRADITION" in flags:
        consistency_score -= 0.5
    if "OUTDATED_EXTERNAL_DATA" in flags:
        consistency_score -= 0.3
    if "POTENTIAL_HALLUCINATION" in flags:
        consistency_score -= 0.4
    consistency_score = max(0.0, consistency_score)

    confidence = (
        0.4 * max_internal_sim
        + 0.3 * source_quality
        + 0.2 * coverage
        + 0.1 * consistency_score
    )
    confidence = max(0.0, min(1.0, confidence))

    # If both internal and external used, ensure confidence >= 0.6
    if internal_count > 0 and external_count > 0:
        confidence = max(confidence, 0.6)

    if "insufficient" in answer.lower():
        confidence = min(confidence, 0.4)

    explanation_parts = []
    if internal_count > 0:
        explanation_parts.append(f"{internal_count} internal source(s), max similarity {max_internal_sim:.2f}")
    if external_count > 0:
        explanation_parts.append(f"{external_count} external corroboration(s)")
    if "PARTIAL_EXTERNAL_COMPLETION" in flags:
        explanation_parts.append("Partial external completion used")
    if flags:
        explanation_parts.append(f"Flags: {', '.join(flags)}")
    explanation = ". ".join(explanation_parts) if explanation_parts else "No provenance."

    return {
        "confidence": confidence,
        "flags": flags,
        "explanation": explanation,
    }
