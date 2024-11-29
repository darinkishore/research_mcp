import asyncio
from typing import Union

import dspy
from research_mcp.tracing import traced

from research_mcp.dspy_init import get_dspy_lm
from research_mcp.models import QueryRequest, SearchResultItem, SummarizedContent


class ExtractContent(dspy.Signature):
    """
    Extract information from search results to get the best results.
    Only keep search results that are relevant to the original query.

    For each result, return:
    1. The ID of the result
    2. A relevance summary: why it's relevant to the original query (<10 words, be straightforward and concise, say something distinct from the title)
    3. A hyper-dense summary of the content.
        - Use the original content, but tailor it for our query.
        - Be as dense as possible. Don't miss anything not contained in the query.
        - Ideally, you'd return basically the exact content but with words/phrases omitted to focus on answering the reason behind the query and the question itself.
        - If the content is <1000 words or < 5 paragraphs, return it in full.
    If the document is not relevant, return None.
    """

    original_query: QueryRequest = dspy.InputField(
        desc='The query that generated the search results, providing context for determining relevance.'
    )
    content: SearchResultItem = dspy.InputField(desc='the raw search result')

    cleaned_response: Union[SummarizedContent, None] = dspy.OutputField(  # noqa: UP007
        desc='the cleaned search result'
    )


# Instead of initializing for each call, make this a module-level singleton
_lm = None
_content_cleaner = None


def get_content_cleaner():
    global _lm, _content_cleaner
    if _content_cleaner is None:
        get_dspy_lm()  # Ensure DSPy is initialized
        _content_cleaner = dspy.ChainOfThought(ExtractContent)
        _content_cleaner = dspy.asyncify(_content_cleaner)
    return _content_cleaner


@traced(type='llm')
async def summarize_search_items(
    original_query: QueryRequest, content: list[SearchResultItem]
) -> list[SummarizedContent]:
    cleaner = get_content_cleaner()
    # Process all items concurrently using asyncio.gather
    results = await asyncio.gather(
        *(cleaner(original_query=original_query, content=item) for item in content)
    )

    # Filter out None responses and flatten results list
    return [result.cleaned_response for result in results if result.cleaned_response is not None]
