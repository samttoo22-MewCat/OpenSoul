#!/usr/bin/env python3
"""
Gmail Skill Controller - OAuth2 API 整合

使用 Google API 進行郵件操作，支援 fetch 和 stats 兩個主要動作。
"""

import argparse
import json
import os
import sys
import traceback
from pathlib import Path

# 嘗試導入必要的庫
try:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build
except ImportError:
    print("Error: Google API client is not installed.")
    print("Please run: pip install google-auth-oauthlib google-auth-httplib2 google-api-python-client")
    sys.exit(1)

import base64
import email
from email.header import decode_header
from datetime import datetime

SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]
MAX_CACHE_SIZE = 50


def _decode_mime(value: str | bytes, charset: str | None = None) -> str:
    """多字符集 MIME 解碼。"""
    if isinstance(value, bytes):
        charset = charset or "utf-8"
        for enc in (charset, "utf-8", "big5", "gbk", "iso-8859-1"):
            try:
                return value.decode(enc, errors="replace")
            except (LookupError, UnicodeDecodeError):
                continue
        return value.decode("utf-8", errors="replace")
    return value


def _decode_header_value(raw: str) -> str:
    """解碼郵件頭部值。"""
    if not raw:
        return ""
    parts = decode_header(raw)
    decoded = []
    for part, enc in parts:
        if isinstance(part, bytes):
            decoded.append(_decode_mime(part, enc))
        else:
            decoded.append(part or "")
    return "".join(decoded)


