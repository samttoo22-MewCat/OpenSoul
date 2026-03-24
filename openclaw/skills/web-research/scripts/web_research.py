#!/usr/bin/env python3
"""
web_research.py — SearXNG + Jina Reader 整合搜尋工具

用法：
    python scripts/web_research.py --action search   --query "AI 2025"
    python scripts/web_research.py --action fetch    --url "https://example.com"
    python scripts/web_research.py --action research --query "AI 2025" --fetch-top 3
"""

import argparse
import json
import sys
import traceback
import urllib.parse
import urllib.request

SEARXNG_URLS = ["http://searxng:8888", "http://localhost:8888"]
JINA_BASE = "https://r.jina.ai/"


# ── SearXNG ──────────────────────────────────────────────────────────────────

def searxng_search(query: str, categories: str = "general", language: str = "en-US",
                   max_results: int = 5) -> list[dict]:
    params = urllib.parse.urlencode({
        "q": query,
        "categories": categories,
        "language": language,
        "format": "json",
    })
    last_err = None
    for base_url in SEARXNG_URLS:
        url = f"{base_url}/search?{params}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "OpenClaw-WebResearch/1.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
            return data.get("results", [])[:max_results]
        except Exception as e:
            last_err = e
            continue
    raise RuntimeError(
        f"無法連接 SearXNG（{SEARXNG_URLS}）\n"
        f"請先啟動服務：docker compose -f openclaw/docker-compose.yml up searxng -d\n"
        f"原始錯誤：{last_err}"
    )


# ── Jina Reader ───────────────────────────────────────────────────────────────

def jina_fetch(url: str, timeout: int = 15) -> str:
    """透過 r.jina.ai 取得乾淨的 Markdown 頁面內容。"""
    jina_url = JINA_BASE + url
    req = urllib.request.Request(
        jina_url,
        headers={
            "User-Agent": "OpenClaw-WebResearch/1.0",
            "Accept": "text/markdown",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


# ── Actions ───────────────────────────────────────────────────────────────────

def action_search(args) -> None:
    results = searxng_search(
        query=args.query,
        categories=args.categories,
        language=args.language,
        max_results=args.max_results,
    )

    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
        return

    if not results:
        print(f"找不到結果：{args.query}")
        return

    print(f"搜尋結果：{args.query}  [{args.categories}]\n")
    for i, r in enumerate(results, 1):
        title = r.get("title", "(無標題)")
        url = r.get("url", "")
        content = r.get("content", "").strip()
        print(f"{i}. {title}")
        print(f"   {url}")
        if content:
            snippet = content[:200] + ("…" if len(content) > 200 else "")
            print(f"   {snippet}")
        print()


def action_fetch(args) -> None:
    if not args.url:
        print("ERROR: --action fetch 需要 --url 參數", file=sys.stderr)
        sys.exit(1)

    content = jina_fetch(args.url, timeout=args.timeout)

    if args.json:
        print(json.dumps({"url": args.url, "content": content}, ensure_ascii=False, indent=2))
        return

    print(f"# 頁面內容：{args.url}\n")
    print(content)


def action_research(args) -> None:
    if not args.query:
        print("ERROR: --action research 需要 --query 參數", file=sys.stderr)
        sys.exit(1)

    # 1. 搜尋
    results = searxng_search(
        query=args.query,
        categories=args.categories,
        language=args.language,
        max_results=args.max_results,
    )

    if not results:
        print(f"找不到結果：{args.query}")
        return

    fetch_top = min(args.fetch_top, len(results))
    output = {
        "query": args.query,
        "search_results": results,
        "fetched_pages": [],
    }

    # 2. 對前 N 個結果抓取完整內容
    for r in results[:fetch_top]:
        url = r.get("url", "")
        if not url:
            continue
        try:
            content = jina_fetch(url, timeout=args.timeout)
            output["fetched_pages"].append({"url": url, "title": r.get("title", ""), "content": content})
        except Exception as e:
            print(f"[WARN] 無法抓取 {url}：{e}", file=sys.stderr)
            output["fetched_pages"].append({"url": url, "title": r.get("title", ""), "error": str(e)})

    if args.json:
        print(json.dumps(output, ensure_ascii=False, indent=2))
        return

    # 人類可讀格式
    print(f"# 研究結果：{args.query}\n")
    print(f"## 搜尋結果（共 {len(results)} 筆）\n")
    for i, r in enumerate(results, 1):
        title = r.get("title", "(無標題)")
        url = r.get("url", "")
        snippet = r.get("content", "").strip()[:150]
        marker = " ← [已抓取完整內容]" if i <= fetch_top else ""
        print(f"{i}. {title}{marker}")
        print(f"   {url}")
        if snippet:
            print(f"   {snippet}…")
        print()

    print("---\n")
    for page in output["fetched_pages"]:
        print(f"## {page.get('title') or page['url']}")
        print(f"來源：{page['url']}\n")
        if "error" in page:
            print(f"[抓取失敗：{page['error']}]\n")
        else:
            print(page["content"])
        print("\n---\n")


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="SearXNG + Jina Reader 整合網頁研究工具"
    )
    parser.add_argument("--action", choices=["search", "fetch", "research"], required=True,
                        help="search=搜尋, fetch=抓取單頁, research=搜尋+抓取")
    parser.add_argument("--query", "-q", help="搜尋關鍵字（search / research 用）")
    parser.add_argument("--url", "-u", help="目標 URL（fetch 用）")
    parser.add_argument("--categories", "-c", default="general",
                        help="搜尋類別：general, news, it, science, images, videos, social media")
    parser.add_argument("--language", "-l", default="en-US",
                        help="語言（如 en-US、zh-TW）")
    parser.add_argument("--max-results", "-n", type=int, default=5,
                        help="搜尋結果數量上限")
    parser.add_argument("--fetch-top", type=int, default=3,
                        help="research 模式下抓取前幾筆完整內容（預設 3）")
    parser.add_argument("--timeout", type=int, default=15,
                        help="Jina Reader 請求逾時秒數（預設 15）")
    parser.add_argument("--json", action="store_true", help="輸出原始 JSON")
    args = parser.parse_args()

    try:
        if args.action == "search":
            action_search(args)
        elif args.action == "fetch":
            action_fetch(args)
        elif args.action == "research":
            action_research(args)
    except Exception:
        print("--- TRACEBACK START ---", file=sys.stderr)
        traceback.print_exc()
        print("--- TRACEBACK END ---", file=sys.stderr)
        err = {"status": "error", "error": str(sys.exc_info()[1]), "traceback": traceback.format_exc()}
        print(json.dumps(err, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
