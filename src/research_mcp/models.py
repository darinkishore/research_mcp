from dataclasses import dataclass
from typing import Literal, Optional

from pydantic import BaseModel, Field

# Define valid categories from README
ExaCategory = Literal[
    "company",
    "research paper",
    "news",
    "linkedin profile",
    "github",
    "tweet",
    "movie",
    "song",
    "personal site",
    "pdf",
]


@dataclass
class ExaQuery:
    text: str
    category: Optional[ExaCategory] = None
    livecrawl: bool = False


@dataclass
class ExaResult:
    """Represents a single result from Exa search"""

    url: str
    id: str
    title: str
    score: float
    published_date: str
    author: str
    text: str
    highlights: Optional[list[str]] = None
    highlight_scores: Optional[list[float]] = None


@dataclass
class CleanedContent:
    title: str
    author: str
    url: str
    summary: str
    relevance_summary: str
    content: str


class QueryPurpose(BaseModel):
    """Purpose and context for a set of queries"""

    purpose: str = Field(..., description="The research purpose for this query set")
    question: str = Field(..., description="Main query theme")
    queries: list[ExaQuery] = Field(..., description="output queries")


class QueryRequest(BaseModel):
    purpose: str = Field(
        ...,
        description="why do you want to know this thing? (ie: relevant context from your task. more details better.)",
    )
    question: str = Field(
        ...,
        description="what do you want to know, more specifically? use natural language, be descriptive.",
    )
