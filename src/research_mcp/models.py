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


class ExaQuery(BaseModel):
    text: str
    category: Optional[ExaCategory] = None
    livecrawl: bool = False


class SearchResultItem(BaseModel):
    """Represents a single result from Exa search"""

    url: str
    id: str
    title: str
    score: float
    published_date: str | None = None
    author: str | None = None
    text: str
    highlights: Optional[list[str]] = None
    highlight_scores: Optional[list[float]] = None


class CleanedContent(BaseModel):
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


class QueryResults(BaseModel):
    """Groups together raw and processed results for a single query"""

    query_id: int
    query: ExaQuery
    raw_results: list[SearchResultItem]
    processed_results: list[CleanedContent]

    class Config:
        arbitrary_types_allowed = True  # Needed for ExaQuery which is still a dataclass


class ResearchResults(BaseModel):
    """Container for all results from a research request"""

    purpose: str = Field(..., description="Original research purpose")
    question: str = Field(..., description="Original research question")
    query_results: list[QueryResults]

    def all_raw_results(self) -> list[SearchResultItem]:
        """Flatten all raw results into a single list"""
        return [result for qr in self.query_results for result in qr.raw_results]

    def all_processed_results(self) -> list[CleanedContent]:
        """Flatten all processed results into a single list"""
        return [result for qr in self.query_results for result in qr.processed_results]

    class Config:
        arbitrary_types_allowed = True  # Needed for nested dataclass types
