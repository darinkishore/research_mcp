import asyncio
import datetime
import os
from datetime import datetime

import dotenv
import mcp
import mcp.types as types
import stackprinter
from braintrust import init_logger, traced
from exa_py import Exa
from exa_py.api import SearchResponse
from mcp.server import NotificationOptions, Server
from mcp.server.models import InitializationOptions
from pydantic import AnyUrl
from sqlalchemy import select

from research_mcp.clean_content import SearchResultItem, clean_content
from research_mcp.db import ExaQuery, QueryResult, db
from research_mcp.db import Result as DBResult
from research_mcp.models import QueryRequest, QueryResults, ResearchResults
from research_mcp.query_generation import generate_queries
from research_mcp.schemas import (
    format_query_results_summary,
    format_resource_content,
    format_result_summary,
    get_search_tool_schema,
)
from research_mcp.word_ids import WordIDGenerator


# implicit global state with the dspy modules being imported already initialized in the functions

# spantypes:
# ["llm", "score", "function", "eval", "task", "tool"]

# Load environment variables
dotenv.load_dotenv()
stackprinter.set_excepthook(style='darkbg2')


# Initialize Exa client
exa = Exa(os.getenv('EXA_API_KEY'))

# Initialize the server
server = Server('research_mcp')

# Database setup with locking
# Initialize Word ID Generator
word_id_generator = WordIDGenerator()

# Add near the top after initialization
assert os.getenv('EXA_API_KEY'), 'EXA_API_KEY environment variable must be set'

logger = init_logger(project='Research MCP')


@traced(type='function')
async def perform_exa_search(
    query_text: str, category: str | None = None, livecrawl: bool = False
) -> SearchResponse:
    """Perform Exa search asynchronously."""
    assert query_text.strip(), 'Query text cannot be empty'
    search_args = {
        'highlights': True,
        'num_results': 10,
        'type': 'neural',
        'text': True,
        'use_autoprompt': False,
    }
    if category is not None:
        search_args['category'] = category
    if livecrawl:
        search_args['livecrawl'] = 'always'
    results: SearchResponse = await asyncio.to_thread(
        exa.search_and_contents, query_text, **search_args
    )
    return results


server = Server('research_mcp')


@server.list_resources()
async def handle_list_resources() -> list[types.Resource]:
    """List available result resources, focusing on most relevant and recent."""
    try:
        async with db() as session:
            stmt = (
                select(DBResult)
                .order_by(DBResult.relevance_score.desc(), DBResult.created_at.desc())
                .limit(25)
                # TODO: joinedload
                .options()
            )
            results = await session.execute(stmt)
            rows = results.scalars().all()

        resources = [
            types.Resource(
                uri=AnyUrl(f'research://results/{res.id}'),
                name=f'[{res.id}] {res.title[:50]}...',
                description=f'Summary: {res.summary[:150]}...',
                mimeType='text/plain',
            )
            for res in rows
        ]

        return resources
    except Exception as e:
        logger.error(f'Error in list_resources: {e!s}')
        raise


@server.read_resource()
async def handle_read_resource(uri: AnyUrl) -> str:
    """Read full content of a specific result."""
    try:
        if not str(uri).startswith('research://results/'):
            raise ValueError(f'Unsupported URI scheme: {uri}')

        result_id = str(uri).split('/')[-1]

        async with db() as session:
            stmt = select(DBResult).where(DBResult.id == result_id)
            result = (await session.execute(stmt)).scalars().first()

            if not result:
                raise ValueError(f'Result not found: {result_id}')

        return format_resource_content(
            result_id=result.id,
            title=result.title,
            author=result.author[:60] + '...' if result.author else None,
            content=result.full_text,
        )
    except Exception as e:
        logger.error(f'Error in read_resource: {e!s}')
        raise


@server.list_tools()
async def handle_list_tools() -> list[types.Tool]:
    """List available research tools with detailed schemas."""
    try:
        tools = [
            types.Tool(
                name='search',
                description='Perform comprehensive research on a topic, using multiple optimized queries and summarizing the results',
                inputSchema=get_search_tool_schema(),
            )
        ]
        return tools
    except Exception as e:
        logger.error(f'Error in list_tools: {e!s}')
        raise


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

        # Process each query and collect results
        for search_query in search_queries:
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
        async with db() as session:
            for query_result in research_results.query_results:
                for raw_result, processed_result in zip(
                    query_result.raw_results, query_result.processed_results, strict=False
                ):
                    if not hasattr(raw_result, 'id') or not raw_result.id:
                        raw_result.id = await word_id_generator.generate_result_id()

                    # Check if result already exists
                    existing_result_stmt = select(DBResult).where(DBResult.id == raw_result.id)
                    existing_result_obj = await session.execute(existing_result_stmt)
                    existing_result = existing_result_obj.scalars().first()

                    if existing_result:
                        existing_result.updated_at = datetime.now(datetime.UTC)
                    else:
                        new_result = DBResult(
                            id=raw_result.id,
                            title=processed_result.title,
                            author=processed_result.author,
                            url=processed_result.url,
                            summary=processed_result.summary,
                            relevance_summary=processed_result.relevance_summary,
                            full_text=raw_result.text,
                            cleaned_content=processed_result.content,
                            relevance_score=raw_result.score,
                            query_purpose=purpose,
                            query_question=question,
                            exa_id=raw_result.id,
                            raw_highlights=raw_result.highlights,
                            metadata={
                                'published_date': raw_result.published_date,
                                'highlight_scores': raw_result.highlight_scores,
                            },
                        )
                        session.add(new_result)

                    # Link result to query
                    existing_link_stmt = select(QueryResult).where(
                        QueryResult.query_id == query_result.query_id,
                        QueryResult.result_id == raw_result.id,
                    )
                    existing_link_obj = await session.execute(existing_link_stmt)
                    existing_link = existing_link_obj.scalars().first()

                    if not existing_link:
                        new_link = QueryResult(
                            query_id=query_result.query_id, result_id=raw_result.id
                        )
                        session.add(new_link)
            await session.commit()

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
            for raw_result, processed_result in zip(
                query_result.raw_results, query_result.processed_results, strict=False
            ):
                summaries.append(
                    format_result_summary(
                        result_id=raw_result.id,
                        title=processed_result.title,
                        author=processed_result.author,
                        relevance_summary=processed_result.relevance_summary,
                        summary=processed_result.summary,
                    )
                )

        # Notify clients that new resources are available
        await server.request_context.session.send_resource_list_changed()

        result = [types.TextContent(type='text', text='\n\n'.join(summaries))]
        return result

    except Exception as e:
        error_msg = f'Error performing research: {e!s}'
        logger.error(f'Error in call_tool: {e!s}')
        return [types.TextContent(type='text', text=error_msg)]


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
    """Clean author name"""
    if len(author) > 60:
        return author[:60] + '...'
    return author
