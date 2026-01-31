#!/usr/bin/env bash
# verify_end_to_end.sh - Smoke-check for BFSI Research Agent
# No external network calls required.

set -e
cd "$(dirname "$0")"

echo "=== BFSI Research Agent – Smoke Check ==="

# 1. Run pytest (if available)
if python -c "import pytest" 2>/dev/null; then
  echo ""
  echo "[1/3] Running pytest..."
  python -m pytest tests/ -v --tb=short -x
else
  echo ""
  echo "[1/3] pytest not found. Install: pip install -r requirements_add.txt"
  echo "Skipping pytest."
fi

# 2. Small dry-run query (mocked, no network)
echo ""
echo "[2/3] Dry-run (mocked orchestrator)..."
python -c "
import sys
from pathlib import Path
sys.path.insert(0, str(Path('.').resolve()))
from unittest.mock import patch
from orchestrator import classifier_agent
with patch('local_pdf_qa.extract_text_from_pdf', return_value='sample'):
    with patch('local_pdf_qa.chunk_text', return_value=['chunk1']):
        with patch('local_pdf_qa.find_relevant_chunks', return_value=[
            {'chunk_text': 'c', 'idx': 0, 'similarity': 0.9}
        ]):
            r = classifier_agent('test query', 'dummy.pdf')
assert r.get('internal_sufficient') == True, r
print('Dry-run OK: classifier returns internal_sufficient=True')
" || { echo "Dry-run failed."; exit 1; }

# 3. Manual steps
echo ""
echo "[3/3] Manual verification steps:"
echo ""
echo "  1. Register provider (optional):"
echo "     python manage_tools.py list"
echo "     python manage_tools.py add-provider --id serpapi --category generic \\"
echo "       --endpoint 'https://api.serpapi.com/search?q={q}&api_key={api_key}' --required api_key"
echo ""
echo "  2. Add credentials (optional):"
echo "     python manage_tools.py add-credentials --provider serpapi --field api_key=YOUR_KEY"
echo ""
echo "  3. Run Streamlit UI:"
echo "     streamlit run app.py"
echo ""
echo "  4. Test: Upload PDF, ask question, check provenance and confidence."
echo ""
echo "=== Smoke check complete ==="
