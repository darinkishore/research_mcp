"""Exa MCP Server - Main server implementation using FastMCP."""

from fastmcp import FastMCP
from typing import Any
import json
from datetime import datetime
from search_tool import setup_search_tool

# Create the FastMCP server instance
mcp = FastMCP("Exa Research Server 🔍")

# Set up the Exa search tool
setup_search_tool(mcp)

if __name__ == "__main__":
    # Run the server
    mcp.run()