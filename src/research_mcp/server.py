from __future__ import annotations

import asyncio
import logging
import os

import dotenv
import mcp
import stackprinter  # type: ignore
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
        logger.error('Error listing resources', exc_info=True)
        raise


@server.read_resource()
async def handle_read_resource(uri: AnyUrl) -> str:
    """Read full content of a specific result."""
    try:
        if not uri.scheme == 'research':
            raise ValueError(f'Unsupported URI scheme: {uri.scheme}')

        # Ensure path exists and is a string
        path = uri.path
        if not isinstance(path, str):
            raise ValueError('URI path must be a string')

        result_id = path.strip('/').split('/')[-1]
        result = await research_service.get_resource(result_id)

        # Convert SQLAlchemy Column types to strings
        return format_resource_content(
            result_id=str(result.id),
            title=str(result.title),
            author=clean_author(str(result.author) if result.author else None),
            content=str(result.text),
            published_date=str(result.published_date) if result.published_date else None,
        )
    except Exception:
        logger.error('Error reading resource', exc_info=True)
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
@traced(type='task')  # type: ignore
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
            try:
                research_results = await research_service.research(
                    purpose=purpose, question=question
                )
            except Exception:
                logger.error('Error performing research', exc_info=True)
                raise

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
                logger.error('Missing result_ids argument')
                raise ValueError('Missing result_ids argument')

            result_ids = arguments['result_ids']
            if not isinstance(result_ids, list):
                logger.error(f'Invalid result_ids type: {type(result_ids)}')
                raise ValueError('result_ids must be a list')

            logger.info(f'Fetching full texts for IDs: {result_ids}')

            try:
                results = await research_service.get_full_texts(result_ids)
                logger.info(f'Successfully retrieved {len(results)} results')
            except Exception as e:
                logger.error(f'Error retrieving full texts: {e!s}', exc_info=True)
                raise

            try:
                formatted_results = [
                    {
                        'id': str(result.id),
                        'title': str(result.title),
                        'author': str(result.author) if result.author else None,
                        'content': str(result.text),
                        'published_date': str(result.published_date)
                        if result.published_date
                        else None,
                    }
                    for result in results
                ]
                logger.info(f'Successfully formatted {len(formatted_results)} results')
            except Exception as e:
                logger.error(f'Error formatting results: {e!s}', exc_info=True)
                raise

            try:
                combined_text = format_full_texts_response(formatted_results)
                return [types.TextContent(type='text', text=combined_text)]
            except Exception as e:
                logger.error(f'Error in format_full_texts_response: {e!s}', exc_info=True)
                raise

        else:
            raise ValueError(f'Unknown tool: {name}')
    except Exception as e:
        logger.error(f'Tool execution failed: {e!s}', exc_info=True)
        return [types.TextContent(type='text', text=f'Error: Tool execution failed - {e!s}')]


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
            logger.error(f'Server error: {e}', exc_info=True)


if __name__ == '__main__':
    asyncio.run(main())
