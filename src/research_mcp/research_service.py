"""Business logic for research operations."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from exa_py import Exa
from sqlalchemy import select

from research_mcp.db import ExaQuery, QueryResult, Result, db
from research_mcp.models import (
    ExaQuery as ExaQueryModel,
    QueryRequest,
    QueryResults,
    ResearchResults,
    SearchResultItem,
)
from research_mcp.query_generation import generate_queries
from research_mcp.rate_limiter import RateLimiter
from research_mcp.summarize import summarize_search_items
from research_mcp.word_ids import WordIDGenerator


class ResearchService:
    """Service for handling research operations."""

    def __init__(self, exa_client: Exa, word_id_generator: WordIDGenerator):
        self.exa = exa_client
        self.word_id_generator = word_id_generator
        self.exa_limiter = RateLimiter(rate=3)  # Slightly under 5/s to be safe

    async def perform_search(
        self, query_text: str, category: str | None = None, livecrawl: bool = False
    ) -> list[SearchResultItem]:
        """Perform search and return results."""
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
        await self.exa_limiter.acquire()

        # If Exa client supports async, use it directly; else, use to_thread
        if hasattr(self.exa.search_and_contents, '__await__'):
            results = await self.exa.search_and_contents(query_text, **search_args)
        else:
            results = await asyncio.to_thread(
                self.exa.search_and_contents, query_text, **search_args
            )
        return results.results

    async def process_search_query(self, search_query: QueryRequest) -> QueryResults:
        """Process a single search query and return the raw results."""
        # Store query in database
        async with db() as session:
            exa_query = ExaQueryModel(text=search_query.question)
            db_query = ExaQuery(
                query_text=exa_query.text,
                category=None,  # We'll add category support later
                livecrawl=False,  # We'll add livecrawl support later
            )
            session.add(db_query)
            await session.commit()
            query_id = db_query.id

        # Execute search
        exa_results = await self.perform_search(
            query_text=search_query.question,
            category=None,  # We'll add category support later
            livecrawl=False,  # We'll add livecrawl support later
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
            query_id=query_id,
            query=exa_query,
            raw_results=raw_results,
            summarized_results=[],  # Will be filled later
        )

    async def store_results(self, research_results: ResearchResults, purpose: str, question: str):
        """Store all results in the database."""
        async with db() as session:
            result_ids = set()
            for query_result in research_results.query_results:
                result_ids.update(r.id for r in query_result.raw_results)

            # Fetch existing results and links
            existing_results_stmt = select(Result).where(Result.id.in_(result_ids))
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
            result: Result = (await session.execute(stmt)).scalars().first()
            if not result:
                raise ValueError(f'Result not found: {result_id}')
            return result

    async def get_full_texts(self, result_ids: list[str]) -> list[Result]:
        """Get full texts for a list of result IDs."""
        async with db() as session:
            stmt = select(Result).where(Result.id.in_(result_ids))
            results = (await session.execute(stmt)).scalars().all()
            return results

    async def research(self, purpose: str, question: str) -> ResearchResults:
        """Perform comprehensive research on a topic."""
        # Generate optimized queries
        search_queries = await generate_queries(purpose=purpose, question=question)
        assert search_queries, 'No search queries were generated'

        # Initialize research results container
        research_results = ResearchResults(purpose=purpose, question=question, query_results=[])

        # Process each query sequentially to avoid database concurrency issues
        for query in search_queries:
            query_result = await self.process_search_query(query)
            research_results.query_results.append(query_result)

        # Process content cleaning concurrently
        cleaning_tasks = []
        for query_result in research_results.query_results:
            cleaning_task = summarize_search_items(
                original_query=QueryRequest(purpose=purpose, question=question),
                content=query_result.raw_results,
            )
            cleaning_tasks.append(cleaning_task)

        # Wait for all content cleaning
        cleaned_results = await asyncio.gather(*cleaning_tasks)

        # Update results with cleaned content
        for query_result, cleaned_result in zip(
            research_results.query_results, cleaned_results, strict=True
        ):
            query_result.summarized_results = cleaned_result

        # Store results
        await self.store_results(research_results, purpose, question)

        return research_results
