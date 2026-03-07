"""
soul/integrations/gmail_poller.py

Gmail API 輪詢器：透過 OAuth2 定期抓取未讀信件，以 JSON 持久化快取。
"""

from __future__ import annotations

import base64
import email
import json
import logging
import os
from datetime import datetime
from email.header import decode_header
from pathlib import Path
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from soul.core.config import settings

logger = logging.getLogger(__name__)

# 修改權限（讀取並標示為已讀）
SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]
MAX_CACHE_SIZE = 50


def _decode_mime(value: str | bytes, charset: str | None = None) -> str:
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
    if not raw:
        return ""
    parts = decode_header(raw)
    decoded = []
    for part, enc in parts:
        if isinstance(part, bytes):
            decoded.append(_decode_mime(part, enc))
        else:
            decoded.append(part)
    return "".join(decoded)


class GmailPoller:
    def __init__(self) -> None:
        self._cache_path: Path = settings.workspace_path / "gmail_cache.json"
        self._creds_path: Path = settings.workspace_path / "credentials.json"
        self._token_path: Path = settings.workspace_path / "token.json"
        
        self._creds = None
        self._service = None
        self._enabled = self._creds_path.exists() or self._token_path.exists()
        
        if self._enabled:
            self._authenticate()
            
        self._cache: list[dict[str, Any]] = self._load_cache()

    def _authenticate(self) -> None:
        """處理 OAuth2 認證，如果需要會彈出瀏覽器。"""
        if self._token_path.exists():
            self._creds = Credentials.from_authorized_user_file(str(self._token_path), SCOPES)
            
        if not self._creds or not self._creds.valid:
            if self._creds and self._creds.expired and self._creds.refresh_token:
                self._creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    str(self._creds_path), SCOPES
                )
                self._creds = flow.run_local_server(port=0)
                
            with open(self._token_path, "w", encoding="utf-8") as token:
                token.write(self._creds.to_json())
                
        self._service = build("gmail", "v1", credentials=self._creds)
        logger.info("Gmail API 認證成功")

    def fetch_unseen(self) -> int:
        if not self._enabled or not self._service:
            logger.debug("Gmail 憑證未載入，跳過輪詢")
            return 0
        try:
            return self._fetch_impl()
        except Exception as exc:
            logger.error("Gmail API 輪詢失敗：%s", exc)
            return 0

    def get_cached_emails(self, limit: int = 10) -> list[dict[str, Any]]:
        return self._cache[:limit]

    def get_cache_stats(self) -> dict[str, Any]:
        return {
            "enabled": self._enabled,
            "cached_count": len(self._cache),
            "oldest": self._cache[-1]["date"] if self._cache else None,
            "newest": self._cache[0]["date"] if self._cache else None,
        }

    def _fetch_impl(self) -> int:
        new_count = 0
        
        # 查詢最近三天內的信件 (包含已讀與未讀)
        results = self._service.users().messages().list(userId="me", q="newer_than:3d").execute()
        messages = results.get("messages", [])

        if not messages:
            logger.debug("沒有新的信件")
            return 0

        logger.info("發現 %d 封信件", len(messages))

        for msg_item in messages:
            msg_id = msg_item["id"]
            try:
                # 抓取完整 metadata
                message = self._service.users().messages().get(userId="me", id=msg_id, format="full").execute()
                
                parsed = self._parse_message(message)
                if parsed:
                    self._insert_email(parsed)
                    new_count += 1
                    
                # 移除 UNREAD 標籤（標記為已讀）
                self._service.users().messages().modify(
                    userId="me", 
                    id=msg_id, 
                    body={"removeLabelIds": ["UNREAD"]}
                ).execute()
                
            except Exception as exc:
                logger.warning("處理信件 %s 失敗：%s", msg_id, exc)

        if new_count > 0:
            self._save_cache()
            logger.info("Gmail：新增 %d 封信到快取（共 %d 封）", new_count, len(self._cache))

        return new_count

    def _parse_message(self, message: dict[str, Any]) -> dict[str, Any] | None:
        """解析 Gmail API 回傳的 message 物件。"""
        headers = {header["name"].lower(): header["value"] for header in message["payload"].get("headers", [])}
        
        sender = headers.get("from", "")
        subject = headers.get("subject", "（無主旨）")
        date_str = headers.get("date", "")
        
        body = self._get_body_from_payload(message["payload"])

        return {
            "id": message["id"],
            "from": sender,
            "subject": subject,
            "date": date_str,
            "preview": body[:500],
            "fetched_at": datetime.utcnow().isoformat(),
        }

    def _get_body_from_payload(self, payload: dict[str, Any]) -> str:
        """遞迴提取 body 內容。"""
        if "data" in payload.get("body", {}):
            try:
                data = payload["body"]["data"]
                return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace").strip()
            except BaseException:
                pass
        
        if "parts" in payload:
            text_parts = []
            for part in payload["parts"]:
                if part.get("mimeType") == "text/plain":
                    text_parts.append(self._get_body_from_payload(part))
                elif part.get("mimeType") == "multipart/alternative":
                    text_parts.append(self._get_body_from_payload(part))
            return "\n".join(text_parts).strip()
            
        return ""

    def _insert_email(self, email_dict: dict[str, Any]) -> None:
        existing_ids = {e["id"] for e in self._cache}
        if email_dict["id"] in existing_ids:
            return
        self._cache.insert(0, email_dict)
        if len(self._cache) > MAX_CACHE_SIZE:
            self._cache = self._cache[:MAX_CACHE_SIZE]

    def _load_cache(self) -> list[dict[str, Any]]:
        if not self._cache_path.exists():
            return []
        try:
            with open(self._cache_path, encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return data
        except Exception:
            pass
        return []

    def _save_cache(self) -> None:
        try:
            self._cache_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._cache_path, "w", encoding="utf-8") as f:
                json.dump(self._cache, f, ensure_ascii=False, indent=2)
        except Exception as exc:
            logger.error("Gmail 快取寫入失敗：%s", exc)
