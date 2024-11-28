from __future__ import annotations

import asyncio
import multiprocessing
import os
from collections import deque
from datetime import UTC, datetime
from time import time

import dotenv
import mcp
import stackprinter
from async_lru import alru_cache as lru_cache
from braintrust import init_logger, traced
from exa_py import Exa

# from exa_py.api import SearchResponse
from mcp import types
from mcp.server import NotificationOptions, Server
from mcp.server.models import InitializationOptions
from pydantic import AnyUrl
from sqlalchemy import select

from research_mcp.db import ExaQuery, QueryResult, Result as DBResult, db
from research_mcp.dspy_init import get_dspy_lm
from research_mcp.models import QueryRequest, QueryResults, ResearchResults
from research_mcp.query_generation import generate_queries
from research_mcp.schemas import (
    format_query_results_summary,
    format_resource_content,
    format_result_summary,
    get_search_tool_schema,
    wrap_in_results_tag,
)
from research_mcp.summarize import SearchResultItem, summarize_search_items
from research_mcp.word_ids import WordIDGenerator


DEFAULT_WORKERS = min(multiprocessing.cpu_count() * 2, 32)

# Initialize it early
get_dspy_lm()

# Load environment variables
dotenv.load_dotenv()
stackprinter.set_excepthook(style='darkbg2')


# Move the RateLimiter class definition before its usage
class RateLimiter:
    """Token bucket rate limiter"""

    def __init__(self, rate: float, burst: int = 1):
        self.rate = rate  # tokens per second
        self.burst = burst  # max tokens
        self.tokens = burst  # current tokens
        self.last_update = time()
        self.lock = asyncio.Lock()
        # Track request timestamps for debugging
        self.request_times = deque(maxlen=100)

    async def acquire(self):
        """Acquire a token, waiting if necessary"""
        async with self.lock:
            while self.tokens <= 0:
                now = time()
                time_passed = now - self.last_update
                self.tokens = min(self.burst, self.tokens + time_passed * self.rate)
                self.last_update = now
                if self.tokens <= 0:
                    await asyncio.sleep(1 / self.rate)

            self.tokens -= 1
            self.request_times.append(time())

    def get_request_rate(self, window: float = 1.0) -> float:
        """Calculate current request rate over window seconds"""
        now = time()
        recent = [t for t in self.request_times if now - t <= window]
        return len(recent) / window if recent else 0


# Initialize Exa client
EXA_API_KEY = os.getenv('EXA_API_KEY')
assert EXA_API_KEY, 'EXA_API_KEY environment variable must be set'
exa = Exa(EXA_API_KEY)

# Initialize the server
server = Server('research_mcp')

# Initialize logger and Word ID Generator
init_logger(project='Research MCP')
word_id_generator = WordIDGenerator()

# Initialize rate limiter
exa_limiter = RateLimiter(rate=3)  # Slightly under 5/s to be safe


@traced(type='function')
@lru_cache(maxsize=100)
async def perform_exa_search(query_text: str, category: str | None = None, livecrawl: bool = False):
    """
    Perform Exa search asynchronously.
    Note: type hint removed for optimization

    Returns:
        exa_py.api.SearchResponse
        []
    """
    assert query_text.strip(), 'Query text cannot be empty'
    search_args = {
        'num_results': 10,
        'type': 'neural',
        'text': True,
        'use_autoprompt': False,
        'category': category,
        'livecrawl': 'always' if livecrawl else None,
    }
    # Remove None values from search_args
    search_args = {k: v for k, v in search_args.items() if v is not None}

    # Wait for rate limit
    await exa_limiter.acquire()

    # If Exa client supports async, use it directly; else, use to_thread
    results = await asyncio.to_thread(exa.search_and_contents, query_text, **search_args)
    return results


@server.list_resources()
async def handle_list_resources() -> list[types.Resource]:
    """List available result resources, focusing on most relevant and recent."""
    try:
        async with db() as session:
            stmt = (
                select(DBResult)
                .order_by(DBResult.relevance_score.desc(), DBResult.created_at.desc())
                .limit(25)
            )
            results: list[DBResult] = (await session.execute(stmt)).scalars().all()

        resources = [
            types.Resource(
                uri=AnyUrl(f'research://results/{res.id}'),
                name=f'[{res.id}] {res.title[:50]}...',
                description=f'Summary: {res.dense_summary[:150]}...',
                mimeType='text/plain',
            )
            for res in results
        ]

        return resources
    except Exception:
        raise


@server.read_resource()
async def handle_read_resource(uri: AnyUrl) -> str:
    """Read full content of a specific result."""
    try:
        if not uri.scheme == 'research':
            raise ValueError(f'Unsupported URI scheme: {uri.scheme}')

        result_id = uri.path.strip('/').split('/')[-1]

        async with db() as session:
            stmt = select(DBResult).where(DBResult.id == result_id)
            result: DBResult = (await session.execute(stmt)).scalars().first()

            if not result:
                raise ValueError(f'Result not found: {result_id}')

        return format_resource_content(
            result_id=result.id,
            title=result.title,
            author=clean_author(result.author),
            content=result.text,
            published_date=result.published_date,
        )
    except Exception:
        raise


@server.list_tools()
async def handle_list_tools() -> list[types.Tool]:
    """List available research tools with detailed schemas."""
    try:
        tools = [
            types.Tool(
                name='search',
                description=(
                    'Perform comprehensive research on a topic, using multiple optimized '
                    'queries and summarizing the results'
                ),
                inputSchema=get_search_tool_schema(),
            )
        ]
        return tools
    except Exception:
        raise


