# PDF Q&A Agent

A **BFSI-focused PDF research assistant** that answers questions from financial documents using semantic search, language models, and optional external augmentation. Designed for financial analysts, compliance officers, and researchers working with annual reports, regulatory filings, and investment research documents.

## Key Features

- **PDF Question Answering**: Extract insights from financial documents with semantic chunking and two-pass reasoning
- **Offline Mode**: Search memory without external API calls (instant, privacy-preserving)
- **Online Mode**: Augment partial answers with live external data via SerpAPI when needed
- **Semantic Memory**: Store and retrieve Q&A pairs per PDF for faster queries on repeated topics
- **Confidence Scoring**: Risk assessment for each answer (high, medium, low) with explicit flags
- **Hallucination Prevention**: Strict provenance tracking; answers cite their sources

## Architecture Overview

```
Query
  ↓
[PDF Chunker] → Extract & embed document chunks
  ↓
[Internal Retriever] → Find relevant chunks via semantic search
  ↓
[LLM Synthesis] → Draft answer from internal evidence
  ↓
[Completeness Check] → Is the answer full or partial?
  ├─ SUFFICIENT → Return answer with confidence
  └─ PARTIAL/MISSING → (if ENABLE_TOOL_PLANNER=1)
      ↓
    [External Lookup] → Fetch data from SerpAPI
      ↓
    [Re-synthesis] → Enhance answer with external facts
      ↓
[Verifier Agent] → Score confidence, detect contradictions
  ↓
Answer + Provenance + Confidence + Flags
```

## Project Structure

The codebase is organized into five modular layers:

```
pdf-qa-agent/
├── config/                    # Configuration & environment variables
│   ├── settings.py           # All 30+ config constants
│   └── __init__.py
│
├── core/                      # Core utilities (no business logic)
│   ├── embeddings.py         # AWS Bedrock embedding generation
│   ├── pdf_loader.py         # PDF text extraction (PyPDF2)
│   ├── chunking.py           # Text sliding-window chunking
│   └── __init__.py
│
├── agent/                     # Business logic & orchestration
│   ├── orchestrator.py       # Main RAG workflow (semantic → synthesis → verify)
│   ├── synthesizer.py        # LLM calls + prompt templates
│   ├── retriever.py          # Chunk & memory semantic search
│   ├── memory.py             # Per-PDF semantic memory (JSON)
│   ├── verifier.py           # Confidence scoring & contradiction detection
│   ├── tools.py              # External search (SerpAPI) integration
│   └── __init__.py
│
├── ui/                        # Web interface
│   ├── streamlit_app.py      # Streamlit dashboard
│   └── __init__.py
│
├── cli/                       # Command-line interface
│   ├── local_pdf_qa.py       # CLI entrypoint
│   └── __init__.py
│
├── tests/                     # Test suite
├── memories/                  # Per-PDF semantic memory files
├── uploads/                   # User-uploaded PDFs
└── requirements.txt           # Python dependencies
```

### Layer Responsibilities

