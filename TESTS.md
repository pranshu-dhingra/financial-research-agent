# BFSI Research Agent – Tests Guide

How to validate correctness of the system.

---

## A. Unit Tests

### Tool Planner

- **File**: `tests/test_tool_planner_context.py`
- **What**: BFSI context, conceptual tools, planner output structure.
- **Run**: `python -m pytest tests/test_tool_planner_context.py -v`

### Verifier

- **Files**: `tests/test_verifier_no_internal.py`, `tests/test_verifier_numeric_conflict.py`
- **What**: Confidence scoring, external-only low confidence, numeric contradiction detection.
- **Run**: `python -m pytest tests/test_verifier_*.py -v`

### Orchestrator

- **File**: `tests/test_orchestrator_flow.py`
- **What**: Classifier internal-only path, tool agent not called when internal sufficient.
- **Run**: `python -m pytest tests/test_orchestrator_flow.py -v`

---

## B. Integration Tests

### Internal-Only Question

- **File**: `tests/test_orchestrator_flow.py`
- **What**: When classifier returns `internal_sufficient=True`, external tools are skipped.

### External Fallback

- **File**: `tests/test_external_fallback.py`
- **What**: When internal insufficient, tool planner recommends providers; fallback to generic search.

### Credential Handshake

- **File**: `tests/test_credential_handshake.py`
- **What**: Provider not configured or missing credentials → prompt or SKIP.

### Graceful Failure

- **File**: `tests/test_graceful_failure.py`
- **What**: System degrades gracefully when Bedrock or tools fail.

---

## C. Manual Tests

### Upload PDF

1. Run `streamlit run app.py`.
2. Use sidebar "Upload PDF".
3. Select a PDF file.
4. Confirm it appears in the dropdown and `uploads/` directory.

### Run Question

1. Select a PDF.
2. Enter a question (e.g. "What is the main theme of this document?").
3. Enable "Run live analysis".
4. Click "Ask".
5. Confirm answer, sources table, and confidence appear.

### Check Provenance

- Verify **Sources** table shows:
  - `type`: internal or external
  - `source`: PDF page or URL
  - `category`: regulatory, financials, generic, etc.
  - `snippet`: relevant text

### Check Confidence

- Verify **Confidence** shows numeric score and label:
  - \> 0.8 → High
  - 0.5–0.8 → Medium
  - \< 0.5 → Low

### Memory Separation

1. Upload PDF1, ask question, note answer.
2. Upload PDF2, ask different question.
3. Use "Show Memory for Selected PDF" for each.
4. Confirm memories are separate per PDF.

### Offline Mode

1. Run a live question first (to populate memory).
2. Uncheck "Run live analysis".
3. Click "Ask".
4. Confirm last N stored Q&As are shown.
