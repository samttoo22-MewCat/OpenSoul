import sys
from pathlib import Path

# 設定專案根目錄
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(PROJECT_ROOT))

from soul.core.config import settings
from soul.memory.graph import get_graph_client, initialize_schemas

def force_reset_db():
    print("--- 💥 強制重置資料庫 (含索引刪除) ---")
    print(f"目標維度: {settings.soul_embedding_dim}")
    
    client = get_graph_client()
    
    # 取得圖譜名稱
    graph_names = [
        settings.soul_semantic_graph,
        settings.soul_episodic_graph,
        settings.soul_procedural_graph
    ]
    
    for graph_name in graph_names:
        print(f"正在移除圖譜: {graph_name} ...")
        try:
            # 直接使用 Redis 指令刪除 Key，這是最徹底的
            # FalkorDB 的圖譜本質上是 Redis 裡的 Key
            client._client.connection.delete(graph_name)
            print(f"  ✅ 圖譜 {graph_name} 已徹底刪除。")
        except Exception as e:
            print(f"  ❌ 刪除 {graph_name} 失敗: {e}")

    print("\n重新執行初始化邏輯...")
    try:
        initialize_schemas(client)
        print("✅ 全新 3072 維度索引已建立！")
    except Exception as e:
        print(f"❌ 初始化失敗: {e}")

if __name__ == "__main__":
    force_reset_db()