# TODO: Add tool for answering questions based on a document
# TODO: Get full texts tool that given ids, returns full text of all results in them


@server.call_tool()
@traced(name='Research Request', type='task')
async def handle_call_tool(
    name: str, arguments: dict | None
) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
    """Handle research tool execution."""
    try:
        if name != 'search':
            raise ValueError(f'Unknown tool: {name}')
        if not arguments:
            raise ValueError('Missing arguments')

        purpose = arguments.get('purpose')
        question = arguments.get('question')
        if not purpose or not question:
            raise ValueError('Missing purpose or question')

        # Generate optimized queries based on purpose and question
        search_queries = await generate_queries(purpose=purpose, question=question)
        assert search_queries, 'No search queries were generated'

        # Initialize our research results container
        research_results = ResearchResults(purpose=purpose, question=question, query_results=[])

        # Process each query concurrently to get raw results
        query_tasks = [process_search_query(search_query) for search_query in search_queries]
        raw_query_results = await asyncio.gather(*query_tasks)

        # Now process all content cleaning concurrently
        cleaning_tasks = []
        for query_result in raw_query_results:
            cleaning_task = summarize_search_items(
                original_query=QueryRequest(purpose=purpose, question=question),
                content=query_result.raw_results,
            )
            cleaning_tasks.append(cleaning_task)

        # Wait for all content cleaning to complete
        cleaned_results = await asyncio.gather(*cleaning_tasks)

        # Combine raw results with cleaned results
        for query_result, cleaned_result in zip(raw_query_results, cleaned_results, strict=True):
            query_result.summarized_results = cleaned_result
            research_results.query_results.append(query_result)

        # Store all results in database
        await store_results_in_db(research_results, purpose, question)

        # Generate summaries for output, grouped by query
        summaries = []
        for query_result in research_results.query_results:
            # Add query header using schema formatter
            summaries.append(
                format_query_results_summary(
                    query_text=query_result.query.text,
                    category=query_result.query.category,
                    livecrawl=query_result.query.livecrawl,
                )
            )

            # Add results for this query using schema formatter
            for raw_result, summarized_result in zip(
                query_result.raw_results, query_result.summarized_results, strict=False
            ):
                summaries.append(
                    format_result_summary(
                        result_id=raw_result.id,
                        title=raw_result.title,
                        author=raw_result.author[:60] + '...',
                        relevance_summary=summarized_result.relevance_summary,
                        summary=summarized_result.text,
                        published_date=raw_result.published_date,
                    )
                )

        # Notify clients that new resources are available
        await server.request_context.session.send_resource_list_changed()

        result = [types.TextContent(type='text', text=wrap_in_results_tag('\n\n'.join(summaries)))]
        return result

    except Exception as e:
        raise e


async def process_search_query(search_query):
    """Process a single search query and return the raw results."""
    # Store query in database
    async with db() as session:
        exa_query = ExaQuery(
            query_text=search_query.text,
            category=str(search_query.category) if search_query.category else None,
            livecrawl=search_query.livecrawl or False,
        )
        session.add(exa_query)
        await session.commit()
        query_id = exa_query.id

    # Execute search
    exa_results = await perform_exa_search(
        query_text=search_query.text,
        category=search_query.category,
        livecrawl=search_query.livecrawl,
    )
    exa_results = exa_results.results

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
        )
        for r in exa_results
    ]

    return QueryResults(
        query_id=query_id,
        query=search_query,
        raw_results=raw_results,
        summarized_results=[],  # Will be filled later
    )


async def store_results_in_db(research_results, purpose, question):
    """Store all results in the database."""
    async with db() as session:
        result_ids = set()
        for query_result in research_results.query_results:
            result_ids.update(r.id for r in query_result.raw_results)

        # Fetch existing results and links
        existing_results_stmt = select(DBResult).where(DBResult.id.in_(result_ids))
        existing_results = (await session.execute(existing_results_stmt)).scalars().all()
        existing_result_ids = {r.id for r in existing_results}

        # Prepare new results and links
        new_results = []
        new_links = []
        for query_result in research_results.query_results:
            for raw_result, summarized_result in zip(
                query_result.raw_results, query_result.summarized_results, strict=False
            ):
                if raw_result.id not in existing_result_ids:
                    new_result = DBResult(
                        id=raw_result.id,
                        title=raw_result.title or None,
                        author=raw_result.author or None,
                        url=raw_result.url or None,
                        dense_summary=summarized_result.dense_summary,
                        relevance_summary=summarized_result.relevance_summary,
                        text=raw_result.text,
                        relevance_score=raw_result.score,
                        query_purpose=purpose,
                        query_question=question,
                        published_date=raw_result.published_date,
                    )
                    new_results.append(new_result)
                else:
                    # Update existing result's updated_at timestamp
                    existing_result = next(
                        (res for res in existing_results if res.id == raw_result.id), None
                    )
                    if existing_result:
                        existing_result.updated_at = datetime.now(UTC)

                # Prepare link between query and result
                new_links.append(
                    QueryResult(query_id=query_result.query_id, result_id=raw_result.id)
                )

        # Bulk save new results and links
        if new_results:
            session.add_all(new_results)
        if new_links:
            session.add_all(new_links)
        await session.commit()


async def main():
    # Run the server using stdin/stdout streams
    async with mcp.stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name='research_mcp',
                server_version='0.1.0',
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        )


def clean_author(author: str) -> str:
    """Clean author name."""
    if author and len(author) > 60:  # noqa: PLR2004
        return author[:60] + '...'
    return author


if __name__ == '__main__':
    print('hey')
