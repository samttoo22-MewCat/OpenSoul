"""
soul_mcp/adapters/graph_lite.py

FalkorDB GraphClient 的 SQLite + networkx 輕量替代（Phase 1）。

只實作 soul/ 程式碼實際用到的 Cypher 子集：
  - CREATE 節點 / 邊
  - MATCH ... RETURN（依 id / prop 過濾）
  - MATCH ... SET（更新屬性）
  - MERGE 邊
  - CALL db.idx.vector.queryNodes（cosine similarity，numpy）
  - MATCH ()-[:TYPE*1..N]-()（多跳 BFS，networkx）
  - MATCH ()-[:TYPE]->() WHERE id IN (...)
  - COUNT(*)
"""

from __future__ import annotations

import json
import re
import sqlite3
import uuid
from pathlib import Path
from typing import Any


# ── 偽裝成 FalkorDB 節點 / 邊 ─────────────────────────────────────────────────

class FakeNode:
    """模擬 FalkorDB Node 物件，供 retrieval.py 取用 .properties。"""
    __slots__ = ("properties",)

    def __init__(self, properties: dict):
        self.properties = properties


class FakeEdge:
    """模擬 FalkorDB Edge 物件，供 retrieval.py 取用 .properties。"""
    __slots__ = ("properties",)

    def __init__(self, properties: dict = None):
        self.properties = properties or {}


class QueryResult:
    """模擬 FalkorDB query() 的回傳容器。"""

    def __init__(self, result_set: list | None = None):
        self.result_set: list = result_set or []
        self.nodes_deleted: int = 0


# ── 核心圖譜類別 ──────────────────────────────────────────────────────────────

