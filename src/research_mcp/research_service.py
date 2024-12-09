from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from returns.future import future_safe


if TYPE_CHECKING:
    from mcp.server import Server

from exa_py import Exa
from exa_py.api import ResultWithText, SearchResponse
from sqlalchemy import select

from research_mcp.db import ExaQuery as DbExaQuery, QueryResult, Result as DbResult, db
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
        self.exa_limiter = RateLimiter(max_calls=4, period=1)
        self.server = server
        self.write_semaphore = asyncio.Semaphore(1)
        self.background_tasks: set[asyncio.Task] = set()
        self.exa_semaphore = asyncio.Semaphore(5)

    async def perform_search(
        self, query_text: str, category: str | None = None, livecrawl: bool = False
    ) -> list[SearchResultItem]:
        """Perform search and return a list of SearchResultItem or raise on fail."""
        if not query_text.strip():
            raise ValueError('Query text cannot be empty')

        search_args: dict[str, Any] = {
            'num_results': 10,
            'type': 'neural',
            'text': True,
            'use_autoprompt': False,
            'category': category,
            'livecrawl': 'always' if livecrawl else None,
        }
        search_args = {k: v for k, v in search_args.items() if v is not None}

        async with self.exa_semaphore:
            await self.exa_limiter.acquire()
            # This can fail (raise exception)
            search_response: SearchResponse[ResultWithText] = await asyncio.to_thread(
                lambda: self.exa.search_and_contents(query_text, **search_args)  # type: ignore
            )

            search_result_items = [
                SearchResultItem(
                    url=str(r.url) if r.url else '',
                    id=str(r.id),
                    title=str(r.title) if r.title else '',
                    score=float(r.score) if r.score else 0.0,
                    published_date=r.published_date,
                    author=str(r.author) if r.author else '',
                    text=str(r.text) if r.text else '',
                )
                for r in search_response.results
            ]
            return search_result_items

    async def store_exa_query(self, search_query: ExaQueryModel) -> int:
        """Store ExaQuery in DB and return its ID or raise."""
        async with self.write_semaphore, db() as session:
            db_query = DbExaQuery(
                query_text=search_query.text,
                category=search_query.category,
                livecrawl=search_query.livecrawl,
            )
            session.add(db_query)
            await session.commit()
            return int(db_query.id)

    async def process_search_query(self, search_query: ExaQueryModel) -> QueryResults:
        """Process a single search query. Returns QueryResults or raise."""
        query_id = await self.store_exa_query(search_query)
        raw_results = await self.perform_search(
            query_text=search_query.text,
            category=search_query.category,
            livecrawl=search_query.livecrawl,
        )
        return QueryResults(
            query_id=query_id,
            query=search_query,
            raw_results=raw_results,
            summarized_results=[],
        )

    async def store_results(
        self, research_results: ResearchResults, purpose: str, question: str
    ) -> None:
        """Store all results in the DB or raise."""
        async with self.write_semaphore, db() as session:
            result_ids: set[str] = {
                r.id for qr in research_results.query_results for r in qr.raw_results
            }

            existing_results_stmt = select(DbResult).where(DbResult.id.in_(result_ids))
            existing_results = (await session.execute(existing_results_stmt)).scalars().all()
            existing_map = {r.id: r for r in existing_results}

            summarized_by_id = {}
            for query_result in research_results.query_results:
                for raw_result, summarized_result in zip(
                    query_result.raw_results, query_result.summarized_results, strict=False
                ):
                    if summarized_result and summarized_result.id == raw_result.id:
                        summarized_by_id[raw_result.id] = summarized_result

            new_results = []
            new_links = []
            for query_result in research_results.query_results:
                for raw_result in query_result.raw_results:
                    current_summary: SummarizedContent | None = summarized_by_id.get(raw_result.id)
                    if not current_summary:
                        continue
                    if raw_result.id not in existing_map:
                        new_result = DbResult(
                            id=self.word_id_generator,
                            title=raw_result.title or None,
                            author=raw_result.author or None,
                            url=raw_result.url or None,
                            dense_summary=current_summary.dense_summary,
                            relevance_summary=current_summary.relevance_summary,
                            text=raw_result.text,
                            relevance_score=raw_result.score,
                            query_purpose=purpose,
                            query_question=question,
                            published_date=raw_result.published_date,
                        )
                        new_results.append(new_result)
                    else:
                        existing_map[raw_result.id].updated_at = datetime.now(UTC)

                    new_links.append(
                        QueryResult(query_id=query_result.query_id, result_id=raw_result.id)
                    )

            if new_results:
                session.add_all(new_results)
            if new_links:
                session.add_all(new_links)
            await session.commit()

    async def list_resources(self, limit: int = 25) -> list[DbResult]:
        """Return a list of DbResult or raise."""
        async with db() as session:
            stmt = (
                select(DbResult)
                .order_by(DbResult.relevance_score.desc(), DbResult.created_at.desc())
                .limit(limit)
            )
            results: list[DbResult] = (await session.execute(stmt)).scalars().all()
            return results

    async def get_resource(self, result_id: str) -> DbResult:
        """Return a single DbResult by id or raise ValueError if not found."""
        async with db() as session:
            stmt = select(DbResult).where(DbResult.id == result_id)
            result: DbResult | None = (await session.execute(stmt)).scalar_one_or_none()
            if not result:
                raise ValueError(f'Result not found: {result_id}')
            return result

    async def get_full_texts(self, result_ids: list[str]) -> list[DbResult]:
        """Return multiple DbResults by their ids or raise if fail."""
        async with db() as session:
            stmt = select(DbResult).where(DbResult.id.in_(result_ids))
            results: list[DbResult] = (await session.execute(stmt)).scalars().all()
            return results

    async def assign_word_id(self, result: SearchResultItem) -> None:
        """Assign a new word ID to a search result."""
        result.id = await self.word_id_generator.generate_result_id()

    @traced(type='tool')
    @future_safe
    async def research(self, purpose: str, question: str) -> ResearchResults:
        # generate_queries might raise ValueError if no queries generated
        search_queries = await generate_queries(purpose=purpose, question=question)
        if not search_queries:
            raise ValueError('No search queries were generated')

        # Gather QueryResults from multiple queries
        query_results: list[QueryResults] = await asyncio.gather(
            *(self.process_search_query(q) for q in search_queries)
        )

        # Assign word IDs to all results concurrently
        await asyncio.gather(
            *(self.assign_word_id(result) for qr in query_results for result in qr.raw_results)
        )

        # Summarize each query_result's raw_results (now with our IDs)
        all_summaries_list: list[list[SummarizedContent]] = await asyncio.gather(
            *(
                summarize_search_items(
                    QueryRequest(purpose=purpose, question=question), qr.raw_results
                )
                for qr in query_results
            )
        )

        # Attach summaries
        for qr, summs in zip(query_results, all_summaries_list, strict=True):
            qr.summarized_results = summs

        research_results = ResearchResults(
            purpose=purpose, question=question, query_results=query_results
        )

        # Store results in the background
        store_coro = self.store_results(research_results, purpose, question)
        store_task: asyncio.Task[None] = asyncio.create_task(store_coro)
        self.background_tasks.add(store_task)
        store_task.add_done_callback(self.background_tasks.discard)

        return research_results
