import asyncio
import os
import sqlite3

import dotenv
import mcp
import mcp.types as types
from exa_py import Exa
from exa_py.api import Result
from mcp.server import NotificationOptions, Server
from mcp.server.models import InitializationOptions
from pydantic import AnyUrl

from research_mcp.clean_content import ExaResult, clean_content
from research_mcp.models import CleanedContent, QueryRequest
from research_mcp.query_generation import generate_queries
from research_mcp.word_ids import WordIDGenerator

# implicit global state with the dspy modules being imported already initialized in the functions

# Load environment variables
dotenv.load_dotenv()

# Initialize Exa client
exa = Exa(os.getenv("EXA_API_KEY"))

# Initialize the server
server = Server("research_mcp")

# Database setup with locking
DATABASE_FILE = "results.db"
conn = sqlite3.connect(DATABASE_FILE, check_same_thread=False)
cursor = conn.cursor()
db_lock = asyncio.Lock()

# Create results table if it doesn't exist
# TODO: add a created_at and updated_at timestamp
# TODO: should also store relevance to the query generated via GPT
# TODO: should also store reason, query inputs to the thing


cursor.execute("""
CREATE TABLE IF NOT EXISTS results (
    id TEXT PRIMARY KEY,         -- Our word-based ID (e.g. "SPARK")
    title TEXT NOT NULL,         -- Article title
    author TEXT NOT NULL,        -- Article author(s)
    url TEXT NOT NULL,          -- Original source URL
    
    -- Summaries
    summary TEXT NOT NULL,       -- Original GPT-generated summary
    relevance_summary TEXT NOT NULL, -- Why this result is relevant to query
    
    -- Content
    full_text TEXT NOT NULL,     -- Original raw text
    cleaned_content TEXT NOT NULL,-- Cleaned/dense version from GPT
               
    -- Relevance
    relevance_score FLOAT NOT NULL,
    
    -- Query Context
    query_purpose TEXT NOT NULL, -- Original research purpose
    query_question TEXT NOT NULL,-- Original research question
    
    -- Metadata for system use
    metadata JSON,              -- Any additional metadata we might want to store
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    exa_id TEXT,
    raw_highlights JSON
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS exa_queries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    query_text TEXT NOT NULL,      -- The actual Exa query
    category TEXT,                 -- Optional category
    livecrawl BOOLEAN NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS query_results (
    query_id INTEGER NOT NULL,
    result_id TEXT NOT NULL,
    FOREIGN KEY(query_id) REFERENCES exa_queries(id),
    FOREIGN KEY(result_id) REFERENCES results(id),
    PRIMARY KEY(query_id, result_id)
)
""")

# Add an index for recent results
cursor.execute("""
CREATE INDEX IF NOT EXISTS idx_results_created_at ON results(created_at DESC)
""")

conn.commit()

# Initialize Word ID Generator
word_id_generator = WordIDGenerator(conn)


async def perform_exa_search(
    query_text: str, category: str | None = None, livecrawl: bool = False
) -> list[Result]:
    """Perform Exa search asynchronously."""
    search_args = {
        "highlights": True,
        "num_results": 10,
        "type": "neural",
        "text": True,
        "use_autoprompt": False,
    }
    if category is not None:
        search_args["category"] = category
    if livecrawl:
        search_args["livecrawl"] = "always"
    loop = asyncio.get_event_loop()
    results: list[Result] = await loop.run_in_executor(
        None, lambda: exa.search_and_contents(query_text, **search_args)
    )

    return results


# Store notes as a simple key-value dict to demonstrate state management
notes: dict[str, str] = {}

server = Server("research_mcp")


@server.list_resources()
async def handle_list_resources() -> list[types.Resource]:
    """List available result resources, focusing on most relevant and recent."""
    async with db_lock:
        # Get recent results, ordered by relevance
        cursor.execute("""
            SELECT id, title, summary 
            FROM results 
            ORDER BY created_at DESC 
            LIMIT 25  -- Maintain reasonable context size
        """)
        rows = cursor.fetchall()

    return [
        types.Resource(
            uri=AnyUrl(f"research://results/{id}"),
            name=f"[{id}] {title[:50]}...",  # Keep titles concise
            description=f"Summary: {summary[:150]}...",  # Truncate for readability
            mimeType="text/plain",
        )
        for id, title, summary in rows
    ]


@server.read_resource()
async def handle_read_resource(uri: AnyUrl) -> str:
    """
    Read a specific note's content by its URI.
    The note name is extracted from the URI host component.
    """
    if uri.scheme != "note":
        raise ValueError(f"Unsupported URI scheme: {uri.scheme}")

    name = uri.path
    if name is not None:
        name = name.lstrip("/")
        return notes[name]
    raise ValueError(f"Note not found: {name}")


@server.list_prompts()
async def handle_list_prompts() -> list[types.Prompt]:
    """
    List available prompts.
    Each prompt can have optional arguments to customize its behavior.
    """
    return [
        types.Prompt(
            name="summarize-notes",
            description="Creates a summary of all notes",
            arguments=[
                types.PromptArgument(
                    name="style",
                    description="Style of the summary (brief/detailed)",
                    required=False,
                )
            ],
        )
    ]


