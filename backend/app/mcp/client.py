from anyio import run
from mcp import Client
from mcp.shared.exceptions import MCPError

from app.ai.llm import TutorError
from app.mcp.server import server_for


async def invoke(owner, name, arguments):
    try:
        async with Client(server_for(owner), read_timeout_seconds=100) as client:
            result = await client.call_tool(name, arguments)
    except (MCPError, TimeoutError, ExceptionGroup) as error:
        raise TutorError("planner_tool", "The scheduling request could not be completed.", 502) from error
    if result.is_error or not isinstance(result.structured_content, dict):
        raise TutorError("planner_tool", "The scheduling request could not be completed.", 502)
    data = result.structured_content
    if data.get("error"):
        error = data["error"]
        raise TutorError(error["code"], error["message"], error["status"])
    return data["value"]


def call(owner, name, **arguments):
    return run(invoke, owner, name, arguments)
