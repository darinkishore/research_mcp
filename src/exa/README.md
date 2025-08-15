# Exa MCP Server

A FastMCP-based Model Context Protocol server for research and data exploration.

## Running the Server

```bash
cd src/exa
uv run python server.py
```

Or using the run script:
```bash
cd src/exa
uv run python run.py
```

## Available Tools

- **Math Operations**: `add`, `multiply`
- **String Processing**: `reverse_string`, `word_count`
- **Data Processing**: `json_prettify`, `get_timestamp`
- **List Operations**: `sort_list`, `unique_items`
- **Research**: `search_placeholder` (to be expanded)

## Adding New Tools

Simply add new functions decorated with `@mcp.tool` to `server.py`:

```python
@mcp.tool
def my_new_tool(param: str) -> str:
    """Tool description."""
    return f"Result: {param}"
```