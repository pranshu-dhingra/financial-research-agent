# PDF Q&A Agent

Annual Reports and Investment Research for BFSI. PDF Q&A with chunking, two-pass reasoning, streaming, and semantic memory.

## Conceptual Tools vs Configured Providers

- **Conceptual tools**: Categories of external knowledge (regulatory filings, company financials, macroeconomic data, credit ratings, financial news, generic web search) defined in `tools.TOOL_KNOWLEDGE_BASE`. The agent can recommend these even if not configured.
- **Configured providers**: Actual API/data sources in `tool_config.json` with endpoints and required credentials. Only configured providers can be used for live queries.

## How the Agent Decides and Asks for Credentials

1. When you ask a question (e.g. "What is HDFC Bank CET1 ratio today?"), the **tool planner** (LLM) decides which category and providers would best answer it.
2. If the recommended provider is **not** in `tool_config.json`, the system prints:
   - `Tool '<provider>' recommended for category '<category>'.`
   - `This provider is not configured. Please provide credentials now or type SKIP.`
3. If you provide credentials (JSON or key=value), they are stored via `tools.register_credentials()` and used for future queries.
4. If you type **SKIP**, the system tries the next provider or falls back to generic web search (`web_search_generic`).
5. After one-time configuration, the system uses the provider for all future queries.

## Usage

```bash
pip install -r requirements.txt
python local_pdf_qa.py path/to/file.pdf "Your question here"
```

### Optional: Tool Intelligence Layer

Set `ENABLE_TOOL_PLANNER=1` to augment answers with external search when the tool planner recommends it:

```bash
ENABLE_TOOL_PLANNER=1 python local_pdf_qa.py budget_speech.pdf "What is HDFC Bank CET1 ratio today?"
```

## Environment Variables

- `MODEL_ID`, `EMBEDDING_MODEL_ID`, `AWS_REGION`
- `CHUNK_SIZE`, `CHUNK_OVERLAP`, `MAX_PAGES`, `MAX_CHUNKS`
- `DEBUG=1`, `SAVE_MEMORY=1`, `MAX_MEMORY_TO_LOAD`
- `ENABLE_TOOL_PLANNER=1` – enable BFSI-aware external search
