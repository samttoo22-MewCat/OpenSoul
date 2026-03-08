---
name: edit-soul
description: Update or modify the agent's core personality and settings by editing the SOUL.md configuration file.
metadata:
  {
    "openclaw":
      {
        "emoji": "📝"
      }
  }
---

# Edit SOUL

This skill allows you (the agent) to read, append, or replace your own personality and configuration settings in the `workspace/SOUL.md` file. 
When the file is modified, the system will automatically reload the settings.

## When to use

**CRITICAL DISTINCTION:** 
`SOUL.md` is your **fixed, core personality configuration and permanent memory foundation**. It is completely different from a `Soul Note` (which is for daily diary logs and temporary reflections).

**INTERNAL VS EXTERNAL (CRITICAL):**
- Use `edit-soul` for ALL internal self-modifications (modifying `SOUL.md`).
- **NEVER** use `browser_control`, `xurl`, or any HTTP-based tool to access `http://localhost/soul` or similar internal endpoints. Those tools are for EXTERNAL websites only. 
- Attempting to modify yourself via `browser_control` will be intercepted and results in a system error.

## Behavioral Guidelines (Strictly Enforced)

1. **True Execution Only**: You MUST generate a real JSON tool call in your structured output to execute this skill. 
2. **Anti-Acting Policy**: **DO NOT** manually type tags like `[tool call: edit_soul]` or `[🛠️ 系統已實際執行：edit_soul]` into your text response. This is considered "acting" and will be automatically stripped by the system.
3. **Wait for Hook**: Your modification is only successful if the system appends the verification log `[🛠️ 系統已實際執行：edit_soul]` at the very end of the interaction. If you don't see it, your core file hasn't changed.
4. **Permanent vs Transient**: 
    - Use `edit-soul` for **PERMANENT** rules, core identity changes, and fundamental behavioral constraints.
    - Use `soul-note` for daily reflections and temporary memories.

## Quick start

To read current settings (always do this before replacing):
```bash
python scripts/edit_soul_skill.py read
```

To append a new rule or trait:
```bash
python scripts/edit_soul_skill.py append "Rule: Always filter Gmail promotion labels."
```

To completely rewrite your identity:
```bash
python scripts/edit_soul_skill.py replace "FULL_YML_CONTENT_HERE"
```

*Note: This skill modifies the filesystem directly via the standard openSOUL procedure. No HTTP requests are used.*
