# BFSI Research Agent – Runbook

Operational guide for the PDF Q&A research system (Annual Reports and Investment Research in BFSI).

---

## A. System Overview

### What This System Does

- **BFSI Research Agent**: Answers questions over uploaded PDFs (annual reports, research docs) using:
  - Internal semantic retrieval (chunking, embeddings, Annoy index)
  - External tool intelligence (web search, regulatory filings, financials)
  - Multi-agent orchestrator (Classifier → Retriever → Tool Agent → Synthesizer → Verifier)
  - Per-PDF memory for past Q&As
  - Confidence scoring and provenance tracking

### High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         BFSI Research Agent                              │
├─────────────────────────────────────────────────────────────────────────┤
│  User Input (Question + PDF)                                             │
│       │                                                                  │
│       ▼                                                                  │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐                  │
│  │ Classifier  │───▶│  Retriever  │───▶│ Tool Agent  │ (if external)   │
│  │ (internal?) │    │ (chunks)    │    │ (web/API)   │                  │
│  └─────────────┘    └─────────────┘    └─────────────┘                  │
│       │                     │                    │                       │
│       └─────────────────────┼────────────────────┘                       │
│                             ▼                                            │
│                    ┌─────────────────┐                                   │
│                    │  Synthesizer     │                                   │
│                    │  (merge + answer)│                                   │
│                    └────────┬────────┘                                   │
│                             │                                            │
│                             ▼                                            │
│                    ┌─────────────────┐     ┌─────────────┐                 │
│                    │  Verifier       │────│  Memory     │                │
│                    │  (confidence)    │     │  (per-PDF)  │                │
│                    └─────────────────┘     └─────────────┘                 │
│                             │                                            │
│                             ▼                                            │
│  Answer + Provenance + Confidence                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## B. Setup

### Python Version

- **Python 3.10+** (3.11 recommended)

### Virtual Environment

```bash
python -m venv .venv
source .venv/bin/activate   # Linux/macOS
# or: .venv\Scripts\activate   # Windows
```

### Dependencies

```bash
pip install -r requirements.txt
pip install -r requirements_add.txt   # optional: pytest for tests
```

### AWS Credentials

- Configure AWS CLI or environment variables for Bedrock access.
- Required: `bedrock:InvokeModel`, `bedrock:InvokeModelWithResponseStream`.

---

## C. External Tools

### List Providers

```bash
python cli/manage_tools.py list
```

### Add Provider

```bash
python cli/manage_tools.py add-provider \
  --id serpapi \
  --category generic \
  --endpoint "https://api.serpapi.com/search?q={q}&api_key={api_key}" \
  --required api_key
```

### Add Credentials

```bash
python cli/manage_tools.py add-credentials --provider serpapi --field api_key=YOUR_KEY
```

Or multiple fields:

```bash
python cli/manage_tools.py add-credentials --provider my_provider \
  --field api_key=xxx --field api_secret=yyy
```

---

## D. Running the System

### CLI Usage

```bash
python local_pdf_qa.py path/to/file.pdf "Your research question"
```

With external tools:

```bash
ENABLE_TOOL_PLANNER=1 python local_pdf_qa.py budget_speech.pdf "What is HDFC Bank CET1 ratio today?"
```

### Streamlit Usage

```bash
streamlit run app.py
```

- Upload PDFs via sidebar.
- Select PDF, enter question, optionally enable live analysis.
- View answer, sources, confidence, and memory.

---

## E. Memory & Persistence

### Where Memories Are Stored

- **Directory**: `memories/`
- **Format**: `memory_<pdf_basename>_<hash>.json`
- One file per PDF (hash from absolute path).

### How to Inspect

- **Streamlit**: "Show Memory for Selected PDF" in sidebar.
- **CLI**: Inspect `memories/*.json` directly (JSON list of Q&A entries).

### How to Clear Safely

- **Streamlit**: "Clear Memory for Selected PDF" (with confirmation).
- **CLI**: Delete the specific `memories/memory_*.json` file for that PDF, or use `local_pdf_qa.clear_memory_for_pdf(pdf_path)` from Python.

---

## F. Security Notes

- **`tool_config.json`**: May contain endpoint templates. Do not commit if they include secrets.
- **`.tool_credentials.json`**: Contains API keys and secrets. **Do not commit.** (Already in `.gitignore`.)
- **Production**: Use AWS Secrets Manager or Parameter Store for credentials instead of local files.
