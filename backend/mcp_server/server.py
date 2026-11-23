"""Docent MCP server (stdio).

Exposes the user's documents to any MCP client (Claude Desktop, Claude Code,
Cursor). Auth: set DOCENT_ACCESS_TOKEN to a Supabase access token; it is
verified on every call with the same code as the HTTP API, so all data access
is scoped to that user and an expired token stops working.

Run:  python -m mcp_server.server
"""

from __future__ import annotations

import os

from mcp.server.mcpserver import MCPServer

from app.core.auth import TokenVerificationError, verify_token
from app.db.client import create_pool

from . import tools

mcp = MCPServer("docent")


def current_user_id() -> str:
    """Verify the configured token. Raises a readable error if missing/expired."""
    token = os.environ.get("DOCENT_ACCESS_TOKEN", "")
    try:
        return verify_token(token)
    except TokenVerificationError as exc:
        raise ValueError(f"DOCENT_ACCESS_TOKEN is invalid or expired: {exc}") from exc


@mcp.tool()
async def search_documents(query: str, k: int = 5, document_id: str | None = None) -> list[dict]:
    """Search the user's documents (hybrid semantic + keyword) and return the
    top-k excerpts with filename, page and similarity. Optionally restrict to one document id."""
    return await tools.search_documents(
        await create_pool(), current_user_id(), query, k, document_id
    )


@mcp.tool()
async def list_documents() -> list[dict]:
    """List the user's uploaded documents with id, filename and ingestion status."""
    user_id = current_user_id()
    return await tools.list_documents(await create_pool(), user_id)


@mcp.tool()
async def get_document_insight(document_id: str, kind: str = "summary") -> dict:
    """Get a summary, key_facts list or quiz for a ready document."""
    user_id = current_user_id()
    return await tools.get_document_insight(await create_pool(), user_id, document_id, kind)


@mcp.resource("docent://documents")
async def documents_resource() -> str:
    """The user's document list as JSON text."""
    import json

    user_id = current_user_id()
    return json.dumps(await tools.list_documents(await create_pool(), user_id))


if __name__ == "__main__":
    mcp.run()