- **config/**: Environment variables, feature flags, constants
- **core/**: Stateless utilities for PDFs, embeddings, chunking (reusable in any context)
- **agent/**: Stateful business logic (retrieval, synthesis, orchestration, memory)
- **ui/**: Streamlit web dashboard (interactive queries)
- **cli/**: Command-line interface (batch/programmatic queries)

### Running the Application

**CLI (command-line):**
```bash
python cli/local_pdf_qa.py path/to/document.pdf "Your question"
```

**Web UI (Streamlit):**
```bash
streamlit run ui/streamlit_app.py
```

Then upload PDFs and ask questions interactively.

## How External Search is Triggered

External search (SerpAPI) is **automatically invoked** when:

1. **No internal evidence**: Document doesn't mention the topic at all
2. **Partial internal evidence**: Document mentions related metrics but doesn't fully answer the question (e.g., mentions regulatory requirements but not specific ratios)
3. **Missing entities**: Query references companies/metrics not found in the document

External search is **skipped** when:

- Document fully answers the question internally
- `ENABLE_TOOL_PLANNER=0` (default; only internal search)

## When to Use Each Mode

### Offline Mode (Default)
```bash
python local_pdf_qa.py path/to/file.pdf "Your question"
```
- **Use when**: Privacy is critical, no internet available, or rapid responses needed
- **Behavior**: Searches document + memory only
- **Speed**: Instant
- **No API costs**

### Online Mode (With External Augmentation)
```bash
ENABLE_TOOL_PLANNER=1 python local_pdf_qa.py path/to/file.pdf "What is the CET1 ratio?"
```
- **Use when**: You need current data (e.g., live stock prices, latest ratings)
- **Behavior**: Tries internal first; calls SerpAPI if answer is incomplete
- **Speed**: 3-10 seconds (includes API + synthesis)
- **Requires**: SerpAPI credentials (one-time setup via prompt)

## Credentials and Configuration

### SerpAPI Setup (Optional, One-Time)

If `ENABLE_TOOL_PLANNER=1`:

1. First query prompts for SerpAPI credentials:
   ```
   This provider is not configured. Please provide credentials now or type SKIP.
   ```
2. Enter your API key when prompted
3. Credentials stored locally in `.tool_credentials.json` (ignored by git)
4. Reused for all future queries

To skip: Type `SKIP` at the prompt → falls back to generic web search

Get SerpAPI key: https://serpapi.com/

## Memory Behavior

- **Per-PDF storage**: Each PDF gets its own memory file (`memories/memory_<hash>.json`)
- **Auto-learn**: Answers to Q&A pairs are stored after each query
- **Semantic indexing**: Stored Q&As are embeddable and searchable
- **Offline query**: Questions matching stored Q&As return instant answers from memory
- **Clear memory**: Use the Streamlit UI to delete all Q&A history for a PDF

## Confidence Scoring

Each answer receives a **confidence score** (0.0 – 1.0) and **quality flags**:

| Score | Label | Meaning |
|-------|-------|---------|
| > 0.8 | 🟢 High | Answer fully supported by document(s) |
| 0.5–0.8 | 🟡 Medium | Partial or supplemented answer |
| < 0.5 | 🔴 Low | Unreliable; use with caution |

### Quality Flags

- `PARTIAL_EXTERNAL_COMPLETION`: Answer includes external data to supplement internal evidence
- `ONLY_GENERIC_WEB`: Fell back to generic web search (not premium provider)
- `NUMERIC_CONTRADICTION`: Internal and external data disagree on numbers
- `OUTDATED_EXTERNAL_DATA`: External source is older than document publish date
- `LOW_EVIDENCE_COVERAGE`: Few sentences in answer have supporting sources
- `POTENTIAL_HALLUCINATION`: Answer mentions facts not in any source

## Limitations

⚠️ **Important to understand:**

- **No guarantees on current data**: Answers reflect document + external snapshot only
- **Regulatory latency**: Financial data may be 1-3 months old (depends on document)
- **SerpAPI dependency**: External search requires internet + valid API key
- **LLM reasoning limits**: Complex multi-step inference may fail; verify manually
- **No vector-db persistence**: Embeddings computed fresh per query (not cached)
- **PDF parsing**: Scanned PDFs or complex layouts may extract text incorrectly
- **Language**: Currently optimized for English documents

## Installation

### Prerequisites
- Python 3.9+
- AWS credentials configured (for Bedrock LLM)
- (Optional) SerpAPI key for external search

### Setup

```bash
# Clone repo
git clone https://github.com/<username>/pdf-qa-agent.git
cd pdf-qa-agent

# Install dependencies
pip install -r requirements.txt

# (Optional) Configure SerpAPI
# Edit tool_config.json or let the system prompt you on first use

# Run locally
python local_pdf_qa.py path/to/document.pdf "What is the total debt?"

# Run Streamlit UI
streamlit run app.py
```

## Environment Variables

```bash
# Core Models (AWS Bedrock)
export MODEL_ID="anthropic.llama2-70b-chat-v1"
export EMBEDDING_MODEL_ID="amazon.titan-embed-text-v2:0"
export AWS_REGION="us-east-1"

# Chunking
export CHUNK_SIZE=1500
export CHUNK_OVERLAP=300
export MAX_PAGES=500
export MAX_CHUNKS=100

# Memory & Debugging
export MAX_MEMORY_TO_LOAD=5    # Top-k stored Q&A pairs to include
export SAVE_MEMORY=1            # Auto-save answers to memory
export DEBUG=1                  # Verbose logging

# External Search (NEW)
export ENABLE_TOOL_PLANNER=1    # Enable SerpAPI augmentation
```

## Example Queries

### ✅ Works Well

```bash
# Specific metrics in document
"What is HDFC's CET1 capital ratio as of 2024?"

# Regulatory terms
"What is the total risk-weighted assets (RWA)?"

# Business segments
"How much revenue did the Asia-Pacific region generate?"

# Document summaries
"What are the key risks mentioned?"
```

### ⚠️ Requires Verification

```bash
# Current prices (needs external data)
"What is HSBC's stock price today?" → Relies on external search; may be delayed

# Multi-document queries
"Compare dividend policies of Bank A and Bank B?" → Use separately, compare manually

# Predictions
"Will the bank's profitability improve next year?" → LLM reasoning; not guaranteed
```

## Project Structure

```
pdf-qa-agent/
├── agent/                   # Business logic & orchestration
│   ├── orchestrator.py      # RAG workflow coordinator
│   ├── verifier.py          # Confidence scoring & validation
│   ├── tools.py             # External search integration (SerpAPI)
│   ├── memory.py            # Per-PDF semantic memory
│   ├── retriever.py         # Chunk & memory semantic search
│   └── synthesizer.py       # LLM calls + prompt templates
├── cli/                     # Command-line utilities
│   ├── local_pdf_qa.py      # Main Q&A CLI
│   └── manage_tools.py      # Tool provider management
├── ui/                      # Web interface
│   └── streamlit_app.py     # Streamlit web UI
├── evaluation/              # Evaluation suite
│   ├── run_evaluation.py    # Evaluation harness
│   ├── evaluation_queries.py # Test queries
│   └── evaluation_report.py # Report generation
├── core/                    # Core utilities (no business logic)
│   ├── embeddings.py        # AWS Bedrock embeddings
│   ├── pdf_loader.py        # PDF text extraction
│   └── chunking.py          # Text sliding-window chunking
├── requirements.txt         # Dependencies
├── tool_config.json         # Provider templates (no secrets)
├── memories/                # Auto-generated Q&A storage (ignored)
├── uploads/                 # User PDFs for testing (ignored)
└── tests/                   # Unit and integration tests
```

## Usage Examples

### CLI: Simple Answer

```bash
python local_pdf_qa.py budget_speech.pdf "What is the inflation forecast?"
```

Output:
```
=== ANSWER ===
The inflation forecast for 2025 is 4.2%, based on...

=== SOURCES ===
internal | budget_speech.pdf | page=12
internal | budget_speech.pdf | page=45

=== CONFIDENCE ===
0.92

=== FLAGS ===
(none)
```

### CLI: With External Augmentation

```bash
ENABLE_TOOL_PLANNER=1 python local_pdf_qa.py abc_bank_2024.pdf \
  "What was the market capitalization of ABC Bank in 2024?"
```

- Internal: Document mentions assets but not market cap
- External: SerpAPI fetches current stock price & market cap
- Result: Hybrid answer with both internal + external sources
- Confidence: 0.78 (marked PARTIAL_EXTERNAL_COMPLETION)

### Streamlit UI: Interactive Mode

```bash
streamlit run app.py
```

Opens browser → Upload PDF → Toggle offline/online → Ask questions → View memory

## Testing

```bash
# Run test suite
pytest tests/ -v

# Test specific feature
pytest tests/test_verifier_numeric_conflict.py -v

# Debug mode
DEBUG=1 python local_pdf_qa.py sample.pdf "test question"
```

## Contributing

This is a personal research project. Issues, suggestions, and PRs are welcome.

## License

MIT License

## Disclaimer

**Financial Disclaimer**: This tool is for research and analysis only. It is NOT financial advice. Always verify answers against original documents and consult qualified financial advisors before making investment decisions.

**Data Accuracy**: Answers are based on available data with inherent delays. External data is not real-time. Use for historical analysis, not high-frequency trading.

