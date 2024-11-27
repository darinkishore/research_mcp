import asyncio
import json
import os
import sqlite3

import dotenv
import mcp
import mcp.types as types
import stackprinter
from exa_py import Exa
from exa_py.api import Result
from mcp.server import NotificationOptions, Server
from mcp.server.models import InitializationOptions
from pydantic import AnyUrl

from research_mcp.clean_content import SearchResultItem, clean_content
from research_mcp.models import QueryRequest, QueryResults, ResearchResults
from research_mcp.query_generation import generate_queries
from research_mcp.word_ids import WordIDGenerator

# implicit global state with the dspy modules being imported already initialized in the functions

# Load environment variables
dotenv.load_dotenv()
stackprinter.set_excepthook(style="darkbg2")


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

# Add near the top after initialization
assert os.getenv("EXA_API_KEY"), "EXA_API_KEY environment variable must be set"


async def perform_exa_search(
    query_text: str, category: str | None = None, livecrawl: bool = False
) -> list[Result]:
    """Perform Exa search asynchronously."""
    assert query_text.strip(), "Query text cannot be empty"
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
    results: list[Result] = await asyncio.to_thread(exa.search_and_contents, query_text, **search_args)
    return results


server = Server("research_mcp")


@server.list_resources()
async def handle_list_resources() -> list[types.Resource]:
    """List available result resources, focusing on most relevant and recent."""
    async with db_lock:
        # Get recent results, ordered by relevance
        cursor.execute("""
            SELECT id, title, summary 
            FROM results 
            ORDER BY relevance_score DESC, created_at DESC 
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
    """Read full content of a specific result."""
    if not str(uri).startswith("research://results/"):
        raise ValueError(f"Unsupported URI scheme: {uri}")

    result_id = str(uri).split("/")[-1]

    async with db_lock:
        cursor.execute(
            """
            SELECT 
                r.title, r.author, r.cleaned_content, r.summary,
                r.relevance_summary, r.relevance_score,
                r.query_purpose, r.query_question,
                q.query_text, q.category, q.livecrawl
            FROM results r
            JOIN query_results qr ON r.id = qr.result_id
            JOIN exa_queries q ON qr.query_id = q.id
            WHERE r.id = ?
        """,
            (result_id,),
        )
        row = cursor.fetchone()


    if not row:
        raise ValueError(f"Result not found: {result_id}")

    title, author, content, summary, relevance_summary, relevance_score, purpose, question, query_text, category, livecrawl = row

    # Format the query details
    query_details = f"Query: {query_text}"
    if category:
        query_details += f"\nCategory: {category}"
    if livecrawl:
        query_details += "\nWith live crawling enabled"

    return f"""# [{result_id}]
## Title: {title}

**Author:** {author}
<context>
## Original Query Context

This is why we were looking for this information:

**Purpose:** {purpose}
**Question:** {question}

This is what was searched to find this information:

{query_details}

Relevance Score: {relevance_score}
Relevance to Query: {relevance_summary}

</context>

## Full Content

<content>
{content}
</content>
"""


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
        search_queries = await generate_queries(purpose=purpose, question=question)
        assert search_queries, "No search queries were generated"

        # Initialize our research results container
        research_results = ResearchResults(
            purpose=purpose, question=question, query_results=[]
        )

        # Process each query and collect results
        for search_query in search_queries:
            # Store query in database
            async with db_lock:
                cursor.execute(
                    """
                    INSERT INTO exa_queries (query_text, category, livecrawl)
                    VALUES (?, ?, ?)
                    RETURNING id
                    """,
                    (search_query.text, search_query.category, search_query.livecrawl),
                )
                query_id = cursor.fetchone()[0]
                conn.commit()

            # Execute search
            exa_results = await perform_exa_search(
                query_text=search_query.text,
                category=search_query.category,
                livecrawl=search_query.livecrawl,
            )

            # Convert to our models
            raw_results = [
                SearchResultItem(
                    url=r.url,
                    id=await word_id_generator.generate_result_id(),
                    title=r.title,
                    score=r.score,
                    published_date=r.published_date,
                    author=r.author,
                    text=r.text,
                    highlights=r.highlights,
                    highlight_scores=r.highlight_scores,
                )
                for r in exa_results
            ]

            # Process the results
            processed_results = await clean_content(
                original_query=QueryRequest(purpose=purpose, question=question),
                content=raw_results,
            )

            # Add to our research results
            research_results.query_results.append(
                QueryResults(
                    query_id=query_id,
                    query=search_query,
                    raw_results=raw_results,
                    processed_results=processed_results,
                )
            )

        # Store all results in database
        async with db_lock:
            for query_result in research_results.query_results:
                for raw_result, processed_result in zip(
                    query_result.raw_results, query_result.processed_results
                ):
                    if not hasattr(raw_result, "id") or not raw_result.id:
                        raw_result.id = await word_id_generator.generate_result_id()

                    cursor.execute(
                        """
                        INSERT INTO results (
                            id, title, author, url, summary, relevance_summary,
                            full_text, cleaned_content, relevance_score,
                            query_purpose, query_question, exa_id, raw_highlights,
                            metadata
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(id) DO UPDATE SET
                            updated_at = CURRENT_TIMESTAMP
                        """,
                        (
                            raw_result.id,
                            processed_result.title,
                            processed_result.author,
                            processed_result.url,
                            processed_result.summary,
                            processed_result.relevance_summary,
                            raw_result.text,
                            processed_result.content,
                            raw_result.score,
                            purpose,
                            question,
                            raw_result.id,
                            json.dumps(raw_result.highlights),
                            json.dumps(
                                {
                                    "published_date": raw_result.published_date,
                                    "highlight_scores": raw_result.highlight_scores,
                                }
                            ),
                        ),
                    )

                    # Link result to query
                    cursor.execute(
                        """
                        INSERT INTO query_results (query_id, result_id)
                        VALUES (?, ?)
                        """,
                        (query_result.query_id, raw_result.id),
                    )
            conn.commit()

        # Generate summaries for output, grouped by query
        summaries = []
        for query_result in research_results.query_results:
            # Add query header
            summaries.append(
                f"""
# Results for Query: {query_result.query.text}
{"Category: " + query_result.query.category if query_result.query.category else ""}
""".strip()
            )

            # Add results for this query
            for raw_result, processed_result in zip(
                query_result.raw_results, query_result.processed_results
            ):
                summaries.append(f"""\
## [{raw_result.id}] {processed_result.title}
**Author:** {processed_result.author}

### Relevance to Your Query
{processed_result.relevance_summary}

### Summary
{processed_result.summary}
""")

        # Notify clients that new resources are available
        await server.request_context.session.send_resource_list_changed()

        return [types.TextContent(type="text", text="\n\n".join(summaries))]

    except Exception as e:
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

def clean_author(author: str) -> str:
    """Clean author name"""
    if len(author) > 60:
        return author[:60] + "..."
    return author


if __name__ == "__main__":
    import asyncio

    from research_mcp.models import QueryRequest

    async def inspect_db(section: str):
        """Helper to inspect database state after each step"""
        print(f"\n=== Database State After {section} ===")
        async with db_lock:
            print("\nExa Queries:")
            cursor.execute(
                "SELECT id, query_text, category, livecrawl FROM exa_queries"
            )
            queries = cursor.fetchall()
            for q in queries:
                print(f"ID: {q[0]}, Query: {q[1]}, Category: {q[2]}, LiveCrawl: {q[3]}")

            print("\nResults:")
            cursor.execute("SELECT id, title, author, relevance_score FROM results")
            results = cursor.fetchall()
            for r in results:
                print(f"ID: {r[0]}, Title: {r[1]}, Author: {r[2]}, Score: {r[3]}")

            print("\nQuery-Result Links:")
            cursor.execute("""
                SELECT eq.query_text, r.id, r.title 
                FROM query_results qr 
                JOIN exa_queries eq ON qr.query_id = eq.id 
                JOIN results r ON qr.result_id = r.id
            """)
            links = cursor.fetchall()
            for l in links:
                print(f"Query: {l[0]}, Result: {l[1]} ({l[2]})")

    async def test_components():
        print("\n=== Testing Individual Components ===\n")

        # 1. Test word ID generation
        print("Testing Word ID Generation...")
        test_id = await word_id_generator.generate_result_id()
        print(f"Generated ID: {test_id}")
        await inspect_db("Word ID Generation")

        # 2. Test query generation
        print("\nTesting Query Generation...")
        test_purpose = "I'm writing a paper about AI safety"
        test_question = "What are the main concerns about large language models?"
        queries = await generate_queries(purpose=test_purpose, question=test_question)
        print("Generated Queries:")
        for q in queries:
            print(f"- {q.text}")
            if q.category:
                print(f"  Category: {q.category}")
            if q.livecrawl:
                print("  With livecrawl")
        await inspect_db("Query Generation")

        # 3. Test Exa search
        print("\nTesting Exa Search...")
        test_query = queries[0]  # Use first generated query
        search_response: list[Result] = await perform_exa_search(
            query_text=test_query.text,
            category=test_query.category,
            livecrawl=test_query.livecrawl,
        )
        results = search_response.results

        print(f"Found {len(results)} results")
        print(f"First result title: {results[0].title if results else 'No results'}")
        await inspect_db("Exa Search")

        # 4. Test content cleaning
        print("\nTesting Content Cleaning...")
        query_request = QueryRequest(purpose=test_purpose, question=test_question)
        raw_results = [
            SearchResultItem(
                url=r.url,
                id=await word_id_generator.generate_result_id(),  # Generate unique IDs
                title=r.title,
                score=r.score if hasattr(r, "score") else 0.0,
                published_date=r.published_date if hasattr(r, "published_date") else "",
                author=lambda: clean_author(r.author) if hasattr(r, "author") else "Unknown",
                text=r.text,
                highlights=r.highlights if hasattr(r, "highlights") else None,
                highlight_scores=r.highlight_scores
                if hasattr(r, "highlight_scores")
                else None,
            )
            for r in results[:2]  # Just test with first two results
        ]
        cleaned_results = await clean_content(query_request, raw_results)
        print(f"Cleaned {len(cleaned_results)} results")
        if cleaned_results:
            print("First cleaned result:")
            print(f"Title: {cleaned_results[0].title}")
            print(f"Author: {cleaned_results[0].author}")
            print(f"Relevance: {cleaned_results[0].relevance_summary[:100]}...")
        await inspect_db("Content Cleaning")

        # 5. Test database operations
        print("\nTesting Database Operations...")
        async with db_lock:
            # Store a test query
            cursor.execute(
                """
                INSERT INTO exa_queries (query_text, category, livecrawl)
                VALUES (?, ?, ?) RETURNING id
                """,
                (test_query.text, test_query.category, test_query.livecrawl),
            )
            query_id = cursor.fetchone()[0]

            # Store a test result
            if cleaned_results:
                result = cleaned_results[0]
                raw = raw_results[0]
                cursor.execute(
                    """
                    INSERT INTO results (
                        id, title, author, url, summary, relevance_summary,
                        full_text, cleaned_content, relevance_score,
                        query_purpose, query_question, exa_id, raw_highlights
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        raw.id,
                        result.title,
                        result.author,
                        result.url,
                        result.summary,
                        result.relevance_summary,
                        raw.text,
                        result.content,
                        raw.score,
                        test_purpose,
                        test_question,
                        raw.id,
                        json.dumps(raw.highlights),
                    ),
                )


                # Link query and result
                cursor.execute(
                    """
                    INSERT INTO query_results (query_id, result_id)
                    VALUES (?, ?)
                    """,
                    (query_id, raw.id),
                )
            conn.commit()
        await inspect_db("Database Operations")

        # 6. Test resource retrieval
        print("\nTesting Resource Retrieval...")
        resources = await handle_list_resources()
        print(f"Listed {len(resources)} resources")
        if resources:
            print("\nTesting Resource Reading...")
            first_uri = resources[0].uri
            content = await handle_read_resource(first_uri)
            print(f"Retrieved content length: {len(content)}")
            print("\nFirst 200 chars of content:")
            print(content[:200])
        await inspect_db("Resource Retrieval")

        print("\n=== All Tests Complete ===\n")

    # Run all tests
    asyncio.run(test_components())
