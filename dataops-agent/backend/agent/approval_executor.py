"""The one place an action_name becomes a callable for the approval path.

TOOL_MAP is derived from agent.tools.ALL_TOOLS, the same registry the chat
graph binds and the Tasks executor resolves through, so a tool that can be
gated can always be executed after approval -- by construction, not by
someone remembering to add a second entry elsewhere. PolicyEngine.
execute_approved_action() dispatches through this map (2026-09-17).
"""
from agent.tools import ALL_TOOLS
import structlog

log = structlog.get_logger()

TOOL_MAP = {tool.name: tool for tool in ALL_TOOLS}


async def execute_tool_call(action_name: str, action_args: dict) -> dict:
    tool = TOOL_MAP.get(action_name)
    if not tool:
        raise ValueError(f"Tool '{action_name}' not found.")
    try:
        log.info("executing_approved_tool", tool=action_name, args=action_args)
        result = await tool.ainvoke(action_args)
        return {"success": True, "result": result}
    except Exception as e:
        log.error("tool_execution_failed", tool=action_name, error=str(e))
        return {"success": False, "error": str(e)}