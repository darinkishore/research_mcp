#!/usr/bin/env python
"""Run the Exa MCP server."""

from server import mcp

if __name__ == "__main__":
    print("Starting Exa MCP Server...")
    mcp.run()