class GraphLiteGraph:
    """
    單一記憶圖譜（情節/語意/程序）的 SQLite + networkx 實作。

    SQLite schema（每個 graph_name 獨立命名前綴）：
      {name}_nodes: id TEXT PK, label TEXT, props TEXT (JSON)
      {name}_edges: id TEXT PK, edge_type TEXT, src TEXT, tgt TEXT, props TEXT (JSON)
    """

    def __init__(self, conn: sqlite3.Connection, name: str) -> None:
        self._conn = conn
        self._name = name
        self._tn = f"{name}_nodes"   # table: nodes
        self._te = f"{name}_edges"   # table: edges
        self._init_tables()

    # ── 初始化 ────────────────────────────────────────────────────────────────

    def _init_tables(self) -> None:
        c = self._conn.cursor()
        c.execute(f"""
            CREATE TABLE IF NOT EXISTS {self._tn} (
                id    TEXT PRIMARY KEY,
                label TEXT NOT NULL,
                props TEXT NOT NULL DEFAULT '{{}}'
            )
        """)
        c.execute(f"""
            CREATE TABLE IF NOT EXISTS {self._te} (
                id        TEXT PRIMARY KEY,
                edge_type TEXT NOT NULL,
                src       TEXT NOT NULL,
                tgt       TEXT NOT NULL,
                props     TEXT NOT NULL DEFAULT '{{}}'
            )
        """)
        c.execute(f"CREATE INDEX IF NOT EXISTS ix_{self._name}_nl ON {self._tn}(label)")
        c.execute(f"CREATE INDEX IF NOT EXISTS ix_{self._name}_es ON {self._te}(src)")
        c.execute(f"CREATE INDEX IF NOT EXISTS ix_{self._name}_et ON {self._te}(tgt)")
        self._conn.commit()

    # ── 公開介面（對齊 FalkorDB Graph API）───────────────────────────────────

    def query(self, cypher: str, params: dict | None = None) -> QueryResult:
        return self._dispatch(cypher.strip(), params or {})

    def ro_query(self, cypher: str, params: dict | None = None) -> QueryResult:
        return self._dispatch(cypher.strip(), params or {})

    # ── Dispatcher ────────────────────────────────────────────────────────────

    def _dispatch(self, cypher: str, params: dict) -> QueryResult:
        up = cypher.upper()

        # 向量搜尋（最高優先，避免被 MATCH 攔截）
        if "CALL DB.IDX.VECTOR.QUERYNODES" in up:
            return self._vector_search(cypher, params)

        # 多跳遍歷
        if re.search(r'\[:\w+\*\d+\.\.\d+\]', cypher):
            return self._multihop(cypher, params)

        # MATCH + MENTIONS/CONTRADICTS 邊查詢
        if "MATCH" in up and ("-[:MENTIONS]->" in cypher or "-[:CONTRADICTS]->" in cypher):
            return self._edge_match(cypher, params)

        # SET 更新
        if "MATCH" in up and "SET " in up:
            return self._handle_set(cypher, params)

        # MERGE 邊
        if "MERGE" in up and "->" in cypher:
            return self._handle_merge_edge(cypher, params)

        # CREATE 邊（含 MATCH）
        if "CREATE" in up and "->" in cypher and "MATCH" in up:
            return self._handle_create_edge(cypher, params)

        # CREATE 節點（不含 ->）
        if re.match(r'\s*CREATE\s*\(', cypher, re.IGNORECASE) and "->" not in cypher:
            return self._handle_create_node(cypher, params)

        # MATCH RETURN count
        if "COUNT(" in up:
            return self._handle_count(cypher, params)

        # 一般 MATCH ... RETURN
        if "MATCH" in up and "RETURN" in up:
            return self._handle_match(cypher, params)

        # 未識別：回傳空結果（不拋例外）
        return QueryResult()

    # ── 向量搜尋 ─────────────────────────────────────────────────────────────

    def _vector_search(self, cypher: str, params: dict) -> QueryResult:
        """
        解析 CALL db.idx.vector.queryNodes('{Label}', 'embedding', {k}, vecf32({vec}))
        用 numpy cosine similarity 搜尋最近 k 個節點。
        """
        try:
            import numpy as np
        except ImportError:
            return QueryResult()

        # 提取 label 與 k
        m = re.search(
            r"queryNodes\s*\(\s*'(\w+)'\s*,\s*'(\w+)'\s*,\s*(\d+)\s*,\s*vecf32\((.+?)\)\s*\)",
            cypher, re.IGNORECASE | re.DOTALL
        )
        if not m:
            return QueryResult()

        label, field, k_str = m.group(1), m.group(2), m.group(3)
        k = int(k_str)

        # 解析查詢向量（從 vecf32([...]) 中取出）
        vec_str = m.group(4).strip()
        # vec_str 可能是 "[0.1, 0.2, ...]" 格式
        try:
            query_vec = np.array(json.loads(vec_str), dtype=np.float32)
        except Exception:
            return QueryResult()

        # 從 SQLite 載入所有該 label 節點
        c = self._conn.cursor()
        c.execute(f"SELECT id, props FROM {self._tn} WHERE label=?", (label,))
        rows = c.fetchall()

        results = []
        for row_id, props_str in rows:
            props = json.loads(props_str)
            emb = props.get(field)
            if not emb:
                continue
            try:
                node_vec = np.array(emb, dtype=np.float32)
                # cosine similarity
                denom = (np.linalg.norm(query_vec) * np.linalg.norm(node_vec))
                score = float(np.dot(query_vec, node_vec) / denom) if denom > 0 else 0.0
                results.append((props, score))
            except Exception:
                continue

        results.sort(key=lambda x: x[1], reverse=True)
        result_set = [[FakeNode(p), s] for p, s in results[:k]]
        return QueryResult(result_set)

    # ── 多跳遍歷 ─────────────────────────────────────────────────────────────

    def _multihop(self, cypher: str, params: dict) -> QueryResult:
        """
        處理 MATCH (seed:Label)-[:TYPE*1..N]-(related:Label) 模式。
        使用 networkx BFS 展開。
        """
        try:
            import networkx as nx
        except ImportError:
            return QueryResult()

        # 提取邊類型與最大跳數
        m = re.search(r'\[:(\w+)\*(\d+)\.\.(\d+)\]', cypher)
        if not m:
            return QueryResult()
        edge_type = m.group(1)
        max_hops = int(m.group(3))

        # 取得 LIMIT
        limit_m = re.search(r'LIMIT\s+(\d+)', cypher, re.IGNORECASE)
        limit = int(limit_m.group(1)) if limit_m else 50

        # 從 WHERE 子句提取 seed id（FalkorDB 實作寫的是 WHERE seed.id = '{id}' 格式）
        seed_m = re.search(r"seed\.id\s*=\s*'([^']+)'", cypher)
        if not seed_m:
            # 找不到種子 id，回傳空
            return QueryResult()
        seed_id = seed_m.group(1)

        # 建立 networkx 圖（只載入指定邊類型）
        G = nx.DiGraph()
        c = self._conn.cursor()
        c.execute(
            f"SELECT src, tgt FROM {self._te} WHERE edge_type=?",
            (edge_type,)
        )
        for src, tgt in c.fetchall():
            G.add_edge(src, tgt)

        # BFS 展開
        visited = set()
        queue = [(seed_id, 0)]
        while queue:
            nid, hop = queue.pop(0)
            if hop >= max_hops or nid in visited:
                continue
            visited.add(nid)
            for neighbor in list(G.successors(nid)) + list(G.predecessors(nid)):
                if neighbor not in visited:
                    queue.append((neighbor, hop + 1))

        visited.discard(seed_id)
        if not visited:
            return QueryResult()

        # 批次載入節點
        placeholders = ",".join("?" * len(visited))
        c.execute(
            f"SELECT props FROM {self._tn} WHERE id IN ({placeholders})",
            list(visited)
        )
        nodes = [FakeNode(json.loads(row[0])) for row in c.fetchall()][:limit]
        return QueryResult([[n] for n in nodes])

    # ── 邊查詢（MENTIONS / CONTRADICTS）─────────────────────────────────────

    def _edge_match(self, cypher: str, params: dict) -> QueryResult:
        """
        處理:
          MATCH (e:Ep)-[:MENTIONS]->(n:Entity) WHERE e.id IN $ids RETURN DISTINCT n
          MATCH (u:C)-[:CONTRADICTS]->(v:C) WHERE u.id IN $ids AND v.id IN $ids
            RETURN u.id AS src, v.id AS tgt
        """
        # 取得邊類型
        et_m = re.search(r'\[:(\w+)\]', cypher)
        if not et_m:
            return QueryResult()
        edge_type = et_m.group(1)

        # 取得 $ids 參數
        ids = params.get("ids", [])
        if not ids:
            return QueryResult()

        c = self._conn.cursor()

        if edge_type == "MENTIONS":
            # src 在 ids → 取 tgt 節點
            ph = ",".join("?" * len(ids))
            c.execute(f"SELECT DISTINCT tgt FROM {self._te} WHERE edge_type=? AND src IN ({ph})",
                      [edge_type] + list(ids))
            tgt_ids = [row[0] for row in c.fetchall()]
            if not tgt_ids:
                return QueryResult()
            ph2 = ",".join("?" * len(tgt_ids))
            c.execute(f"SELECT props FROM {self._tn} WHERE id IN ({ph2})", tgt_ids)
            nodes = [FakeNode(json.loads(row[0])) for row in c.fetchall()]
            return QueryResult([[n] for n in nodes])

        if edge_type == "CONTRADICTS":
            ph = ",".join("?" * len(ids))
            c.execute(
                f"SELECT src, tgt FROM {self._te} WHERE edge_type=? AND src IN ({ph}) AND tgt IN ({ph})",
                [edge_type] + list(ids) + list(ids)
            )
            rows = c.fetchall()
            return QueryResult([[r[0], r[1]] for r in rows])

        return QueryResult()

    # ── SET ───────────────────────────────────────────────────────────────────

    def _handle_set(self, cypher: str, params: dict) -> QueryResult:
        """
        MATCH (n:Label {id: $id}) SET n.prop = $val
        或
        MATCH (n:Label {id: $id}) SET n.p1 = $v1, n.p2 = $v2 ...
        """
        node_id = params.get("id") or params.get("eid")
        if not node_id:
            return QueryResult()

        c = self._conn.cursor()
        c.execute(f"SELECT props FROM {self._tn} WHERE id=?", (node_id,))
        row = c.fetchone()
        if not row:
            return QueryResult()

        props = json.loads(row[0])

        # 解析 SET 部分的賦值（n.prop = value 或 n.prop = $var）
        set_block = re.search(r'\bSET\b(.+?)(?:RETURN|$)', cypher, re.IGNORECASE | re.DOTALL)
        if set_block:
            for assign in re.finditer(r'\w+\.(\w+)\s*=\s*(\S+)', set_block.group(1)):
                prop_name = assign.group(1)
                raw_val = assign.group(2).rstrip(',')
                if raw_val.startswith('$'):
                    var_name = raw_val[1:]
                    val = params.get(var_name)
                elif raw_val.lower() == 'true':
                    val = True
                elif raw_val.lower() == 'false':
                    val = False
                else:
                    try:
                        val = json.loads(raw_val)
                    except Exception:
                        val = raw_val.strip("'\"")
                props[prop_name] = val

        c.execute(f"UPDATE {self._tn} SET props=? WHERE id=?", (json.dumps(props), node_id))
        self._conn.commit()
        return QueryResult()

    # ── MERGE 邊 ─────────────────────────────────────────────────────────────

    def _handle_merge_edge(self, cypher: str, params: dict) -> QueryResult:
        """
        MATCH (a {id: $eid}), (b {id: $nid})
        MERGE (a)-[:TYPE]->(b)
        [SET r.prop = ...]
        """
        src_id = params.get("eid") or params.get("uid") or params.get("source_id")
        tgt_id = params.get("nid") or params.get("vid") or params.get("target_id")
        if not src_id or not tgt_id:
            return QueryResult()

        et_m = re.search(r'MERGE\s*\(\w*\)-\[:(\w+)\]->', cypher, re.IGNORECASE)
        edge_type = et_m.group(1) if et_m else "UNKNOWN"

        # MERGE 語意：若不存在才建立
        c = self._conn.cursor()
        c.execute(
            f"SELECT id FROM {self._te} WHERE edge_type=? AND src=? AND tgt=?",
            (edge_type, src_id, tgt_id)
        )
        if not c.fetchone():
            eid = str(uuid.uuid4())
            # 提取 SET 屬性
            props: dict = {}
            set_m = re.search(r'\bSET\b\s+r\.(\w+)\s*=\s*\$(\w+)', cypher, re.IGNORECASE)
            if set_m:
                props[set_m.group(1)] = params.get(set_m.group(2), "")
            c.execute(
                f"INSERT INTO {self._te}(id,edge_type,src,tgt,props) VALUES(?,?,?,?,?)",
                (eid, edge_type, src_id, tgt_id, json.dumps(props))
            )
            self._conn.commit()
        return QueryResult()

    # ── CREATE 邊 ─────────────────────────────────────────────────────────────

    def _handle_create_edge(self, cypher: str, params: dict) -> QueryResult:
        """
        MATCH (prev {id: $prev}), (curr {id: $curr})
        CREATE (prev)-[:TYPE {props}]->(curr)
        """
        src_id = params.get("prev") or params.get("uid") or params.get("source_id")
        tgt_id = params.get("curr") or params.get("vid") or params.get("target_id")
        if not src_id or not tgt_id:
            return QueryResult()

        et_m = re.search(r'CREATE\s*\(\w*\)-\[:(\w+)', cypher, re.IGNORECASE)
        edge_type = et_m.group(1) if et_m else "UNKNOWN"

        # 提取內聯屬性 {...}
        props: dict = {}
        prop_m = re.search(r'\[:' + edge_type + r'\s*\{(.+?)\}', cypher, re.IGNORECASE | re.DOTALL)
        if prop_m:
            for kv in re.finditer(r'(\w+)\s*:\s*(\S+)', prop_m.group(1)):
                k, v = kv.group(1), kv.group(2).rstrip(',')
                if v.startswith('$'):
                    props[k] = params.get(v[1:])
                else:
                    try:
                        props[k] = json.loads(v)
                    except Exception:
                        props[k] = v.strip("'\"")

        eid = str(uuid.uuid4())
        c = self._conn.cursor()
        c.execute(
            f"INSERT OR IGNORE INTO {self._te}(id,edge_type,src,tgt,props) VALUES(?,?,?,?,?)",
            (eid, edge_type, src_id, tgt_id, json.dumps(props))
        )
        self._conn.commit()
        return QueryResult()

    # ── CREATE 節點 ───────────────────────────────────────────────────────────

    def _handle_create_node(self, cypher: str, params: dict) -> QueryResult:
        """
        CREATE (alias:Label {
            id: $id, prop1: $p1, ...
        })
        """
        # 提取 label
        label_m = re.search(r'CREATE\s*\(\w*:(\w+)', cypher, re.IGNORECASE)
        if not label_m:
            return QueryResult()
        label = label_m.group(1)

        # 提取 id
        node_id = params.get("id") or str(uuid.uuid4())

        # 建立 props dict：從 params 中選取 cypher 裡出現的 $var
        props: dict = {}
        for var in re.findall(r'\$(\w+)', cypher):
            if var in params:
                props[var] = params[var]

        # 修正 key 名稱：Cypher 內 "prop: $var"，key 應是 prop 而非 var
        named_props: dict = {}
        for m in re.finditer(r'(\w+)\s*:\s*\$(\w+)', cypher):
            prop_key, var_name = m.group(1), m.group(2)
            if var_name in params:
                named_props[prop_key] = params[var_name]

        # 合併 embedding 處理（vecf32(...) 格式）
        emb_m = re.search(r'embedding\s*:\s*vecf32\(\[(.+?)\]\)', cypher, re.DOTALL)
        if emb_m:
            try:
                named_props["embedding"] = json.loads("[" + emb_m.group(1) + "]")
            except Exception:
                pass

        named_props.setdefault("id", node_id)
        named_props["_label"] = label

        c = self._conn.cursor()
        c.execute(
            f"INSERT OR REPLACE INTO {self._tn}(id, label, props) VALUES(?,?,?)",
            (node_id, label, json.dumps(named_props))
        )
        self._conn.commit()
        return QueryResult()

    # ── COUNT ─────────────────────────────────────────────────────────────────

    def _handle_count(self, cypher: str, params: dict) -> QueryResult:
        c = self._conn.cursor()
        # MATCH (n:Label) RETURN count(n)
        label_m = re.search(r'MATCH\s*\(\w*:(\w+)\)', cypher, re.IGNORECASE)
        if label_m:
            label = label_m.group(1)
            c.execute(f"SELECT count(*) FROM {self._tn} WHERE label=?", (label,))
        elif "()-[" in cypher or "MATCH ()-[" in cypher.upper():
            c.execute(f"SELECT count(*) FROM {self._te}")
        else:
            c.execute(f"SELECT count(*) FROM {self._tn}")
        row = c.fetchone()
        return QueryResult([[row[0] if row else 0]])

    # ── 一般 MATCH ────────────────────────────────────────────────────────────

    def _handle_match(self, cypher: str, params: dict) -> QueryResult:
        """
        處理常見的 MATCH ... RETURN 模式：
          - MATCH (n:Label {id: $id}) RETURN n
          - MATCH (n:Label {name: $name}) RETURN n.id
          - MATCH (n:Label {session_id: $sid}) RETURN n ORDER BY ... LIMIT N
          - MATCH (n:Label) WHERE n.prop >= $val AND ... RETURN n ORDER BY ... LIMIT N
        """
        c = self._conn.cursor()

        # 取得 label
        label_m = re.search(r'MATCH\s*\(\w*:(\w+)', cypher, re.IGNORECASE)
        label = label_m.group(1) if label_m else None

        # 取得 LIMIT
        limit_m = re.search(r'LIMIT\s+\$?(\w+)', cypher, re.IGNORECASE)
        if limit_m:
            raw_limit = limit_m.group(1)
            limit = params.get(raw_limit, int(raw_limit)) if not raw_limit.isdigit() else int(raw_limit)
        else:
            limit = 200

        # 內嵌過濾屬性：MATCH (n:Label {key: $var})
        inline_filters: dict = {}
        inline_m = re.search(r'MATCH\s*\(\w*(?::\w+)?\s*\{(.+?)\}\s*\)', cypher, re.DOTALL)
        if inline_m:
            for kv in re.finditer(r'(\w+)\s*:\s*\$(\w+)', inline_m.group(1)):
                inline_filters[kv.group(1)] = params.get(kv.group(2))

        # WHERE 子句過濾（簡單 n.prop >= $val）
        where_filters: list[tuple[str, str, Any]] = []
        for wm in re.finditer(r'\bn\.(\w+)\s*(>=|<=|>|<|=)\s*\$(\w+)', cypher):
            where_filters.append((wm.group(1), wm.group(2), params.get(wm.group(3))))

        # WHERE n.prop = false
        for wm in re.finditer(r'\bn\.(\w+)\s*=\s*(true|false)\b', cypher, re.IGNORECASE):
            where_filters.append((wm.group(1), "=", wm.group(2).lower() == "true"))

        # 查詢 SQLite
        if label:
            c.execute(f"SELECT props FROM {self._tn} WHERE label=?", (label,))
        else:
            c.execute(f"SELECT props FROM {self._tn}")

        rows = c.fetchall()
        nodes = []
        for (props_str,) in rows:
            props = json.loads(props_str)

            # 套用 inline 過濾
            match = True
            for key, val in inline_filters.items():
                if props.get(key) != val:
                    match = False
                    break
            if not match:
                continue

            # 套用 WHERE 過濾
            for prop_name, op, val in where_filters:
                pv = props.get(prop_name)
                if pv is None:
                    match = False
                    break
                if op == ">=" and not (pv >= val):
                    match = False
                    break
                elif op == "<=" and not (pv <= val):
                    match = False
                    break
                elif op == ">" and not (pv > val):
                    match = False
                    break
                elif op == "<" and not (pv < val):
                    match = False
                    break
                elif op == "=" and pv != val:
                    match = False
                    break
            if not match:
                continue

            nodes.append(props)

        # ORDER BY
        order_m = re.search(r'ORDER BY\s+\w+\.(\w+)\s*(ASC|DESC)?', cypher, re.IGNORECASE)
        if order_m:
            field = order_m.group(1)
            desc = (order_m.group(2) or "ASC").upper() == "DESC"
            nodes.sort(key=lambda x: x.get(field, ""), reverse=desc)

        nodes = nodes[:limit]

        # RETURN 格式判斷
        ret_m = re.search(r'RETURN\s+(.+?)(?:\s+ORDER|\s+LIMIT|$)', cypher, re.IGNORECASE | re.DOTALL)
        if not ret_m:
            return QueryResult([[FakeNode(n)] for n in nodes])

        ret_clause = ret_m.group(1).strip()

        # RETURN n.id AS id（單欄位）
        if re.match(r'\w+\.\w+\s+AS\s+\w+', ret_clause, re.IGNORECASE):
            field_m = re.match(r'\w+\.(\w+)', ret_clause)
            field_name = field_m.group(1) if field_m else "id"
            return QueryResult([[n.get(field_name)] for n in nodes])

        # RETURN n（節點）
        return QueryResult([[FakeNode(n)] for n in nodes])


