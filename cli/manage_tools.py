#!/usr/bin/env python3
"""
manage_tools.py - CLI for managing external tool providers and credentials.

Usage:
  python manage_tools.py list
  python manage_tools.py add-provider --id PROVIDER_ID --category CATEGORY [--endpoint TEMPLATE] [--required FIELD1,FIELD2]
  python manage_tools.py add-credentials --provider PROVIDER_ID --field KEY=VALUE [--field KEY2=VALUE2]
"""

import argparse
import json
import sys
from pathlib import Path

# Add parent directory to path to import tools from agent
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.tools import (
    list_configured_providers,
    get_provider_config,
    register_credentials,
    TOOL_CONFIG_PATH,
)


def cmd_list(args):
    """List configured providers."""
    providers = list_configured_providers()
    if not providers:
        print("No providers configured.")
        return 0
    for pid in providers:
        cfg = get_provider_config(pid)
        cat = cfg.get("category", "") if cfg else ""
        req = cfg.get("required_fields", []) if cfg else []
        print(f"  {pid}: category={cat}, required={req}")
    return 0


def cmd_add_provider(args):
    """Add a provider to tool_config.json."""
    provider_id = args.id
    category = args.category
    endpoint = args.endpoint or ""
    required = [f.strip() for f in (args.required or "").split(",") if f.strip()]

    config = {"providers": {}}
    if TOOL_CONFIG_PATH.exists():
        try:
            with open(TOOL_CONFIG_PATH, "r", encoding="utf-8") as f:
                config = json.load(f)
        except Exception as e:
            print(f"Error loading config: {e}", file=sys.stderr)
            return 1
    if not isinstance(config.get("providers"), dict):
        config["providers"] = {}

    config["providers"][provider_id] = {
        "category": category,
        "endpoint_template": endpoint,
        "required_fields": required,
    }
    try:
        with open(TOOL_CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)
        print(f"Added provider: {provider_id}")
        return 0
    except Exception as e:
        print(f"Error writing config: {e}", file=sys.stderr)
        return 1


def cmd_add_credentials(args):
    """Add credentials for a provider."""
    provider_id = args.provider
    fields = {}
    for f in args.field or []:
        if "=" in f:
            k, v = f.split("=", 1)
            fields[k.strip()] = v.strip()
    if not fields:
        print("Provide at least one --field KEY=VALUE", file=sys.stderr)
        return 1
    try:
        register_credentials(provider_id, fields)
        print(f"Stored credentials for: {provider_id}")
        return 0
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def main():
    parser = argparse.ArgumentParser(description="Manage BFSI tool providers and credentials")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="List configured providers")

    add_prov = sub.add_parser("add-provider", help="Add a provider to tool_config.json")
    add_prov.add_argument("--id", "-i", required=True, help="Provider ID")
    add_prov.add_argument("--category", "-c", required=True, help="Category (generic, regulatory, financials, etc.)")
    add_prov.add_argument("--endpoint", "-e", help="Endpoint template with {q}, {api_key}, etc.")
    add_prov.add_argument("--required", "-r", help="Comma-separated required fields (e.g. api_key)")

    add_cred = sub.add_parser("add-credentials", help="Store credentials for a provider")
    add_cred.add_argument("--provider", "-p", required=True, help="Provider ID")
    add_cred.add_argument("--field", "-f", action="append", help="KEY=VALUE (repeat for multiple)")

    args = parser.parse_args()

    if args.command == "list":
        return cmd_list(args)
    if args.command == "add-provider":
        return cmd_add_provider(args)
    if args.command == "add-credentials":
        return cmd_add_credentials(args)
    return 1


if __name__ == "__main__":
    sys.exit(main())
