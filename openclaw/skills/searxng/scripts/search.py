#!/usr/bin/env python3
"""
SearXNG search script for OpenClaw.
Queries the local SearXNG instance and prints results.

Usage:
    python search.py --query "search terms" [--categories "general"] [--language "en"] [--max-results 5] [--json]
"""

import argparse
import json
import sys
import urllib.parse
import urllib.request


SEARXNG_URL = "http://searxng:8888"
FALLBACK_URL = "http://localhost:8888"


def search(query: str, categories: str = "general", language: str = "en-US",
           max_results: int = 5, as_json: bool = False) -> None:
    params = urllib.parse.urlencode({
        "q": query,
        "categories": categories,
        "language": language,
        "format": "json",
    })

    for base_url in [SEARXNG_URL, FALLBACK_URL]:
        url = f"{base_url}/search?{params}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "OpenClaw-SearXNG-Skill/1.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
            break
        except Exception:
            if base_url == FALLBACK_URL:
                print("ERROR: Could not connect to SearXNG. Is the service running?", file=sys.stderr)
                print("  Start with: docker compose -f openclaw/docker-compose.yml up searxng -d", file=sys.stderr)
                sys.exit(1)
            continue

    results = data.get("results", [])[:max_results]

    if as_json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
        return

    if not results:
        print(f"No results found for: {query}")
        return

    print(f"Search results for: {query}  [{categories}]\n")
    for i, r in enumerate(results, 1):
        title = r.get("title", "(no title)")
        url_res = r.get("url", "")
        content = r.get("content", "").strip()
        print(f"{i}. {title}")
        print(f"   {url_res}")
        if content:
            snippet = content[:200] + ("..." if len(content) > 200 else "")
            print(f"   {snippet}")
        print()


def main() -> None:
    parser = argparse.ArgumentParser(description="Search using local SearXNG instance")
    parser.add_argument("--query", "-q", required=True, help="Search query")
    parser.add_argument("--categories", "-c", default="general",
                        help="Search categories (general, news, it, science, images, videos, social media)")
    parser.add_argument("--language", "-l", default="en-US", help="Language (e.g. en-US, zh-TW)")
    parser.add_argument("--max-results", "-n", type=int, default=5, help="Number of results to return")
    parser.add_argument("--json", action="store_true", help="Output raw JSON")
    args = parser.parse_args()

    search(
        query=args.query,
        categories=args.categories,
        language=args.language,
        max_results=args.max_results,
        as_json=args.json,
    )


if __name__ == "__main__":
    main()
