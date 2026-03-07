import os
import sys
from pathlib import Path
from openai import OpenAI

# 設定專案根目錄
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(PROJECT_ROOT))

from soul.core.config import settings

def check_embedding_dim():
    print(f"--- 診斷 Embedding 維度 ---")
    print(f"Provider: {settings.soul_llm_provider}")
    print(f"Model: {settings.soul_embedding_model}")
    print(f"Expected Dim in Config: {settings.soul_embedding_dim}")
    
    if settings.soul_llm_provider.lower() == "openrouter":
        client = OpenAI(
            api_key=settings.openrouter_api_key or settings.openai_api_key,
            base_url=settings.openrouter_base_url
        )
    else:
        client = OpenAI(api_key=settings.openai_api_key)
        
    try:
        resp = client.embeddings.create(
            input="test",
            model=settings.soul_embedding_model
        )
        vec = resp.data[0].embedding
        actual_dim = len(vec)
        print(f"✅ 成功獲取 Embedding")
        print(f"📌 實際輸出維度: {actual_dim}")
        
        if actual_dim != settings.soul_embedding_dim:
            print(f"❌ 警告：配置與實際維度不符！({settings.soul_embedding_dim} vs {actual_dim})")
        else:
            print(f"✅ 配置與實際維度相符。")
            
    except Exception as e:
        print(f"❌ 獲取失敗: {e}")

if __name__ == "__main__":
    check_embedding_dim()
