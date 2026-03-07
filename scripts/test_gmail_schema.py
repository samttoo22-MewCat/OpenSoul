import sys
from pathlib import Path
import json

# 設定專案根目錄
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(PROJECT_ROOT))

from soul.interface.api import _build_skill_schema

def test_gmail_schema():
    print("--- 測試 Gmail Schema 解析 ---")
    schema = _build_skill_schema("gmail")
    
    if not schema:
        print("❌ 失敗：無法產生 gmail schema")
        return
        
    print(f"✅ 成功獲取 Schema")
    params = schema.get("function", {}).get("parameters", {}).get("properties", {})
    
    # 驗證關鍵參數：action
    if "action" in params:
        action = params["action"]
        print(f"📦 'action' 參數存在")
        print(f"   - Enum: {action.get('enum')}")
        print(f"   - Description: {action.get('description')}")
        
        # 核心驗證：action 的 enum 應該是 ['fetch', 'stats']
        expected_enum = ['fetch', 'stats']
        if action.get('enum') == expected_enum:
            print("   ✅ Enum 正確")
        else:
            print(f"   ❌ Enum 錯誤：預期 {expected_enum}，實際 {action.get('enum')}")
    else:
        print("❌ 錯誤：'action' 參數不存在")

    # 驗證關鍵參數：limit
    if "limit" in params:
        limit = params["limit"]
        print(f"📦 'limit' 參數存在")
        print(f"   - Type: {limit.get('type')}")
        print(f"   - Default: {limit.get('default')}")
        
        if limit.get('default') == 20:
             print("   ✅ Default 正確 (20)")
        else:
             print(f"   ❌ Default 錯誤：實際 {limit.get('default')}")
    else:
        print("❌ 錯誤：'limit' 參數不存在")

    print("\n完整 Schema 預覽：")
    print(json.dumps(schema, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    test_gmail_schema()
