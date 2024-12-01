from __future__ import annotations

import asyncio
import logging
import os
import sys

import dotenv
import mcp
import stackprinter
from braintrust import current_span, init_logger, traced
from exa_py import Exa
from mcp import types
from mcp.server import NotificationOptions, Server
from mcp.server.models import InitializationOptions
from pydantic import AnyUrl

from research_mcp.research_service import ResearchService
from research_mcp.schemas import (
    format_full_texts_response,
    format_query_results_summary,
    format_resource_content,
    format_result_summary,
    get_search_tool_schema,
    wrap_in_results_tag,
)
from research_mcp.word_ids import WordIDGenerator


# Load environment variables and setup
dotenv.load_dotenv()
stackprinter.set_excepthook(style='darkbg2')

# Initialize logger
init_logger(project='Research MCP')

# Initialize Exa client
EXA_API_KEY = os.getenv('EXA_API_KEY')
assert EXA_API_KEY, 'EXA_API_KEY environment variable must be set'
exa = Exa(EXA_API_KEY)

# Initialize the server and service
server = Server('research_mcp')
word_id_generator = WordIDGenerator()
research_service = ResearchService(exa, word_id_generator, server=server)

# Configure logging
logger = logging.getLogger('research-mcp')
logger.setLevel(logging.INFO)


@server.list_resources()
async def handle_list_resources() -> list[types.Resource]:
    """List available result resources, focusing on most relevant and recent."""
    try:
        results = await research_service.list_resources()

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
        result = await research_service.get_resource(result_id)

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
            ),
            types.Tool(
                name='get_full_texts',
                description='Retrieve full text content for a list of result IDs',
                inputSchema={
                    'type': 'object',
                    'properties': {
                        'result_ids': {
                            'type': 'array',
                            'items': {'type': 'string'},
                            'description': 'List of result IDs to retrieve full texts for',
                        }
                    },
                    'required': ['result_ids'],
                },
            ),
        ]
        return tools
    except Exception:
        raise


@server.call_tool()
@traced(type='task')
async def handle_call_tool(name: str, arguments: dict | None) -> list[types.TextContent]:
    """Handle research tool execution."""
    try:
        if name == 'search':
            current_span().set_attributes(name=f'tool.{name}')

            if not arguments:
                raise ValueError('Missing arguments')

            purpose = arguments.get('purpose')
            question = arguments.get('question')

            if not purpose or not question:
                raise ValueError('Missing purpose or question')

            # Use research service to perform the search
            research_results = await research_service.research(purpose=purpose, question=question)

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
                            author=raw_result.author[:60] + '...' if raw_result.author else None,
                            relevance_summary=summarized_result.relevance_summary,
                            summary=summarized_result.dense_summary,
                            published_date=raw_result.published_date,
                        )
                    )

            # Notify clients that new resources are available
            await server.request_context.session.send_resource_list_changed()

            result = [
                types.TextContent(type='text', text=wrap_in_results_tag('\n\n'.join(summaries)))
            ]
            return result

        elif name == 'get_full_texts':
            current_span().set_attributes(name=f'tool.{name}')

            if not arguments or 'result_ids' not in arguments:
                raise ValueError('Missing result_ids argument')

            result_ids = arguments['result_ids']
            if not isinstance(result_ids, list):
                raise ValueError('result_ids must be a list')

            # Use research service to get full texts
            results = await research_service.get_full_texts(result_ids)

            # Format results using the schema formatter
            formatted_results = [
                {
                    'id': result.id,
                    'title': result.title,
                    'author': result.author,  # Don't truncate for full text view
                    'content': result.text,
                    'published_date': result.published_date,
                }
                for result in results
            ]

            combined_text = format_full_texts_response(formatted_results)

            return [types.TextContent(type='text', text=combined_text)]

        else:
            raise ValueError(f'Unknown tool: {name}')

    except Exception as e:
        raise e


def clean_author(author: str | None) -> str | None:
    """Clean author name."""
    if author and len(author) > 60:
        return author[:60] + '...'
    return author


@server.set_logging_level()
async def set_logging_level(level: types.LoggingLevel) -> types.EmptyResult:
    """Handle requests to change the logging level."""
    logger.setLevel(level.upper())
    await server.request_context.session.send_log_message(
        level='info', data=f'Log level set to {level}', logger='research-mcp'
    )
    return types.EmptyResult()


async def main():
    # Run the server using stdin/stdout streams
    async with mcp.stdio_server() as (read_stream, write_stream):
        try:
            init_options = InitializationOptions(
                server_name='research_mcp',
                server_version='0.1.0',
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(
                        prompts_changed=False,
                        resources_changed=False,
                        tools_changed=False,
                    ),
                    experimental_capabilities={},
                ),
            )

            await server.run(
                read_stream,
                write_stream,
                init_options,
            )
        except Exception as e:
            print(f'Server error: {e}', file=sys.stderr)
            raise


if __name__ == '__main__':
    asyncio.run(main())
