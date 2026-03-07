import sys
from pathlib import Path

# 設定專案根目錄
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(PROJECT_ROOT))

from soul.core.config import settings
from soul.memory.graph import get_graph_client, initialize_schemas

def reinit_database():
    print("--- 重新初始化資料庫索引 ---")
    print(f"當前設定維度: {settings.soul_embedding_dim}")
    
    client = get_graph_client()
    
    # 這裡我們選擇直接刪除現有的向量索引，以便 initialize_schemas 重新建立
    graphs = [
        ("Semantic", client.semantic),
        ("Episodic", client.episodic),
        ("Procedural", client.procedural)
    ]
    
    for name, graph in graphs:
        print(f"清理 {name} 圖譜的舊索引...")
        try:
            # 嘗試刪除向量索引
            if name == "Semantic":
                graph.query("DROP INDEX FOR (c:Concept) ON (c.embedding)")
            elif name == "Episodic":
                graph.query("DROP INDEX FOR (e:Episode) ON (e.embedding)")
            elif name == "Procedural":
                graph.query("DROP INDEX FOR (p:Procedure) ON (p.embedding)")
            print(f"  ✅ {name} 向量索引已刪除")
        except Exception as e:
            print(f"  ⚠️ {name} 向量索引刪除失敗 (可能不存在): {e}")

    print("\n執行初始化邏輯 (建立新維度索引)...")
    try:
        initialize_schemas(client)
        print("✅ 初始化成功！所有索引已更新為新維度。")
    except Exception as e:
        print(f"❌ 初始化失敗: {e}")

if __name__ == "__main__":
    reinit_database()