class GmailController:
    def __init__(self, workspace_path: Path):
        self.workspace_path = workspace_path
        self.creds_path = workspace_path / "credentials.json"
        self.token_path = workspace_path / "token.json"
        self.cache_path = workspace_path / "gmail_cache.json"

        self.creds = None
        self.service = None
        self.cache = []

        self._authenticate()
        self._load_cache()

    def _authenticate(self) -> None:
        """OAuth2 認證流程。"""
        # 檢查是否有有效的 token
        if self.token_path.exists():
            self.creds = Credentials.from_authorized_user_file(str(self.token_path), SCOPES)

        # 如果沒有有效 token，進行新認證或刷新
        if not self.creds or not self.creds.valid:
            if self.creds and self.creds.expired and self.creds.refresh_token:
                self.creds.refresh(Request())
            else:
                # 需要新認證
                if not self.creds_path.exists():
                    raise FileNotFoundError(
                        f"credentials.json 不存在。請先將 OAuth2 認證檔放在 {self.creds_path}"
                    )
                flow = InstalledAppFlow.from_client_secrets_file(
                    str(self.creds_path), SCOPES
                )
                self.creds = flow.run_local_server(port=0)

            # 保存 token 供下次使用
            with open(self.token_path, "w", encoding="utf-8") as token_file:
                token_file.write(self.creds.to_json())

        self.service = build("gmail", "v1", credentials=self.creds)

    def fetch_emails(self, limit: int = 20) -> dict:
        """獲取並快取郵件（已讀和未讀）。"""
        try:
            # 查詢最近 3 天的信件（不限已讀/未讀，獲取所有）
            results = self.service.users().messages().list(userId="me", q="newer_than:3d").execute()
            messages = results.get("messages", [])

            new_count = 0
            for msg_item in messages:
                msg_id = msg_item["id"]
                try:
                    # 獲取完整信件
                    message = self.service.users().messages().get(
                        userId="me", id=msg_id, format="full"
                    ).execute()

                    parsed = self._parse_message(message)
                    if parsed and parsed["id"] not in {e["id"] for e in self.cache}:
                        self.cache.insert(0, parsed)
                        new_count += 1

                    # 標記為已讀
                    self.service.users().messages().modify(
                        userId="me",
                        id=msg_id,
                        body={"removeLabelIds": ["UNREAD"]}
                    ).execute()

                except Exception as e:
                    print(f"Warning: Failed to process message {msg_id}: {e}", file=sys.stderr)

            # 維持快取大小限制
            if len(self.cache) > MAX_CACHE_SIZE:
                self.cache = self.cache[:MAX_CACHE_SIZE]

            self._save_cache()

            return {
                "status": "success",
                "new_count": new_count,
                "cached_count": len(self.cache),
                "newest": self.cache[0]["date"] if self.cache else None,
                "oldest": self.cache[-1]["date"] if self.cache else None,
                "emails": self.cache[:limit]
            }

        except Exception as e:
            raise RuntimeError(f"Failed to fetch emails: {e}")

    def get_stats(self) -> dict:
        """獲取快取統計。"""
        return {
            "status": "success",
            "cached_count": len(self.cache),
            "newest": self.cache[0]["date"] if self.cache else None,
            "oldest": self.cache[-1]["date"] if self.cache else None,
        }

    def _parse_message(self, message: dict) -> dict | None:
        """解析 Gmail API 回傳的郵件。"""
        try:
            headers = {
                header["name"].lower(): header["value"]
                for header in message["payload"].get("headers", [])
            }

            from_addr = _decode_header_value(headers.get("from", ""))
            subject = _decode_header_value(headers.get("subject", "（無主旨）"))
            date_str = headers.get("date", "")

            body = self._get_body_from_payload(message["payload"])

            return {
                "id": message["id"],
                "from": from_addr,
                "subject": subject,
                "date": date_str,
                "preview": body[:500],
                "fetched_at": datetime.utcnow().isoformat(),
            }
        except Exception:
            return None

    def _get_body_from_payload(self, payload: dict) -> str:
        """遞迴提取郵件內容。"""
        if "data" in payload.get("body", {}):
            try:
                data = payload["body"]["data"]
                return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace").strip()
            except Exception:
                pass

        if "parts" in payload:
            text_parts = []
            for part in payload["parts"]:
                mime_type = part.get("mimeType", "")
                if mime_type in ("text/plain", "multipart/alternative"):
                    text_parts.append(self._get_body_from_payload(part))
            return "\n".join(text_parts).strip()

        return ""

    def _load_cache(self) -> None:
        """從本地 JSON 讀取快取。"""
        if not self.cache_path.exists():
            return
        try:
            with open(self.cache_path, encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    self.cache = data
        except Exception:
            pass

    def _save_cache(self) -> None:
        """將快取保存到 JSON。"""
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.cache_path, "w", encoding="utf-8") as f:
                json.dump(self.cache, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"Warning: Failed to save cache: {e}", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description="Gmail OAuth2 Controller")
    parser.add_argument("--action", choices=["fetch", "stats"], required=True, help="Action to perform")
    parser.add_argument("--limit", type=int, default=20, help="Number of emails to return (for fetch action, default 20)")
    parser.add_argument("--workspace", default="workspace", help="Workspace directory path")

    args = parser.parse_args()

    # 計算工作區路徑
    if not Path(args.workspace).is_absolute():
        # 從腳本位置往上回溯到項目根：scripts(parents[0]) → gmail(parents[1]) → skills(parents[2]) → openclaw(parents[3]) → root(parents[4])
        root_dir = Path(__file__).resolve().parents[4]
        workspace_path = root_dir / args.workspace
    else:
        workspace_path = Path(args.workspace)

    try:
        controller = GmailController(workspace_path)

        if args.action == "fetch":
            result = controller.fetch_emails(limit=args.limit)
        elif args.action == "stats":
            result = controller.get_stats()

        print(json.dumps(result, ensure_ascii=False, indent=2))

    except Exception as e:
        print("--- TRACEBACK START ---", file=sys.stderr)
        traceback.print_exc()
        print("--- TRACEBACK END ---", file=sys.stderr)

        error_result = {
            "status": "error",
            "error": str(e),
            "traceback": traceback.format_exc()
        }
        print(json.dumps(error_result, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