# ── GraphLiteClient（對齊 GraphClient 介面）──────────────────────────────────

class GraphLiteClient:
    """
    GraphClient 的 SQLite + networkx 輕量替代。

    用法：
        from soul_mcp.adapters.graph_lite import GraphLiteClient
        client = GraphLiteClient()  # 預設 :memory:
        # 或
        client = GraphLiteClient(db_path="/path/to/soul.db")
    """

    def __init__(self, db_path: str | Path | None = None) -> None:
        if db_path is None or str(db_path) == ":memory:":
            self._conn = sqlite3.connect(":memory:", check_same_thread=False)
        else:
            self._conn = sqlite3.connect(str(db_path), check_same_thread=False)

        self._episodic: GraphLiteGraph | None = None
        self._semantic: GraphLiteGraph | None = None
        self._procedural: GraphLiteGraph | None = None

    @property
    def episodic(self) -> GraphLiteGraph:
        if self._episodic is None:
            self._episodic = GraphLiteGraph(self._conn, "episodic")
        return self._episodic

    @property
    def semantic(self) -> GraphLiteGraph:
        if self._semantic is None:
            self._semantic = GraphLiteGraph(self._conn, "semantic")
        return self._semantic

    @property
    def procedural(self) -> GraphLiteGraph:
        if self._procedural is None:
            self._procedural = GraphLiteGraph(self._conn, "procedural")
        return self._procedural

    def ping(self) -> bool:
        return True

    def clear_all(self) -> dict[str, int]:
        results = {}
        for name, graph in [
            ("episodic", self.episodic),
            ("semantic", self.semantic),
            ("procedural", self.procedural),
        ]:
            c = self._conn.cursor()
            c.execute(f"DELETE FROM {graph._tn}")
            c.execute(f"DELETE FROM {graph._te}")
            results[name] = c.rowcount
        self._conn.commit()
        return results


# ── 全域單例工廠 ──────────────────────────────────────────────────────────────

_lite_client: GraphLiteClient | None = None


def get_lite_client(db_path: str | Path | None = None) -> GraphLiteClient:
    """取得全域 GraphLiteClient 單例（lazy init）。"""
    global _lite_client
    if _lite_client is None:
        _lite_client = GraphLiteClient(db_path)
    return _lite_client
