from __future__ import annotations

import logging
import os

import dotenv
import mcp
import stackprinter  # type: ignore
from braintrust import init_logger, traced
from exa_py import Exa
from mcp import types
from mcp.server import NotificationOptions, Server
from mcp.server.models import InitializationOptions
from pydantic import AnyUrl
from returns.pipeline import is_successful
from returns.unsafe import unsafe_perform_io

from research_mcp.models import ResearchResults
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


dotenv.load_dotenv()
stackprinter.set_excepthook(style='darkbg2')

init_logger(project='Research MCP')

EXA_API_KEY = os.getenv('EXA_API_KEY')
assert EXA_API_KEY, 'EXA_API_KEY environment variable must be set'
exa = Exa(EXA_API_KEY)

server = Server('research_mcp')
word_id_generator = WordIDGenerator()
research_service = ResearchService(exa, word_id_generator, server=server)

logger = logging.getLogger('research-mcp')
logger.setLevel(logging.INFO)


@server.list_resources()
async def handle_list_resources() -> list[types.Resource]:
    # Direct call returns raw values or raise, but no @future_safe on list_resources call here
    # Wait, we never decorated list_resources call in research_service. It's just a normal method returning raw values?
    # The user never said we must wrap them. If we want them safe, we can do:
    # But we do not have @future_safe on them. Let's wrap in try/except:
    try:
        db_results = await research_service.list_resources()
        resources = [
            types.Resource(
                uri=AnyUrl(f'research://results/{res.id}'),
                name=f'[{res.id}] {res.title[:50]}...' if res.title else f'[{res.id}]',
                description=f'Summary: {res.dense_summary[:150]}...' if res.dense_summary else '',
                mimeType='text/plain',
            )
            for res in db_results
        ]
        return resources
    except Exception as e:
        logger.error(f'Error listing resources: {e!s}', exc_info=True)
        # Just raise or return empty list?
        # Let's raise to match the pattern
        raise


@server.read_resource()
async def handle_read_resource(uri: AnyUrl) -> str:
    try:
        path = uri.path
        if not isinstance(path, str):
            raise ValueError('URI path must be a string')
        result_id = path.strip('/').split('/')[-1]

        db_result = await research_service.get_resource(result_id)
        return format_resource_content(
            result_id=str(db_result.id),
            title=str(db_result.title),
            author=clean_author(str(db_result.author) if db_result.author else None),
            content=str(db_result.text),
            published_date=str(db_result.published_date) if db_result.published_date else None,
        )
    except Exception as e:
        logger.error(f'Error reading resource: {e!s}', exc_info=True)
        raise


@server.list_tools()
async def handle_list_tools() -> list[types.Tool]:
    return [
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


@server.call_tool()
@traced(type='task')  # type: ignore
async def handle_call_tool(name: str, arguments: dict | None) -> list[types.TextContent]:
    try:
        if name == 'search':
            if not arguments:
                raise ValueError('Missing arguments')
            purpose = arguments.get('purpose')
            question = arguments.get('question')
            if not purpose or not question:
                raise ValueError('Missing purpose or question')

            # research is @future_safe, so returns FutureResult
            research_future = research_service.research(purpose=purpose, question=question)
            research_io = await research_future.awaitable()
            if not is_successful(research_io):
                err = research_io.failure()
                return [types.TextContent(type='text', text=f'Error: {err}')]
            research_results: ResearchResults = unsafe_perform_io(research_io.unwrap())

            summaries = []
            for query_result in research_results.query_results:
                summaries.append(
                    format_query_results_summary(
                        query_text=query_result.query.text,
                        category=query_result.query.category,
                        livecrawl=query_result.query.livecrawl,
                    )
                )
                for raw_result, summarized_result in zip(
                    query_result.raw_results, query_result.summarized_results, strict=False
                ):
                    summaries.append(
                        format_result_summary(
                            result_id=raw_result.id,
                            title=raw_result.title,
                            author=(raw_result.author[:60] + '...') if raw_result.author else None,
                            relevance_summary=summarized_result.relevance_summary,
                            summary=summarized_result.dense_summary,
                            published_date=raw_result.published_date,
                        )
                    )

            await server.request_context.session.send_resource_list_changed()
            return [
                types.TextContent(type='text', text=wrap_in_results_tag('\n\n'.join(summaries)))
            ]

        elif name == 'get_full_texts':
            if not arguments or 'result_ids' not in arguments:
                raise ValueError('Missing result_ids argument')
            result_ids = arguments['result_ids']
            if not isinstance(result_ids, list):
                raise ValueError('result_ids must be a list')

            db_results = await research_service.get_full_texts(result_ids)
            formatted_results = [
                {
                    'id': str(res.id),
                    'title': str(res.title),
                    'author': str(res.author) if res.author else None,
                    'content': str(res.text),
                    'published_date': str(res.published_date) if res.published_date else None,
                }
                for res in db_results
            ]

            combined_text = format_full_texts_response(formatted_results)
            return [types.TextContent(type='text', text=combined_text)]

        else:
            raise ValueError(f'Unknown tool: {name}')
    except Exception as e:
        logger.error(f'Tool execution failed: {e!s}', exc_info=True)
        return [types.TextContent(type='text', text=f'Error: Tool execution failed - {e!s}')]


def clean_author(author: str | None) -> str | None:
    if author and len(author) > 60:
        return author[:60] + '...'
    return author


@server.set_logging_level()
async def set_logging_level(level: types.LoggingLevel) -> types.EmptyResult:
    logger.setLevel(level.upper())
    await server.request_context.session.send_log_message(
        level='info', data=f'Log level set to {level}', logger='research-mcp'
    )
    return types.EmptyResult()


async def main():
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
