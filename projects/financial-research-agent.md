---
title: Financial Research Agent
layout: default
---

[← Back to Projects](/projects)

# Financial Research Agent

**A retrieval-augmented research assistant for BFSI documents that extracts answers from financial PDFs using semantic search and two-pass LLM reasoning, augments incomplete responses with external data, and scores every answer for confidence and provenance — enabling analysts to move from document to decision with traceable, source-backed insights.**

## Tags & Technologies
<div class="topic-tags">
<span class="topic-tag">RAG</span>
<span class="topic-tag">Semantic Search</span>
<span class="topic-tag">LLMs</span>
<span class="topic-tag">Agentic AI</span>
<span class="topic-tag">Confidence Scoring</span>
<span class="topic-tag">Explainable AI</span>
<span class="topic-tag">AWS Bedrock</span>
<span class="topic-tag">Llama 3.3 70B</span>
<span class="topic-tag">Amazon Titan Embeddings</span>
<span class="topic-tag">Annoy</span>
<span class="topic-tag">SerpAPI</span>
<span class="topic-tag">Python</span>
<span class="topic-tag">Streamlit</span>
<span class="topic-tag">BFSI</span>
</div>

## Key Impact & KPIs

- **Two-pass retrieval-augmented generation** — internal evidence first, external augmentation only when needed
- **Weighted confidence scoring with hallucination flags** — structured quality signals before results reach the analyst
- **Per-document semantic memory** — stores and reuses prior Q&A to eliminate redundant LLM calls
- **Offline-first, privacy-preserving design** — full document analysis without external API dependency

## Project Overview

### 1. BFSI Document Ingestion Pipeline
Designed a document ingestion pipeline for BFSI materials — annual reports, regulatory filings, and investment research — that extracts text via PyPDF2, segments it into overlapping chunks, and embeds each chunk through Amazon Titan for semantic retrieval.

### 2. Two-Pass Retrieval-Augmented Generation
Implemented a two-pass RAG workflow where the first pass synthesizes answers strictly from internal document evidence via Llama 3.3 70B, and a second pass — triggered only when coverage is incomplete — augments the response with external data from SerpAPI.

### 3. Confidence Scoring and Hallucination Safeguards
Built a verification layer that computes weighted confidence across semantic similarity, source quality, evidence coverage, and consistency, while flagging numeric contradictions, outdated references, and unsourced claims — providing structured quality signals before results reach the analyst.

### 4. Per-Document Semantic Memory
Developed a per-document memory system that persists Q&A pairs with embeddings, indexes them via Annoy for similarity lookup, and injects relevant prior answers into synthesis prompts — eliminating redundant LLM calls and preserving continuity across research sessions.

### 5. Interactive Research Interface
Delivered a multi-interface research tool with a Streamlit dashboard for document upload and query execution, a CLI for programmatic access, and a nine-scenario evaluation harness — demonstrating operationalization of RAG for financial document analysis under practical latency and trust constraints.

## Model Selection Rationale

- **Models/LLMs used:** Llama 3.3 70B Instruct (synthesis & reasoning); Amazon Titan Embed Text v1 (embeddings).
- **Llama 3.3 70B:** Selected for strong instruction-following on structured financial text, low-temperature (0.2) determinism, and availability on AWS Bedrock without self-hosting overhead.
- **Titan Embeddings:** Chosen for native Bedrock integration, consistent L2-normalizable output, and sufficient dimensionality for financial document retrieval.
- **SerpAPI as external provider:** Structured JSON output from Google search results provided more parse-reliable augmentation than raw web scraping; DuckDuckGo HTML fallback ensures zero-cost degradation when API quota is exhausted.
- **Trade-off:** Prioritized inference reliability and AWS-native deployment over raw benchmark performance; avoided larger models to keep per-query latency practical for interactive use.

## Links

- [Interactive Demo →](<PLACEHOLDER_DEMO_URL>)
- [View Code →](<PLACEHOLDER_CODE_URL>)
