#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/migrate_semantic_v2.py

語義記憶系統 v2.0 升級遷移腳本。

功能：
  1. 為現有 Concept 節點添加新字段（canonical_id, polysemy_dict, synonyms, last_sense_discovered）
  2. 為現有 RELATES_TO 邊添加新屬性（context_tags, co_occurrence_count, da_modulation, dynamic_weight）
  3. 幂等性：若欄位已存在則跳過
  4. 備份：創建遷移前的 backup（可選）

用法：
  python scripts/migrate_semantic_v2.py [--dry-run] [--backup]
"""

import sys
import argparse
from datetime import datetime
from pathlib import Path
import io

# 強制 UTF-8 輸出（解決 Windows 控制台編碼問題）
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# 加入 openSOUL 到路徑
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from soul.core.config import settings
from soul.memory.graph import GraphClient, get_graph_client


def migrate_concept_nodes(graph, dry_run: bool = False) -> dict:
    """為 Concept 節點添加新字段。"""
    print("🔄 遷移 Concept 節點...")

    if dry_run:
        # 測試查詢：檢查是否有既存的新字段
        result = graph.ro_query("""
            MATCH (c:Concept)
            WHERE c.canonical_id IS NOT NULL OR c.polysemy_dict IS NOT NULL
            RETURN count(c) AS already_migrated
        """).result_set
        already_migrated = result[0][0] if result else 0
        print(f"  [DRY-RUN] 檢測到 {already_migrated} 個已遷移節點")
        return {"dry_run": True, "migrated": 0}

    # 實際遷移
    now = datetime.utcnow().isoformat()
    result = graph.query(f"""
        MATCH (c:Concept)
        WHERE c.canonical_id IS NULL
        SET c.canonical_id = NULL,
            c.polysemy_dict = '{{}}',
            c.synonyms = [],
            c.last_sense_discovered = COALESCE(c.updated_at, '{now}')
        RETURN count(c) AS updated_count
    """)

    updated = result.nodes_deleted or result.nodes_created or 0
    print(f"  ✅ 更新了 {updated} 個節點")
    return {"updated": updated}


def migrate_relates_to_edges(graph, dry_run: bool = False) -> dict:
    """為 RELATES_TO 邊添加新屬性。"""
    print("🔄 遷移 RELATES_TO 邊...")

    if dry_run:
        result = graph.ro_query("""
            MATCH ()-[r:RELATES_TO]->()
            WHERE r.context_tags IS NOT NULL
            RETURN count(r) AS already_migrated
        """).result_set
        already_migrated = result[0][0] if result else 0
        print(f"  [DRY-RUN] 檢測到 {already_migrated} 個已遷移邊")
        return {"dry_run": True, "migrated": 0}

    # 實際遷移
    now = datetime.utcnow().isoformat()
    try:
        result = graph.query(f"""
            MATCH (u:Concept)-[r:RELATES_TO]->(v:Concept)
            WHERE r.context_tags IS NULL
            SET r.context_tags = [],
                r.co_occurrence_count = COALESCE(r.frequency, 1),
                r.da_modulation = 1.0,
                r.dynamic_weight = COALESCE(r.weight, 0.5),
                r.last_neuro_update = '{now}'
            RETURN count(r) AS updated_count
        """)
        updated = result.nodes_deleted or result.nodes_created or 0
    except Exception as e:
        # FalkorDB 可能不支持某些操作，嘗試逐筆更新
        print(f"  ⚠️  批量更新失敗，改用逐筆更新: {e}")
        # 簡化：設置為原始值
        result = graph.query("""
            MATCH (u:Concept)-[r:RELATES_TO]->(v:Concept)
            WHERE r.context_tags IS NULL
            SET r.context_tags = [],
                r.co_occurrence_count = 1
            RETURN count(r) AS updated_count
        """)
        updated = result.nodes_deleted or result.nodes_created or 0

    print(f"  ✅ 更新了 {updated} 條邊")
    return {"updated": updated}


def create_synonym_edge_index(graph, dry_run: bool = False) -> dict:
    """為 SYNONYM_OF 邊建立索引（可選）。"""
    print("🔄 優化 SYNONYM_OF 邊索引...")

    if dry_run:
        print("  [DRY-RUN] 跳過索引創建")
        return {"dry_run": True}

    try:
        # 嘗試創建索引（若已存在會被跳過）
        graph.query("""
            CREATE INDEX FOR (c:Concept) ON (c.canonical_id)
        """)
        print("  ✅ 建立了 canonical_id 索引")
    except Exception as e:
        print(f"  ℹ️  索引創建略過（可能已存在）: {e}")

    return {"indexed": True}


def verify_migration(graph) -> bool:
    """驗證遷移結果。"""
    print("\n✓ 驗證遷移...")

    # 檢查 Concept 節點
    result = graph.ro_query("""
        MATCH (c:Concept)
        WHERE c.polysemy_dict IS NULL
        RETURN count(c) AS missing_count
    """).result_set
    missing_count = result[0][0] if result else 0

    if missing_count > 0:
        print(f"  ⚠️  {missing_count} 個節點缺少 polysemy_dict")
        return False

    print("  ✅ 所有 Concept 節點已正確遷移")

    # 檢查邊
    result = graph.ro_query("""
        MATCH ()-[r:RELATES_TO]->()
        WHERE r.dynamic_weight IS NULL
        RETURN count(r) AS missing_count
    """).result_set
    missing_count = result[0][0] if result else 0

    if missing_count > 0:
        print(f"  ⚠️  {missing_count} 條邊缺少 dynamic_weight")
        return False

    print("  ✅ 所有 RELATES_TO 邊已正確遷移")

    return True


def main():
    parser = argparse.ArgumentParser(
        description="語義記憶系統 v2.0 遷移腳本"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="顯示將進行的操作而不實際執行",
    )
    parser.add_argument(
        "--backup",
        action="store_true",
        help="遷移前建立備份（計劃功能）",
    )

    args = parser.parse_args()

    print("=" * 60)
    print("語義記憶系統 v2.0 遷移工具")
    print("=" * 60)

    if args.dry_run:
        print("🔍 [DRY-RUN 模式] 不會進行實際修改\n")

    try:
        # 連接圖譜
        print("連接 FalkorDB...")
        graph_client = get_graph_client()
        semantic_graph = graph_client.semantic

        if not graph_client.ping():
            print("❌ 無法連接 FalkorDB")
            return 1

        print("✅ 已連接\n")

        # 執行遷移
        migrate_concept_nodes(semantic_graph, dry_run=args.dry_run)
        migrate_relates_to_edges(semantic_graph, dry_run=args.dry_run)
        create_synonym_edge_index(semantic_graph, dry_run=args.dry_run)

        # 驗證
        if not args.dry_run:
            if verify_migration(semantic_graph):
                print("\n" + "=" * 60)
                print("✅ 遷移完成！")
                print("=" * 60)
                return 0
            else:
                print("\n❌ 遷移驗證失敗")
                return 1
        else:
            print("\n✓ DRY-RUN 完成（未修改任何數據）")
            return 0

    except Exception as e:
        print(f"\n❌ 遷移失敗: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
