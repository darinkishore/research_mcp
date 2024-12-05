"""Business logic for research operations."""

from __future__ import annotations

import asyncio
import logging
import sys
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, cast


if TYPE_CHECKING:
    from mcp.server import Server

from exa_py import Exa
from exa_py.api import ResultWithText, SearchResponse
from sqlalchemy import select

from research_mcp.db import ExaQuery, QueryResult, Result, db
from research_mcp.models import (
    ExaQuery as ExaQueryModel,
    QueryRequest,
    QueryResults,
    ResearchResults,
    SearchResultItem,
    SummarizedContent,
)
from research_mcp.query_generation import generate_queries
from research_mcp.rate_limiter import RateLimiter
from research_mcp.summarize import summarize_search_items
from research_mcp.tracing import traced
from research_mcp.word_ids import WordIDGenerator


logger = logging.getLogger('research-mcp')


class ResearchService:
    """Service for handling research operations."""

    def __init__(
        self,
        exa_client: Exa,
        word_id_generator: WordIDGenerator,
        server: Server | None = None,
    ):
        self.exa = exa_client
        self.word_id_generator = word_id_generator
        self.exa_limiter = RateLimiter(max_calls=4, period=1)  # Slightly under 5/s to be safe
        self.server = server
        self.write_semaphore = asyncio.Semaphore(1)  # Limit concurrent writes to 1
        self.background_tasks: set[asyncio.Task] = set()  # Keep track of background tasks
        self.exa_semaphore = asyncio.Semaphore(5)

    @traced(type='function')
    async def perform_search(
        self, query_text: str, category: str | None = None, livecrawl: bool = False
    ) -> list[SearchResultItem]:
        """Perform search and return results."""
        assert query_text.strip(), 'Query text cannot be empty'
        search_args: dict[str, Any] = {
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
        async with self.exa_semaphore:
            await self.exa_limiter.acquire()

            try:
                results = cast(
                    SearchResponse[ResultWithText],
                    await asyncio.to_thread(
                        self.exa.search_and_contents, query_text, **search_args
                    ),
                )
            except Exception as e:
                logger.error(f'Error during Exa search: {e}')
                # Handle specific exceptions if needed
                raise

        # Convert ResultWithText to SearchResultItem
        return [
            SearchResultItem(
                url=r.url,
                id=str(r.id),  # Ensure id is string
                title=r.title or '',  # Handle potential None
                score=r.score,  # Ensure float
                published_date=r.published_date,
                author=r.author,
                text=r.text or '',  # Handle potential None
            )
            for r in results.results
        ]

    @traced(type='tool')
    async def process_search_query(self, search_query: ExaQueryModel) -> QueryResults:
        """Process a single search query and return the raw results."""
        # Store query in database asynchronously
        query_id = await self.store_exa_query(search_query)

        # Execute search
        exa_results = await self.perform_search(
            query_text=search_query.text,
            category=search_query.category,
            livecrawl=search_query.livecrawl,
        )

        # Convert to our models
        raw_results = [
            SearchResultItem(
                url=r.url,
                id=await self.word_id_generator.generate_result_id(),
                title=r.title,
                score=r.score,
                published_date=r.published_date,
                author=r.author,
                text=r.text,
            )
            for r in exa_results
        ]

        return QueryResults(
            query_id=int(query_id),
            query=search_query,
            raw_results=raw_results,
            summarized_results=[],  # Will be filled later
        )

    async def store_exa_query(self, search_query: ExaQueryModel) -> int:
        """Store ExaQuery in the database asynchronously."""
        async with self.write_semaphore, db() as session:
            db_query = ExaQuery(
                query_text=search_query.text,
                category=search_query.category,
                livecrawl=search_query.livecrawl,
            )
            session.add(db_query)
            await session.commit()
            return int(db_query.id)

    async def store_results(self, research_results: ResearchResults, purpose: str, question: str):
        """Store all results in the database."""
        async with self.write_semaphore, db() as session:
            result_ids: set[str] = set()
            for query_result in research_results.query_results:
                result_ids.update(r.id for r in query_result.raw_results)

            # Fetch existing results and links
            existing_results_stmt = select(Result).where(Result.id.in_(result_ids))
            existing_results = (await session.execute(existing_results_stmt)).scalars().all()
            existing_result_ids = {r.id for r in existing_results}

            # Create a mapping of result_id to summarized_content for easier lookup
            summarized_by_id = {}
            for query_result in research_results.query_results:
                for raw_result, summarized_result in zip(
                    query_result.raw_results, query_result.summarized_results, strict=False
                ):
                    if summarized_result and summarized_result.id == raw_result.id:
                        summarized_by_id[raw_result.id] = summarized_result

            # Prepare new results and links
            new_results = []
            new_links = []
            for query_result in research_results.query_results:
                for raw_result in query_result.raw_results:
                    # Type-safe way to get summarized_result
                    summarized_result = summarized_by_id.get(raw_result.id)
                    if not summarized_result:
                        continue

                    if raw_result.id not in existing_result_ids:
                        new_result = Result(
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

    async def list_resources(self, limit: int = 25) -> list[Result]:
        """List available result resources, focusing on most relevant and recent."""
        async with db() as session:
            stmt = (
                select(Result)
                .order_by(Result.relevance_score.desc(), Result.created_at.desc())
                .limit(limit)
            )
            results: list[Result] = (await session.execute(stmt)).scalars().all()
            return results

    async def get_resource(self, result_id: str) -> Result:
        """Get a specific result by ID."""
        async with db() as session:
            stmt = select(Result).where(Result.id == result_id)
            result: Result | None = (await session.execute(stmt)).scalar_one_or_none()

            if not result:
                raise ValueError(f'Result not found: {result_id}')
            return result

    async def get_full_texts(self, result_ids: list[str]) -> list[Result]:
        """Get full texts for a list of result IDs."""
        async with db() as session:
            stmt = select(Result).where(Result.id.in_(result_ids))
            results = (await session.execute(stmt)).scalars().all()
            return results

    @traced(type='tool')
    async def research(self, purpose: str, question: str) -> ResearchResults:
        """Perform research based on purpose and question."""
        try:
            # Generate optimized queries
            search_queries = await generate_queries(purpose=purpose, question=question)
            assert search_queries, 'No search queries were generated'

            # Initialize research results container with empty query_results
            research_results = ResearchResults(purpose=purpose, question=question, query_results=[])

            # Process search queries concurrently
            query_tasks = [self.process_search_query(query) for query in search_queries]
            query_results = await asyncio.gather(*query_tasks)
            research_results.query_results = query_results

            # Process content cleaning concurrently
            cleaning_tasks = []
            for query_result in research_results.query_results:
                query_request = QueryRequest(purpose=purpose, question=question)
                cleaning_task = summarize_search_items(
                    original_query=query_request,
                    content=query_result.raw_results,
                )
                cleaning_tasks.append(cleaning_task)

            # Wait for all content cleaning
            cleaned_results: list[list[SummarizedContent]] = await asyncio.gather(*cleaning_tasks)

            # Update results with cleaned content
            for query_result, cleaned_result in zip(
                research_results.query_results, cleaned_results, strict=True
            ):
                query_result.summarized_results = cleaned_result

            # Schedule database writes as a background task
            write_task = asyncio.create_task(
                self.store_results(research_results, purpose, question)
            )
            self.background_tasks.add(write_task)
            write_task.add_done_callback(self.background_tasks.discard)

            return research_results  # Return to client immediately
        except Exception as e:
            print(f'Research error: {e}', file=sys.stderr)
            raise