@server.get_prompt()
async def handle_get_prompt(
    name: str, arguments: dict[str, str] | None
) -> types.GetPromptResult:
    """
    Generate a prompt by combining arguments with server state.
    The prompt includes all current notes and can be customized via arguments.
    """
    if name != "summarize-notes":
        raise ValueError(f"Unknown prompt: {name}")

    style = (arguments or {}).get("style", "brief")
    detail_prompt = " Give extensive details." if style == "detailed" else ""

    return types.GetPromptResult(
        description="Summarize the current notes",
        messages=[
            types.PromptMessage(
                role="user",
                content=types.TextContent(
                    type="text",
                    text=f"Here are the current notes to summarize:{detail_prompt}\n\n"
                    + "\n".join(
                        f"- {name}: {content}" for name, content in notes.items()
                    ),
                ),
            )
        ],
    )


@server.list_tools()
async def handle_list_tools() -> list[types.Tool]:
    """List available research tools with detailed schemas."""
    return [
        types.Tool(
            name="search",
            description="Perform comprehensive research on a topic, using multiple optimized queries and summarizing the results",
            inputSchema={
                "type": "object",
                "properties": {
                    "purpose": {
                        "type": "string",
                        "description": """Why you need this information - provide detailed context to generate better queries.
                        
                        Include:
                        - Your broader research context or goal
                        - How you plan to use this information
                        - Any specific perspective or lens you're analyzing from
                        - Level of technical depth needed
                        - Timeline relevance (historical, current, future trends)
                        
                        Example: "I'm writing an academic paper analyzing how luxury brands commodify spiritual practices, 
                        focusing on the intersection of capitalism and cultural appropriation in the wellness industry"
                        """,
                    },
                    "question": {
                        "type": "string",
                        "description": """Your specific research question or topic - be precise and detailed.
                        
                        Include:
                        - Key concepts or terms you're investigating
                        - Specific aspects you want to focus on
                        - Any relevant timeframes
                        - Types of sources that would be most valuable
                        - Any specific examples or cases you're interested in
                        
                        Example: "How do modern wellness companies incorporate and market traditional spiritual practices? 
                        Looking for both academic analysis and concrete examples from major brands"
                        """,
                    },
                },
                "required": ["purpose", "question"],
            },
        )
    ]


@server.call_tool()
async def handle_call_tool(
    name: str, arguments: dict | None
) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
    """Handle research tool execution."""
    if name != "search":
        raise ValueError(f"Unknown tool: {name}")
    if not arguments:
        raise ValueError("Missing arguments")

    purpose = arguments.get("purpose")
    question = arguments.get("question")
    if not purpose or not question:
        raise ValueError("Missing purpose or question")

    try:
        # Generate optimized queries based on purpose and question
        queries = await generate_queries(purpose=purpose, question=question)

        # Execute all queries concurrently
        search_tasks = []
        for query in queries:
            task: list[Result] = perform_exa_search(
                query_text=query.text,
                category=query.category,
                livecrawl=query.livecrawl,
            )
            search_tasks.append(task)
            print(task[0].title)
        search_results_list: list[list[Result]] = await asyncio.gather(*search_tasks)

        # Convert raw results to ExaResult objects
        raw_results: list[list[ExaResult]] = [
            [
                ExaResult(
                    url=result.url,
                    id=result.id,
                    title=result.title,
                    score=result.score,
                    published_date=result.published_date,
                    author=result.author,
                    text=result.text,
                    highlights=result.highlights,
                    highlight_scores=result.highlight_scores,
                )
                for result in results
            ]
            for results in search_results_list
        ]
        # ensure ExaResults sorted by score, highest first
        for results in raw_results:
            results.sort(key=lambda x: x.score, reverse=True)

        # create ids for them
        for results in raw_results:
            for result in results:
                result.id = await word_id_generator.generate_result_id()

        # Clean and process results
        cleaned_content_list: list[list[CleanedContent]] = [
            await clean_content(
                original_query=QueryRequest(purpose=purpose, question=question),
                content=results,
            )
            for results in raw_results
        ]

        # Store results and generate summaries
        summaries = []
        for content in cleaned_content_list:
            # Generate unique word ID
            result_id = await word_id_generator.generate_result_id()

            # Store in database with all fields
            async with db_lock:
                cursor.execute(
                    """
                    INSERT INTO results (
                        id, 
                        title, 
                        author, 
                        url,
                        summary, 
                        relevance_summary,
                        full_text, 
                        cleaned_content,
                        query_purpose, 
                        query_question,
                        created_at,
                        exa_id,
                        raw_highlights
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                """,
                    (
                        result_id,
                        content.title,
                        content.author,
                        content.url,
                        content.summary,
                        content.relevance_summary,
                        content.text,  # Original full text
                        content.content,  # Cleaned/dense version
                        purpose,
                        question,
                    ),
                )
                conn.commit()

            # Format summary for output in markdown
            summaries.append(f"""\
# [{result_id}] {content.title}
**Author:** {content.author}

## Relevance to Your Query
{content.relevance_summary}

## Summary
{content.summary}
""")

        # Notify clients that new resources are available
        await server.request_context.session.send_resource_list_changed()

        # Return formatted summaries
        return [types.TextContent(type="text", text="\n\n".join(summaries))]

    except Exception as e:
        # Log the error and return a meaningful message
        print(f"Error during search: {str(e)}")
        return [
            types.TextContent(type="text", text=f"Error performing research: {str(e)}")
        ]


async def main():
    # Run the server using stdin/stdout streams
    async with mcp.stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="research_mcp",
                server_version="0.1.0",
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        )
