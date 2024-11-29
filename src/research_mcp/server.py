"""FastAPI server for research MCP."""

from __future__ import annotations

import os
from typing import Annotated

from exa_py import Exa
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from research_mcp.models import (
    QueryRequest,
    ResearchResults,
)
from research_mcp.research_service import ResearchService
from research_mcp.schemas import format_resource_content
from research_mcp.word_ids import WordIDGenerator


server = FastAPI()

# Add CORS middleware
server.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],
    allow_credentials=True,
    allow_methods=['*'],
    allow_headers=['*'],
)

# Initialize services
exa_client = Exa(api_key=os.environ['EXA_API_KEY'])
word_id_generator = WordIDGenerator()
research_service = ResearchService(exa_client=exa_client, word_id_generator=word_id_generator)


def get_research_service() -> ResearchService:
    """Get research service instance."""
    return research_service


@server.post('/research')
async def research(
    query: QueryRequest,
    service: Annotated[ResearchService, Depends(get_research_service)],
) -> ResearchResults:
    """Research a topic."""
    try:
        return await service.research(purpose=query.purpose, question=query.question)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@server.get('/resources')
async def list_resources(
    service: Annotated[ResearchService, Depends(get_research_service)],
    limit: int = 25,
) -> list[dict]:
    """List available resources."""
    try:
        results = await service.list_resources(limit=limit)
        return [format_resource_content(r) for r in results]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@server.get('/resources/{result_id}')
async def get_resource(
    result_id: str,
    service: Annotated[ResearchService, Depends(get_research_service)],
) -> dict:
    """Get a specific resource."""
    try:
        result = await service.get_resource(result_id=result_id)
        return format_resource_content(result)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@server.post('/get_full_texts')
async def get_full_texts(
    result_ids: list[str],
    service: Annotated[ResearchService, Depends(get_research_service)],
) -> list[dict]:
    """Get full texts for a list of result IDs."""
    try:
        results = await service.get_full_texts(result_ids=result_ids)
        return [format_resource_content(r) for r in results]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
