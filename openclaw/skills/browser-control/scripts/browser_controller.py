#!/usr/bin/env python3
import argparse
import json
import os
import sys
import time
import traceback
from pathlib import Path

# 嘗試導入 seleniumbase 與 markdownify
try:
    from seleniumbase import SB
    from markdownify import markdownify as md
except ImportError:
    print("Error: Required packages not installed. Please run 'pip install seleniumbase markdownify'")
    sys.exit(1)

def main():
    parser = argparse.ArgumentParser(description="SeleniumBase UC Mode Controller for openSOUL")
    parser.add_argument("--action", choices=["fetch", "screenshot", "interact"], required=True, help="Action to perform")
    parser.add_argument("--url", required=True, help="Target URL")
    parser.add_argument("--steps", help="JSON string for interactions (for 'interact' action)")
    parser.add_argument("--output_dir", default="workspace/browser_outputs", help="Directory to save screenshots or results")
    args = parser.parse_args()

    # 確保輸出目錄存在 (使用絕對路徑)
    # 假設腳本在 skills/browser-control/scripts/，根目錄在 ../../../
    root_dir = Path(__file__).resolve().parent.parent.parent.parent
    output_path = root_dir / args.output_dir
    output_path.mkdir(parents=True, exist_ok=True)

    try:
        results = {
            "status": "success",
            "timestamp": time.time(),
            "action": args.action,
            "url": args.url
        }

        # 啟動 SeleniumBase (UC Mode)
        # headless=False 讓使用者在 Windows 上看得到視窗
        with SB(uc=True, headless=False, ad_block=True, incognito=True) as sb:
            # 開啟網頁並嘗試自動處理 Cloudflare
            sb.uc_open_with_reconnect(args.url, reconnect_time=4)
            
            # 等待 body 載入
            sb.wait_for_element("body", timeout=10)

            if args.action == "fetch":
                results["title"] = sb.get_page_title()
                results["current_url"] = sb.get_current_url()
                
                # 獲取渲染後的完整 HTML 並轉為 Markdown
                raw_html = sb.get_page_source()
                # 簡單清理：移除 script, style, nav, footer 等不重要的標籤
                markdown_content = md(raw_html, strip=['script', 'style', 'nav', 'footer', 'header'])
                results["content"] = markdown_content.strip()
                
            elif args.action == "screenshot":
                filename = f"screenshot_{int(time.time())}.png"
                filepath = output_path / filename
                sb.save_screenshot(str(filepath))
                results["screenshot_path"] = str(filepath.absolute())
                results["title"] = sb.get_page_title()

            elif args.action == "interact":
                if args.steps:
                    try:
                        steps = json.loads(args.steps)
                        for i, step in enumerate(steps):
                            stype = step.get("type", "").lower()
                            selector = step.get("selector")
                            
                            if stype == "click":
                                sb.uc_click(selector) if "uc" in step else sb.click(selector)
                            elif stype == "type":
                                text = step.get("text", "")
                                sb.type(selector, text)
                            elif stype == "wait":
                                seconds = float(step.get("seconds", 2))
                                sb.sleep(seconds)
                            elif stype == "scroll":
                                sb.scroll_to(selector) if selector else sb.scroll_to_bottom()
                            
                        results["interaction_log"] = f"Successfully executed {len(steps)} steps."
                    except json.JSONDecodeError:
                        results["status"] = "error"
                        results["error"] = "Invalid JSON in --steps"
                
                results["final_url"] = sb.get_current_url()
                results["title"] = sb.get_page_title()
                results["content"] = md(sb.get_page_source(), strip=['script', 'style', 'nav', 'footer', 'header']).strip()

        # 輸出 JSON 結果
        print(json.dumps(results, ensure_ascii=False, indent=2))

    except Exception:
        # 依照 user 規定 3：寫 try except 一定要 print 出 traceback
        print("--- TRACEBACK START ---", file=sys.stderr)
        traceback.print_exc()
        print("--- TRACEBACK END ---", file=sys.stderr)
        
        err_res = {
            "status": "error",
            "error": str(sys.exc_info()[1]),
            "traceback": traceback.format_exc()
        }
        print(json.dumps(err_res), file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
