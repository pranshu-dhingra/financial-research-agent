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
from datetime import datetime
from pathlib import Path

DEBUG = os.environ.get("DEBUG", "0") == "1"

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
    "market_prices": {
        "category": "market",
        "purpose": "Real-time and historical market prices",
        "example_providers": ["Yahoo Finance", "Alpha Vantage", "NSE", "BSE"],
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

TOOL_CONFIG_PATH = Path(__file__).resolve().parent.parent / "tool_config.json"
# Look for credentials in root directory (where user stores them)
CREDENTIALS_STORE_PATH = Path(__file__).resolve().parent.parent / ".tool_credentials.json"

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


def web_search_serpapi(query: str, top_k: int = 5) -> list:
    """
    Call SerpAPI via requests. Loads credentials from store or env.
    Returns list of {"text": snippet, "url": link, "title": title}.
    """
    creds = _resolve_credentials("serpapi", ["api_key"])
    if not creds or not creds.get("api_key"):
        return []
    try:
        import requests
        url = "https://serpapi.com/search.json"
        params = {"engine": "google", "q": query, "api_key": creds["api_key"]}
        resp = requests.get(url, params=params, timeout=10, headers={"User-Agent": "BFSI-PDF-QA/1.0"})
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        if DEBUG:
            print(f"[TOOLS] SerpAPI request failed: {e}")
        return []  # Caller handles empty; execute_external_tools returns structured error
    results = []
    for r in data.get("organic_results", [])[:top_k]:
        if isinstance(r, dict):
            title = r.get("title", "")
            snippet = r.get("snippet", "")
            link = r.get("link", "")
            if snippet or title:
                results.append({"text": f"{title}: {snippet}".strip(": ") or snippet, "url": link, "title": title})
    return results


def duckduckgo_html_scrape(query: str) -> list:
    """
    Scrape DuckDuckGo HTML results using requests + BeautifulSoup.
    Returns list of {"text": snippet, "url": link, "title": title}.
    """
    try:
        import requests
        from bs4 import BeautifulSoup
        import urllib.parse
        base = "https://html.duckduckgo.com/html/"
        data = {"q": query}
        resp = requests.post(base, data=data, timeout=10, headers={"User-Agent": "BFSI-PDF-QA/1.0"})
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        results = []
        for item in soup.select(".result")[:5]:
            title_el = item.select_one(".result__title a") or item.select_one(".result__title")
            snippet_el = item.select_one(".result__snippet")
            link_el = item.select_one(".result__title a") or item.select_one("a.result__a")
            title = title_el.get_text(strip=True) if title_el else ""
            snippet = snippet_el.get_text(strip=True) if snippet_el else ""
            link = ""
            if link_el and hasattr(link_el, "get"):
                link = link_el.get("href", "") or ""
            if link and link.startswith("//"):
                link = "https:" + link
            if not link:
                link = f"https://duckduckgo.com/?q={urllib.parse.quote(query)}"
            if snippet or title:
                results.append({"text": f"{title}: {snippet}".strip(": ") or snippet or title, "url": link, "title": title})
        return results
    except Exception as e:
        if DEBUG:
            print(f"[TOOLS] DuckDuckGo scrape failed: {e}")
        return []


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

    if provider_id == "serpapi":
        creds = _resolve_credentials(provider_id, ["api_key"]) or {}
        creds.update(extra_creds)
        if not creds.get("api_key"):
            return {"text": "Missing credentials for serpapi: ['api_key']", "url": ""}
        if DEBUG:
            print("[TOOLS] Using external provider: serpapi")
        snippets = web_search_serpapi(query, top_k=5)
        if DEBUG:
            print(f"[TOOLS] Retrieved {len(snippets)} external snippets")
        if not snippets:
            return duckduckgo_html_scrape_fallback(query)
        text = "\n".join(s.get("text", "") for s in snippets)
        url = snippets[0].get("url", "https://serpapi.com") if snippets else ""
        return {"text": text[:4000], "url": url}

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
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        return {"text": f"Search request failed: {e}", "url": url}

    # Parse response based on provider
    if "serpapi" in provider_id.lower():
        return _parse_serpapi_response(raw, url)
    # Generic: try to extract snippets from JSON if possible
    return _parse_generic_search_response(raw, url)


def duckduckgo_html_scrape_fallback(query: str) -> dict:
    """Fallback: DuckDuckGo scrape when SerpAPI fails or returns empty."""
    snippets = duckduckgo_html_scrape(query)
    if not snippets:
        return {"text": "External search not configured. Please add provider.", "url": ""}
    text = "\n".join(s.get("text", "") for s in snippets)
    url = snippets[0].get("url", f"https://duckduckgo.com/?q={_url_encode(query)}") if snippets else ""
    return {"text": text[:4000], "url": url}


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
    Uses DuckDuckGo HTML scraping (BeautifulSoup) if possible, else returns stub.
    """
    return duckduckgo_html_scrape_fallback(query)


def tool_planner_agent(query: str, call_llm_fn=None) -> dict:
    """
    Tool Planner for BFSI Investment Research Agent.
    Returns dict: {category, recommended_providers: [...], reason}.
    On parse failure: {"category":"generic","recommended_providers":["web_search_generic"],"reason":"fallback"}
    """
    kb = load_tool_knowledge_base()
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

You are a Tool Planner for a BFSI Investment Research Agent.
Your job is to decide which external knowledge sources are most reliable to answer the user's question.

Categories include:
regulatory filings, company financials, macroeconomic data, market prices, credit ratings, financial news, generic web search.

TOOL_KNOWLEDGE_BASE:
{kb_desc}

CONFIGURED PROVIDERS (currently available):
{cfg_desc}

If the answer is likely available internally (e.g. from the PDF/annual report), return recommended_providers: [].

<|eot_id|><|start_header_id|>user<|end_header_id|>

Given the user question, output a JSON object strictly in this format:
{{
  "category": "<one of the categories>",
  "recommended_providers": ["provider1", "provider2"],
  "reason": "why these providers are suitable"
}}

Question: {query}

Output only valid JSON, no other text.
<|eot_id|><|start_header_id|>assistant<|end_header_id|>
"""

    if call_llm_fn is None:
        try:
            from local_pdf_qa import call_bedrock
            call_llm_fn = call_bedrock
        except ImportError:
            out = {"category": "generic", "recommended_providers": ["web_search_generic"], "reason": "fallback"}
            if DEBUG:
                print(f"[PLANNER] category={out['category']} providers={out['recommended_providers']}")
            return out

    raw = call_llm_fn(prompt)
    if not raw:
        out = {"category": "generic", "recommended_providers": ["serpapi"] if get_provider_config("serpapi") else ["web_search_generic"], "reason": "fallback"}
        if DEBUG:
            print(f"[PLANNER] category={out['category']} providers={out['recommended_providers']}")
        return out

    text = (raw or "").strip()
    for match in re.finditer(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", text):
        try:
            out = json.loads(match.group(0))
            if "category" in out and "recommended_providers" in out:
                out.setdefault("reason", "")
                if DEBUG:
                    print(f"[PLANNER] category={out['category']} providers={out['recommended_providers']}")
                return out
        except json.JSONDecodeError:
            continue
    try:
        out = json.loads(text)
        if "category" in out and "recommended_providers" in out:
            if DEBUG:
                print(f"[PLANNER] category={out['category']} providers={out['recommended_providers']}")
            return out
    except json.JSONDecodeError:
        pass
    # Fallback: recommend serpapi if configured, else web_search_generic
    if get_provider_config("serpapi"):
        out = {"category": "generic", "recommended_providers": ["serpapi"], "reason": "fallback (parse failed)"}
    else:
        out = {"category": "generic", "recommended_providers": ["web_search_generic"], "reason": "fallback"}
    if DEBUG:
        print(f"[PLANNER] category={out['category']} providers={out['recommended_providers']} (parse failed)")
    return out


def prompt_for_credentials(provider_id: str, required_fields: list) -> dict | None:
    """
    Human-in-the-loop: prompt user for credentials, parse, store via register_credentials.
    Returns credentials dict if successful, None otherwise.
    """
    if DEBUG:
        print(f"[CREDENTIALS] requesting credentials for provider: {provider_id}")
    print(f"Required fields: {required_fields}")
    print("Provide as JSON e.g. {{\"api_key\": \"xxx\"}} or key=value e.g. api_key=xxx")
    try:
        user_input = input("> ").strip()
    except EOFError:
        return None
    if user_input.upper() == "SKIP":
        return None
    try:
        parsed = json.loads(user_input)
        if isinstance(parsed, dict) and all(parsed.get(f) for f in required_fields):
            register_credentials(provider_id, parsed)
            return parsed
    except json.JSONDecodeError:
        pass
    creds = {}
    for part in user_input.split(","):
        if "=" in part:
            k, v = part.split("=", 1)
            creds[k.strip()] = v.strip()
    if all(creds.get(f) for f in required_fields):
        register_credentials(provider_id, creds)
        return creds
    return None


def resolve_tool_credentials(planner_output: dict, input_fn=None) -> dict:
    """
    Resolve credentials for recommended providers. Human-in-the-loop when not configured.
    Returns: {"ready_providers": [...], "skipped": [...]}
    """
    providers = planner_output.get("recommended_providers", [])
    category = planner_output.get("category", "generic")
    ready = []
    skipped = []

    for provider in providers:
        if provider == "web_search_generic":
            ready.append(provider)
            continue
        config = get_provider_config(provider)
        if not config:
            print(f"External tool '{provider}' is recommended for category '{category}'.")
            print("This tool is not configured.")
            print("Please add it to tool_config.json or type SKIP.")
            if input_fn:
                user_input = input_fn()
            else:
                try:
                    user_input = input("> ").strip()
                except EOFError:
                    user_input = "SKIP"
            if user_input.upper() == "SKIP":
                skipped.append(provider)
            continue

        required = config.get("required_fields", [])
        creds = _resolve_credentials(provider, required)
        if creds:
            ready.append(provider)
            continue

        if provider == "serpapi":
            print("External web search requires SerpAPI key. Enter now or SKIP.")
        else:
            print(f"External tool '{provider}' is recommended for category '{category}'.")
            print("Credentials are required for this tool.")
            print("Please provide credentials now or type SKIP.")
        if DEBUG:
            print(f"[CREDENTIALS] requesting credentials for provider: {provider}")
        creds = prompt_for_credentials(provider, required)
        if creds:
            ready.append(provider)
        else:
            skipped.append(provider)

    if not ready:
        if DEBUG:
            print("[TOOLS] fallback to generic web search")
        ready.append("web_search_generic")
    return {"ready_providers": ready, "skipped": skipped}


def call_api_tool(provider_id: str, endpoint_template: str, params: dict) -> dict:
    """
    Generic API call using endpoint_template. Params fill {key} placeholders.
    Returns dict with 'text' and 'url' keys.
    """
    url = endpoint_template
    for k, v in params.items():
        url = url.replace("{" + k + "}", _url_encode(str(v)))
    try:
        import urllib.request
        req = urllib.request.Request(url, headers={"User-Agent": "BFSI-PDF-QA/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        return {"text": f"API request failed: {e}", "url": url}
    return _parse_generic_search_response(raw, url)


def _tool_error_result(provider: str, category: str) -> dict:
    """Structured empty result on tool failure. Never blocks."""
    return {
        "tool": provider,
        "category": category,
        "text": "Tool failed or unavailable",
        "url": "",
        "error": True,
    }


def execute_external_tools(ready_providers: list, query: str, category: str) -> list:
    """
    Execute external tools for each ready provider.
    All calls wrapped in try/except; on failure returns structured error result.
    Returns list of provenance-tagged snippets or error results.
    """
    results = []
    for provider in ready_providers:
        if DEBUG:
            print(f"[TOOLS] executed provider: {provider}")
        config = get_provider_config(provider)
        cat = category
        if config:
            cat = config.get("category", category)
        try:
            if cat == "generic" or provider == "web_search_generic":
                r = web_search_via_provider(query, provider)
            else:
                config = config or {}
                endpoint_tpl = config.get("endpoint_template", "")
                if endpoint_tpl:
                    creds = _resolve_credentials(provider, config.get("required_fields", [])) or {}
                    params = {"q": query, **creds}
                    r = call_api_tool(provider, endpoint_tpl, params)
                else:
                    r = web_search_via_provider(query, provider)

            text = r.get("text", "")
            url = r.get("url", "")
            if text and "not configured" not in text.lower() and "failed" not in text.lower():
                results.append({
                    "type": "external",
                    "tool": provider,
                    "category": cat,
                    "url": url,
                    "text": text,
                    "fetched_at": datetime.utcnow().isoformat() + "Z",
                })
                break
        except Exception as e:
            if DEBUG:
                print(f"[TOOLS] provider {provider} failed: {e}")
            results.append(_tool_error_result(provider, cat))
    if results and DEBUG and not any(r.get("error") for r in results):
        print(f"[TOOLS] Retrieved {len(results)} external snippets")
    if not results or all(r.get("error") for r in results):
        if "web_search_generic" not in ready_providers:
            try:
                r = web_search_generic(query)
                results = [{
                    "type": "external",
                    "tool": "web_search_generic",
                    "category": "generic",
                    "url": r.get("url", ""),
                    "text": r.get("text", ""),
                    "fetched_at": datetime.utcnow().isoformat() + "Z",
                }]
            except Exception:
                results = [_tool_error_result("web_search_generic", "generic")]
    return results


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


def run_external_search(query: str, call_llm_fn=None, input_fn=None):
    """
    Full flow: plan -> resolve credentials -> execute tools.
    Returns (combined_external_text, provenance_list).
    provenance_list: [{"type":"external","tool",...}, ...]
    """
    plan = tool_planner_agent(query, call_llm_fn)
    providers = plan.get("recommended_providers", [])
    category = plan.get("category", "generic")

    if not providers:
        return "", []

    resolved = resolve_tool_credentials(plan, input_fn=input_fn)
    ready = resolved.get("ready_providers", [])
    if not ready:
        return "", []

    snippets = execute_external_tools(ready, query, category)
    text_parts = [s.get("text", "") for s in snippets if s.get("text")]
    return "\n\n".join(text_parts), snippets


def run_external_search_forced(query: str, call_llm_fn=None):
    """
    Force external search via SerpAPI regardless of planner recommendation.
    Used when no internal evidence is found.
    Returns (combined_external_text, provenance_list).
    """
    # Directly execute SerpAPI without consulting planner
    category = "generic"
    ready_providers = ["serpapi"]
    
    # Verify SerpAPI is configured
    config = get_provider_config("serpapi")
    if not config:
        ready_providers = ["web_search_generic"]
    
    snippets = execute_external_tools(ready_providers, query, category)
    text_parts = [s.get("text", "") for s in snippets if s.get("text")]
    return "\n\n".join(text_parts), snippets
