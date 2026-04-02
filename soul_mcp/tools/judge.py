"""
soul_mcp/tools/judge.py

MCP Tool: soul_judge_tool
詢問 OpenSoul 的裁判模組：這個需求是否需要呼叫外部工具？
可選擇直接執行推薦的 OpenClaw 技能。
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger("soul_mcp.judge")

_MIN_CONFIDENCE_TO_EXECUTE = 0.6  # 低於此信心分數不自動執行


def _execute_skill(skill_name: str, user_input: str, execute_args: dict) -> dict[str, Any]:
    """
    透過 subprocess 執行 OpenClaw Python 技能腳本。
    仿照 soul/interface/api.py 的 _execute_skill() 邏輯。

    skill_name: 技能名稱（e.g. "gmail", "browser-control"）
    user_input: 使用者原始需求（作為 --input 參數）
    execute_args: 額外參數 dict（各 key 轉為 --key value CLI 參數）
    """
    try:
        from soul.core.config import settings
        skills_root = Path(settings.soul_project_root) / "openclaw" / "skills"
    except Exception:
        skills_root = Path(__file__).resolve().parents[2] / "openclaw" / "skills"

    # skill 目錄名稱：底線轉橫線
    skill_dir_name = skill_name.replace("_", "-")
    scripts_dir = skills_root / skill_dir_name / "scripts"

    if not scripts_dir.exists():
        return {"error": f"找不到技能目錄：{scripts_dir}", "skill": skill_name}

    py_scripts = sorted(scripts_dir.glob("*.py"))
    if not py_scripts:
        return {"error": f"技能目錄中找不到 Python 腳本：{scripts_dir}", "skill": skill_name}

    script_path = py_scripts[0]
    cmd = [sys.executable, str(script_path)]

    # 加入 --input 參數（若腳本支援）
    if user_input:
        cmd.extend(["--input", user_input])

    # 加入額外參數
    for key, value in execute_args.items():
        if value is not None and value != "":
            cmd.extend([f"--{key}", str(value)])

    logger.info(f"[soul_judge_tool] 執行技能：{script_path.name}，參數：{execute_args}")

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return {
            "skill": skill_name,
            "script": script_path.name,
            "returncode": result.returncode,
            "stdout": result.stdout[:1000] if result.stdout else "",
            "stderr": result.stderr[:300] if result.stderr else "",
            "success": result.returncode == 0,
        }
    except subprocess.TimeoutExpired:
        return {"error": "技能執行逾時（30s）", "skill": skill_name}
    except Exception as e:
        return {"error": f"技能執行失敗：{e}", "skill": skill_name}


def soul_judge_tool(
    user_input: str,
    execute: bool = False,
    execute_args: str = "",
) -> dict[str, Any]:
    """
    詢問 OpenSoul 的裁判模組，判斷使用者需求是否需要呼叫外部工具。
    可選擇在決策後直接執行推薦的 OpenClaw 技能。

    Args:
        user_input:    使用者的原始需求描述
        execute:       是否在決策後直接執行推薦技能（預設 False）
        execute_args:  執行時傳入的額外參數（JSON 字串，e.g. '{"limit": 10}'）

    Returns:
        {
          "recommended_tool":  "skill-name" | "none",
          "reasoning":         "決策推理說明",
          "confidence":        0.0 ~ 1.0,
          "available_tools_count": int,
          "executed":          bool,
          "execution_result":  dict（只有 execute=True 且有實際執行時才有）,
          "not_executed_reason": str（只有 execute=True 但未執行時才有）
        }
    """
    base_result: dict[str, Any] = {
        "recommended_tool": "none",
        "reasoning": "",
        "confidence": 0.0,
        "available_tools_count": 0,
        "executed": False,
    }

    try:
        from soul.core.config import settings
        from soul.gating.judge import JudgeAgent

        if settings.soul_utility_llm_provider.lower() == "openrouter":
            from openai import OpenAI
            llm = OpenAI(
                api_key=settings.openrouter_api_key,
                base_url=settings.openrouter_base_url,
            )
            provider = "openrouter"
        else:
            import anthropic
            llm = anthropic.Anthropic(api_key=settings.anthropic_api_key)
            provider = "anthropic"

        judge = JudgeAgent(llm_client=llm, provider=provider)
        tools = judge.discover_available_tools()
        result = judge.recommend_tool(user_input, tools)

        recommended = result.get("recommended_tool", "none")
        confidence = float(result.get("confidence", 0.0))

        base_result.update({
            "recommended_tool": recommended,
            "reasoning": result.get("reasoning", ""),
            "confidence": confidence,
            "available_tools_count": len(tools),
        })

    except Exception as e:
        logger.error(f"[soul_judge_tool] Judge 初始化失敗：{e}")
        base_result["reasoning"] = f"Judge 初始化失敗：{e}"
        return base_result

    # ── 執行推薦技能（execute=True）──────────────────────────────────────────
    if not execute:
        return base_result

    if recommended == "none":
        base_result["not_executed_reason"] = "無推薦技能（recommended_tool = none）"
        return base_result

    if confidence < _MIN_CONFIDENCE_TO_EXECUTE:
        base_result["not_executed_reason"] = (
            f"信心分數過低（{confidence:.2f} < {_MIN_CONFIDENCE_TO_EXECUTE}），不自動執行"
        )
        return base_result

    # 解析 execute_args
    try:
        args_dict: dict = json.loads(execute_args) if execute_args.strip() else {}
    except json.JSONDecodeError:
        args_dict = {}

    execution_result = _execute_skill(recommended, user_input, args_dict)
    base_result["executed"] = True
    base_result["execution_result"] = execution_result
    return base_result
