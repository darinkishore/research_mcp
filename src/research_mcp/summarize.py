import dspy

from research_mcp.models import CleanedContent, QueryRequest, SearchResultItem


class CleanContent(dspy.Signature):
    """
    Clean and format content based on the original query and search results.
    Analyze the provided search results based on the original query and extract only the most relevant articles or papers.
    For each relevant result, return:
    1. Title
    2. Author(s)
    3. URL
    4. A hyper-brief overall summary of the content. 15 words or less.
    5. A brief summary of why it's relevant to the original query.
    6. Full text (cleaned of metadata and formatting). If the text is more than 5 paragraphs, provide a super-dense version
       that conveys as much of the original content as possible in a condensed form.

    Format the response in markdown. Be thorough, and consider the context of the query.
    """

    original_query: QueryRequest = dspy.InputField(
        desc='The query that generated the search results, providing context for determining relevance.'
    )
    content: list[SearchResultItem] = dspy.InputField(desc='the raw search results')

    cleaned_response: list[CleanedContent] = dspy.OutputField(
        desc='A markdown-formatted response summarizing the most relevant articles or papers. '
        'For each result, include title, author(s), URL, relevance summary, and a super-dense version of the main text.'
    )


def initalize_content_cleaner(async_max_workers: int = 4):
    lm = dspy.LM('openai/gpt-4o-2024-11-20')
    dspy.settings.configure(lm=lm, async_max_workers=async_max_workers)
    content_cleaner = dspy.ChainOfThought(CleanContent)
    content_cleaner = dspy.asyncify(content_cleaner)
    return content_cleaner


content_cleaner = initalize_content_cleaner()


async def clean_content(
    original_query: QueryRequest, content: list[SearchResultItem]
) -> list[CleanedContent]:
    result = await content_cleaner(original_query=original_query, content=content)

    return result.cleaned_response
