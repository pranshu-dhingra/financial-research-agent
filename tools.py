#!/usr/bin/env python3
"""
tools.py - BFSI-aware Tool Intelligence Layer

Conceptual tools vs configured providers:
- Conceptual tools: Categories of external knowledge (regulatory, financials, macro, etc.)
  defined in TOOL_KNOWLEDGE_BASE. The agent can recommend these even if not configured.
- Configured providers: Actual API/data sources in tool_config.json with endpoints and
  required credentials. Only configured providers can be used for live queries.

Credential handshake:
- When the tool planner recommends a provider not in tool_config.json, the system
  pauses and asks the user for credentials.
- User can provide credentials (stored via register_credentials) or type SKIP to
  try the next provider or fall back to generic web search.
"""

import os
import json
import re
from pathlib import Path

# --- Conceptual tool universe (BFSI investment research) ---

TOOL_KNOWLEDGE_BASE = {
    "web_search": {
        "category": "generic",
        "purpose": "Search authoritative websites for latest info",
        "example_providers": ["SerpAPI", "Bing API", "DuckDuckGo"],
    },
    "regulatory_filings": {
        "category": "regulatory",
        "purpose": "Fetch official filings and disclosures",
        "example_providers": ["SEC EDGAR", "SEBI", "Companies House"],
    },
    "company_financials": {
        "category": "financials",
        "purpose": "Company metrics, balance sheets, ratios",
        "example_providers": ["Yahoo Finance", "Alpha Vantage"],
    },
    "macroeconomic": {
        "category": "macro",
        "purpose": "GDP, inflation, policy rates",
        "example_providers": ["World Bank", "IMF", "RBI"],
    },
    "credit_ratings": {
        "category": "credit",
        "purpose": "Issuer credit ratings",
        "example_providers": ["Moody's", "S&P"],
    },
    "financial_news": {
        "category": "news",
        "purpose": "Market and company news",
        "example_providers": ["Reuters", "Bloomberg"],
    },
}

TOOL_CONFIG_PATH = Path(__file__).parent / "tool_config.json"
CREDENTIALS_STORE_PATH = Path(__file__).parent / ".tool_credentials.json"

# In-memory credential cache (provider_id -> dict of credentials)
_credentials_cache = {}


def load_tool_knowledge_base():
    """Return the conceptual tool knowledge base."""
    return TOOL_KNOWLEDGE_BASE.copy()


def list_conceptual_tools():
    """Return list of conceptual tool names."""
    return list(TOOL_KNOWLEDGE_BASE.keys())


