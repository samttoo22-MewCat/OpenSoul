"""
soul/interface/cli.py

openSOUL CLI：基於 Typer + Rich 的命令列介面。

指令：
  soul chat                    對話模式（前額葉 + 記憶 + 閘門）
  soul dream                   手動觸發夢境鞏固引擎
  soul dream --replay-only     僅執行 LiDER 重播
  soul status                  神經化學狀態 + 圖譜統計
  soul memory search <query>   在三個圖譜中搜尋記憶
  soul memory stats            各圖譜節點/邊數量
  soul memory prune            手動觸發修剪
  soul init                    初始化 workspace + FalkorDB schema
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Optional

import typer
from rich import print as rprint
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

app = typer.Typer(
    name="soul",
    help="openSOUL — 仿人類心智認知 AI 系統",
    no_args_is_help=True,
)
memory_app = typer.Typer(help="記憶圖譜操作指令")
app.add_typer(memory_app, name="memory")

console = Console()


# ── soul init ─────────────────────────────────────────────────────────────────

@app.command("init")
def init(
    workspace: Annotated[Path, typer.Option("--workspace", "-w", help="workspace 路徑")] = Path("./workspace"),
) -> None:
    """初始化 workspace 目錄與 FalkorDB Schema。"""
    from soul.memory.graph import get_graph_client, initialize_schemas

    console.print(Panel("[bold cyan]openSOUL 初始化[/bold cyan]", expand=False))

    # 建立 workspace 目錄
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "memory").mkdir(exist_ok=True)

    # 複製預設 SOUL.md（若不存在）
    soul_md = workspace / "SOUL.md"
    if not soul_md.exists():
        default_soul = Path("workspace/SOUL.md")
        if default_soul.exists():
            soul_md.write_text(default_soul.read_text(encoding="utf-8"), encoding="utf-8")
            console.print("[green]✓[/green] SOUL.md 建立完成")
        else:
            console.print("[yellow]⚠[/yellow] 找不到預設 SOUL.md，請手動建立")

    # 初始化 FalkorDB
    try:
        client = get_graph_client()
        if not client.ping():
            console.print("[red]✗[/red] FalkorDB 連線失敗，請確認 Docker 已啟動")
            raise typer.Exit(1)
        initialize_schemas(client)
        console.print("[green]✓[/green] FalkorDB Schema 初始化完成（三圖譜 + 向量索引）")
    except Exception as exc:
        console.print(f"[red]✗[/red] FalkorDB 錯誤：{exc}")
        raise typer.Exit(1)

    console.print("\n[bold green]初始化完成！執行 `soul chat` 開始對話。[/bold green]")


# ── soul chat ─────────────────────────────────────────────────────────────────

@app.command("chat")
def chat(
    no_gating: Annotated[bool, typer.Option("--no-gating", help="跳過基底核驗證（開發模式）")] = False,
    session_id: Annotated[Optional[str], typer.Option("--session", "-s", help="指定 Session ID（用於恢復對話）")] = None,
) -> None:
    """啟動互動對話模式。輸入 /exit 或按 Ctrl+C 結束。"""
    from soul.core.agent import SoulAgent
    from soul.core.session import Session
    from soul.dream.engine import get_dream_engine

    console.print(Panel(
        "[bold cyan]openSOUL 對話模式[/bold cyan]\n"
        "輸入 [bold]/exit[/bold] 結束 | [bold]/status[/bold] 顯示狀態 | [bold]/dream[/bold] 手動觸發夢境",
        expand=False,
    ))

    try:
        agent = SoulAgent()
        session = Session(session_id=session_id)
        dream_engine = get_dream_engine()
        dream_engine.start()

        soul = agent.soul
        console.print(
            f"[dim]身份：{soul.name} v{soul.version} | "
            f"DA={soul.neurochem.dopamine:.2f} | "
            f"5-HT={soul.neurochem.serotonin:.2f}[/dim]\n"
        )

    except Exception as exc:
        console.print(f"[red]初始化失敗：{exc}[/red]")
        console.print("[dim]提示：確認 FalkorDB 已啟動（docker compose up -d）並設定 .env[/dim]")
        raise typer.Exit(1)

    while True:
        try:
            user_input = console.input("[bold blue]You[/bold blue] > ").strip()
        except (KeyboardInterrupt, EOFError):
            break

        if not user_input:
            continue

        # 內建指令
        if user_input.lower() in ("/exit", "/quit", "/q"):
            break
        if user_input.lower() == "/status":
            _print_status(agent, dream_engine)
            continue
        if user_input.lower() == "/dream":
            _run_dream(dream_engine, replay_only=False)
            continue

        # 通知 Dream Engine 使用者有互動
        dream_engine.notify_interaction()

        # 正常對話
        with console.status("[dim]思考中...[/dim]", spinner="dots"):
            try:
                response = agent.chat(user_input, session)
            except Exception as exc:
                console.print(f"[red]錯誤：{exc}[/red]")
                continue

        # 顯示回覆
        gating_icon = {
            "pass": "[green]●[/green]",
            "revise": "[yellow]◐[/yellow]",
            "suppress": "[red]○[/red]",
        }.get(response.gating_action, "●")

        console.print(f"\n[bold magenta]Soul[/bold magenta] {gating_icon}")
        console.print(response.text)

        # 底部狀態列
        nc = response.neurochem
        console.print(
            f"\n[dim]DA={nc.get('dopamine', 0):.2f} "
            f"5-HT={nc.get('serotonin', 0):.2f} | "
            f"記憶:{len(response.memory_context.episodes)} 情節 "
            f"{len(response.memory_context.concepts)} 概念 | "
            f"閘門:{response.gating_action} ({response.gating_score:.2f})[/dim]\n"
        )

    # 對話結束：儲存每日日誌
    try:
        log_path = session.flush_to_daily_log()
        console.print(f"\n[dim]對話日誌已儲存至 {log_path}[/dim]")
    except Exception:
        pass

    dream_engine.stop()
    console.print("[dim]再見！[/dim]")


# ── soul dream ────────────────────────────────────────────────────────────────

@app.command("dream")
def dream(
    replay_only: Annotated[bool, typer.Option("--replay-only", help="只執行 LiDER 經驗重播")] = False,
) -> None:
    """手動觸發離線記憶鞏固夢境引擎。"""
    from soul.dream.engine import get_dream_engine

    engine = get_dream_engine()
    _run_dream(engine, replay_only=replay_only)


# ── soul status ───────────────────────────────────────────────────────────────

@app.command("status")
def status() -> None:
    """顯示神經化學狀態、圖譜統計與 Dream Engine 資訊。"""
    from soul.core.agent import SoulAgent
    from soul.dream.engine import get_dream_engine

    try:
        agent = SoulAgent()
        dream_engine = get_dream_engine()
        _print_status(agent, dream_engine)
    except Exception as exc:
        console.print(f"[red]取得狀態失敗：{exc}[/red]")
        raise typer.Exit(1)


# ── soul memory ───────────────────────────────────────────────────────────────

@memory_app.command("search")
def memory_search(
    query: Annotated[str, typer.Argument(help="搜尋查詢")],
    top_k: Annotated[int, typer.Option("--top-k", "-k", help="返回最多幾筆結果")] = 5,
) -> None:
    """在三個記憶圖譜中搜尋相關節點。"""
    from soul.core.agent import EmbeddingService, SoulAgent
    from soul.affect.neurochem import NeurochemState
    from soul.memory.graph import get_graph_client
    from soul.memory.retrieval import EcphoryRetrieval

    console.print(f"[dim]搜尋：{query}[/dim]\n")

    try:
        client = get_graph_client()
        embedder = EmbeddingService()
        retrieval = EcphoryRetrieval(client)
        neurochem = NeurochemState()

        embedding = embedder.embed(query)
        ctx = retrieval.retrieve(
            query_embedding=embedding,
            serotonin=neurochem.serotonin,
            dopamine=neurochem.dopamine,
            top_k=top_k,
        )

        if ctx.is_empty():
            console.print("[dim]未找到相關記憶節點。[/dim]")
            return

        if ctx.episodes:
            _print_section("情節記憶", ctx.episodes, ["content", "da_weight", "timestamp"])
        if ctx.concepts:
            _print_section("語意概念", ctx.concepts, ["name", "type", "description"])
        if ctx.procedures:
            _print_section("程序性記憶", ctx.procedures, ["name", "domain", "success_count"])

    except Exception as exc:
        console.print(f"[red]搜尋失敗：{exc}[/red]")
        raise typer.Exit(1)


@memory_app.command("stats")
def memory_stats() -> None:
    """顯示三個記憶圖譜的節點/邊數量統計。"""
    from soul.memory.graph import get_graph_client
    from soul.memory.semantic import SemanticMemory
    from soul.memory.episodic import EpisodicMemory
    from soul.memory.procedural import ProceduralMemory

    try:
        client = get_graph_client()
        s_stats = SemanticMemory(client).stats()
        e_stats = EpisodicMemory(client).stats()
        p_stats = ProceduralMemory(client).stats()

        table = Table(title="記憶圖譜統計", show_header=True)
        table.add_column("圖譜", style="cyan")
        table.add_column("節點數", justify="right")
        table.add_column("邊數", justify="right")
        table.add_column("額外統計", style="dim")

        table.add_row(
            "soul_semantic（語意）",
            str(s_stats["nodes"]),
            str(s_stats["edges"]),
            "",
        )
        table.add_row(
            "soul_episodic（情節）",
            str(e_stats["nodes"]),
            str(e_stats["edges"]),
            f"情節 {e_stats['episodes']}，待重播 {e_stats['undreamed']}",
        )
        table.add_row(
            "soul_procedural（程序）",
            str(p_stats["nodes"]),
            str(p_stats["edges"]),
            f"累計成功 {p_stats['total_successes']}",
        )

        console.print(table)
    except Exception as exc:
        console.print(f"[red]統計失敗：{exc}[/red]")
        raise typer.Exit(1)


@memory_app.command("prune")
def memory_prune() -> None:
    """手動觸發圖譜修剪（清除低權重邊緣與過期節點）。"""
    from soul.dream.pruning import GraphPruning
    from soul.memory.graph import get_graph_client

    console.print("[dim]執行圖譜修剪...[/dim]")
    try:
        client = get_graph_client()
        pruner = GraphPruning(client)
        report = pruner.run()

        console.print(f"[green]✓[/green] 修剪完成")
        console.print(f"  刪除邊緣：{report.edges_pruned}")
        console.print(f"  歸檔節點：{report.nodes_archived}")
        console.print(f"  新增橋接：{report.bridges_created}")
        for d in report.details:
            console.print(f"  [dim]{d}[/dim]")
    except Exception as exc:
        console.print(f"[red]修剪失敗：{exc}[/red]")
        raise typer.Exit(1)


# ── Private Helpers ───────────────────────────────────────────────────────────

def _print_status(agent: Any, dream_engine: Any) -> None:
    soul = agent.soul
    nc = soul.neurochem
    dm_status = dream_engine.status()

    table = Table(title="openSOUL 狀態", show_header=False, box=None)
    table.add_column("欄位", style="cyan", width=22)
    table.add_column("值")

    table.add_row("Agent", f"{soul.name} v{soul.version}")
    table.add_row("語言", soul.language)
    table.add_row("多巴胺 (DA)", f"{nc.dopamine:.3f}")
    table.add_row("血清素 (5-HT)", f"{nc.serotonin:.3f}")
    table.add_row("神經化學模式", nc.mode.value)
    table.add_row("學習率", f"{nc.learning_rate:.3f}")
    table.add_row("驗證閾值", f"{nc.verification_threshold:.3f}")
    table.add_row("搜尋廣度", str(nc.search_breadth))
    table.add_row("Dream Engine", "[green]運行中[/green]" if dm_status["scheduler_running"] else "[red]已停止[/red]")
    table.add_row("閒置秒數", f"{dm_status['idle_seconds']}s / {dm_status['idle_threshold_seconds']}s")
    table.add_row("上次夢境", soul.last_dream or "尚未執行")

    console.print(table)


def _run_dream(engine: Any, replay_only: bool = False) -> None:
    console.print("[dim]正在執行夢境鞏固週期...[/dim]")
    with console.status("[cyan]作夢中...[/cyan]", spinner="moon"):
        if replay_only:
            from soul.dream.replay import LiDERReplay
            from soul.memory.graph import get_graph_client
            r = LiDERReplay(get_graph_client()).run()
            console.print(
                f"[green]✓[/green] 重播完成：{r.episodes_processed} 個情節，"
                f"新增程序 {r.procedures_created}"
            )
        else:
            report = engine.dream_now(triggered_by="manual")
            console.print(report.summary())


def _print_section(title: str, items: list[dict], keys: list[str]) -> None:
    table = Table(title=title, show_header=True)
    for k in keys:
        table.add_column(k, overflow="fold")
    for item in items:
        table.add_row(*[str(item.get(k, ""))[:80] for k in keys])
    console.print(table)
    console.print()


if __name__ == "__main__":
    app()
