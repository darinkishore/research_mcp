import dspy

from research_mcp.dspy_init import get_dspy_lm
from research_mcp.models import QueryRequest, SearchResultItem, SummarizedContent


class CleanContent(dspy.Signature):
    """
    Extract information from search results to get the best results.
    Only keep search results that are relevant to the original query.

    For each result, return:
    1. The ID of the result
    2. A relevance summary: why it's relevant to the original query
    3. A hyper-dense summary of the content.
        - Use the original content, but tailor it for our query.
        - Be as dense as possible. Don't miss anything not contained in the query.
        - If the content is <1000 words or < 5 paragraphs, return it in full.
    """

    original_query: QueryRequest = dspy.InputField(
        desc='The query that generated the search results, providing context for determining relevance.'
    )
    content: list[SearchResultItem] = dspy.InputField(desc='the raw search results')

    cleaned_response: list[SummarizedContent] = dspy.OutputField(
        desc='list of (id, dense_summary, relevance_summary) for only results that are relevant to the original query'
    )


# Instead of initializing for each call, make this a module-level singleton
_lm = None
_content_cleaner = None


def get_content_cleaner():
    global _lm, _content_cleaner
    if _content_cleaner is None:
        get_dspy_lm()  # Ensure DSPy is initialized
        _content_cleaner = dspy.ChainOfThought(CleanContent)
        _content_cleaner = dspy.asyncify(_content_cleaner)
    return _content_cleaner


async def clean_content(
    original_query: QueryRequest, content: list[SearchResultItem]
) -> list[SummarizedContent]:
    cleaner = get_content_cleaner()
    result = await cleaner(original_query=original_query, content=content)
    return result.cleaned_response