def _load_tool_config():
    """Load tool_config.json. Returns dict with 'providers' key."""
    if not TOOL_CONFIG_PATH.exists():
        return {"providers": {}}
    try:
        with open(TOOL_CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {"providers": {}}
    except Exception:
        return {"providers": {}}


def list_configured_providers():
    """Return list of configured provider IDs."""
    config = _load_tool_config()
    providers = config.get("providers", {})
    return list(providers.keys()) if isinstance(providers, dict) else []


def get_provider_for_category(category: str):
    """Return list of configured providers that match the given category."""
    config = _load_tool_config()
    providers = config.get("providers", {})
    if not isinstance(providers, dict):
        return []
    return [
        pid for pid, pdef in providers.items()
        if isinstance(pdef, dict) and pdef.get("category") == category
    ]


def get_provider_config(provider_id: str):
    """Return provider config dict or None."""
    config = _load_tool_config()
    providers = config.get("providers", {})
    return providers.get(provider_id) if isinstance(providers, dict) else None


def register_credentials(provider_id: str, credentials: dict):
    """Store credentials for a provider. Persists to .tool_credentials.json."""
    global _credentials_cache
    _credentials_cache[provider_id] = credentials
    # Persist
    store = {}
    if CREDENTIALS_STORE_PATH.exists():
        try:
            with open(CREDENTIALS_STORE_PATH, "r", encoding="utf-8") as f:
                store = json.load(f)
        except Exception:
            pass
    if not isinstance(store, dict):
        store = {}
    store[provider_id] = credentials
    try:
        with open(CREDENTIALS_STORE_PATH, "w", encoding="utf-8") as f:
            json.dump(store, f, indent=2)
    except Exception:
        pass


def get_credentials(provider_id: str):
    """Get credentials for provider. Checks cache first, then file."""
    if provider_id in _credentials_cache:
        return _credentials_cache[provider_id]
    if CREDENTIALS_STORE_PATH.exists():
        try:
            with open(CREDENTIALS_STORE_PATH, "r", encoding="utf-8") as f:
                store = json.load(f)
            creds = store.get(provider_id) if isinstance(store, dict) else None
            if creds:
                _credentials_cache[provider_id] = creds
            return creds
        except Exception:
            pass
    return None


def _resolve_credentials(provider_id: str, required_fields: list):
    """Get credentials from cache/file or env. Returns dict or None."""
    creds = get_credentials(provider_id)
    if creds and all(creds.get(f) for f in required_fields):
        return creds
    # Fallback: env vars like SERPAPI_API_KEY
    env_prefix = provider_id.upper().replace("-", "_")
    env_creds = {}
    for f in required_fields:
        env_key = f"{env_prefix}_{f.upper()}"
        val = os.environ.get(env_key)
        if val:
            env_creds[f] = val
    if len(env_creds) == len(required_fields):
        return env_creds
    return creds


def web_search_via_provider(query: str, provider_id: str, **extra_creds):
    """
    Execute web search via a configured provider.
    Returns dict with 'text' and 'url' keys. Raises or returns error dict on failure.
    """
    config = get_provider_config(provider_id)
    if not config:
        return {"text": f"Provider '{provider_id}' not configured.", "url": ""}

    if provider_id == "web_search_generic":
        return web_search_generic(query)

    required = config.get("required_fields", [])
    endpoint_tpl = config.get("endpoint_template", "")
    if not endpoint_tpl:
        return {"text": f"Provider '{provider_id}' has no endpoint.", "url": ""}

    creds = _resolve_credentials(provider_id, required) or {}
    creds.update(extra_creds)

    missing = [f for f in required if not creds.get(f)]
    if missing:
        return {"text": f"Missing credentials for {provider_id}: {missing}", "url": ""}

    # Build URL from template (e.g. q={q}, api_key={api_key})
    url = endpoint_tpl.replace("{q}", _url_encode(query))
    for k, v in creds.items():
        url = url.replace("{" + k + "}", str(v))

    try:
        import urllib.request
        req = urllib.request.Request(url, headers={"User-Agent": "BFSI-PDF-QA/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        return {"text": f"Search request failed: {e}", "url": url}

    # Parse response based on provider
    if "serpapi" in provider_id.lower():
        return _parse_serpapi_response(raw, url)
    # Generic: try to extract snippets from JSON if possible
    return _parse_generic_search_response(raw, url)


def _url_encode(s: str) -> str:
    import urllib.parse
    return urllib.parse.quote(s, safe="")


def _parse_serpapi_response(raw: str, url: str) -> dict:
    """Parse SerpAPI JSON response."""
    try:
        data = json.loads(raw)
        org = data.get("organic_results", [])
        snippets = []
        for r in org[:5]:
            if isinstance(r, dict):
                title = r.get("title", "")
                snippet = r.get("snippet", "")
                link = r.get("link", "")
                if snippet:
                    snippets.append(f"{title}: {snippet}")
        text = "\n".join(snippets) if snippets else data.get("answer_box", {}).get("answer", raw[:2000])
        return {"text": str(text)[:4000], "url": url}
    except json.JSONDecodeError:
        return {"text": raw[:4000], "url": url}


def _parse_generic_search_response(raw: str, url: str) -> dict:
    """Fallback parser for generic JSON-like responses."""
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            for key in ["snippet", "snippets", "results", "organic_results", "items"]:
                val = data.get(key)
                if val:
                    if isinstance(val, list):
                        parts = [str(x) for x in val[:5]]
                        return {"text": "\n".join(parts)[:4000], "url": url}
                    return {"text": str(val)[:4000], "url": url}
    except json.JSONDecodeError:
        pass
    return {"text": raw[:4000], "url": url}


def web_search_generic(query: str) -> dict:
    """
    Default generic web search - no credentials required.
    Uses DuckDuckGo HTML scraping if possible, else returns stub.
    """
    try:
        return _web_search_duckduckgo(query)
    except Exception:
        return {"text": "External search not configured. Please add provider.", "url": ""}


def _web_search_duckduckgo(query: str) -> dict:
    """DuckDuckGo HTML scrape (no API key)."""
    import urllib.parse
    import urllib.request
    base = "https://html.duckduckgo.com/html/"
    data = urllib.parse.urlencode({"q": query}).encode()
    req = urllib.request.Request(base, data=data, headers={"User-Agent": "BFSI-PDF-QA/1.0"}, method="POST")
    with urllib.request.urlopen(req, timeout=10) as resp:
        html = resp.read().decode("utf-8", errors="replace")
    # Simple extraction of result snippets
    snippets = re.findall(r'class="result__snippet"[^>]*>([^<]+)', html)
    if snippets:
        text = "\n".join(s[:200] for s in snippets[:5])
        return {"text": text[:4000], "url": f"https://duckduckgo.com/?q={urllib.parse.quote(query)}"}
    return {"text": "External search not configured. Please add provider.", "url": ""}


def tool_planner_agent(query: str, call_llm_fn=None):
    """
    Use LLM to decide which tool category and providers to use.
    Returns dict: {category, recommended_providers: [...], reason}.
    """
    kb = load_tool_knowledge_base()
    configured = list_configured_providers()
    config = _load_tool_config()
    providers_detail = config.get("providers", {})

    kb_desc = "\n".join(
        f"- {k}: category={v['category']}, purpose={v['purpose']}, example_providers={v['example_providers']}"
        for k, v in kb.items()
    )
    cfg_desc = "\n".join(
        f"- {pid}: category={p.get('category','')}"
        for pid, p in (providers_detail.items() if isinstance(providers_detail, dict) else [])
    ) or "(none)"

    prompt = f"""<|begin_of_text|><|start_header_id|>system<|end_header_id|>

You are a tool planner for BFSI investment research. This project focuses on Annual Reports and Investment Research.

CONCEPTUAL TOOLS (knowledge categories):
{kb_desc}

CONFIGURED PROVIDERS (currently available):
{cfg_desc}

<|eot_id|><|start_header_id|>user<|end_header_id|>

Given the user question, output a JSON object with:
- "category": one of generic, regulatory, financials, macro, credit, news
- "recommended_providers": list of provider names (e.g. serpapi, yahoo_finance) that would best answer this
- "reason": brief explanation

Question: {query}

Output only valid JSON, no other text.
<|eot_id|><|start_header_id|>assistant<|end_header_id|>
"""

    if call_llm_fn is None:
        # Use local_pdf_qa's call_bedrock if available
        try:
            from local_pdf_qa import call_bedrock
            call_llm_fn = call_bedrock
        except ImportError:
            return {
                "category": "generic",
                "recommended_providers": ["web_search_generic"],
                "reason": "LLM not available, defaulting to generic search",
            }

    raw = call_llm_fn(prompt)
    if not raw:
        return {"category": "generic", "recommended_providers": ["web_search_generic"], "reason": "No LLM response"}

    # Parse JSON from response (may be wrapped in markdown)
    text = (raw or "").strip()
    m = re.search(r"\{[^{}]*\"category\"[^{}]*\"recommended_providers\"[^{}]*\"reason\"[^{}]*\}", text, re.DOTALL)
    if m:
        text = m.group(0)
    # Also try to find any {...} block
    for match in re.finditer(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", text):
        try:
            out = json.loads(match.group(0))
            if "category" in out and "recommended_providers" in out:
                out.setdefault("reason", "")
                return out
        except json.JSONDecodeError:
            continue
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"category": "generic", "recommended_providers": ["web_search_generic"], "reason": "Parse failed"}


def resolve_credential_handshake(provider_id: str, category: str, required_fields: list) -> str:
    """
    If provider not configured or missing credentials, prompt user.
    Returns: 'ok' if ready to use, 'skip' if user skipped, 'configured' if we got creds.
    """
    if provider_id == "web_search_generic":
        return "ok"
    config = get_provider_config(provider_id)
    if not config:
        print(f"Tool '{provider_id}' recommended for category '{category}'.")
        print("This provider is not configured. Please add it to tool_config.json or type SKIP.")
        return "skip"

    creds = _resolve_credentials(provider_id, required_fields)
    if creds:
        return "ok"

    print(f"Tool '{provider_id}' recommended for category '{category}'.")
    print("This provider is not configured. Please provide credentials now or type SKIP.")
    print(f"Required fields: {required_fields}")
    try:
        user_input = input("> ").strip()
    except EOFError:
        return "skip"
    if user_input.upper() == "SKIP":
        return "skip"
    # Try to parse as JSON or key=value
    try:
        parsed = json.loads(user_input)
        if isinstance(parsed, dict):
            register_credentials(provider_id, parsed)
            return "configured"
    except json.JSONDecodeError:
        pass
    # key=value format
    creds = {}
    for part in user_input.split(","):
        if "=" in part:
            k, v = part.split("=", 1)
            creds[k.strip()] = v.strip()
    if all(creds.get(f) for f in required_fields):
        register_credentials(provider_id, creds)
        return "configured"
    print("Could not parse credentials. Use JSON or key=value format.")
    return "skip"


def run_external_search(query: str, call_llm_fn=None) -> str:
    """
    Full flow: plan -> resolve credentials -> execute search.
    Returns combined external context text for injection into synthesis.
    """
    plan = tool_planner_agent(query, call_llm_fn)
    providers = plan.get("recommended_providers", [])
    category = plan.get("category", "generic")

    # Add web_search_generic as fallback
    if "web_search_generic" not in providers:
        providers.append("web_search_generic")

    results = []
    for pid in providers:
        if pid == "web_search_generic":
            r = web_search_generic(query)
            if r.get("text") and "not configured" not in r.get("text", "").lower():
                results.append(r["text"])
            continue
        config = get_provider_config(pid)
        if not config:
            continue
        required = config.get("required_fields", [])
        status = resolve_credential_handshake(pid, category, required)
        if status == "skip":
            continue
        if status in ("ok", "configured"):
            r = web_search_via_provider(query, pid)
            if r.get("text"):
                results.append(r["text"])
            break  # Use first successful
    if not results:
        r = web_search_generic(query)
        results.append(r.get("text", ""))
    return "\n\n".join(results) if results else ""
