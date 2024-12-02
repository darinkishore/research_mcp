from __future__ import annotations

import asyncio
from typing import Any, Literal

import dspy  # type: ignore
from cleantext import clean  # type: ignore
from dspy import InputField, OutputField, Signature
from pydantic import BaseModel, Field


# Models
ExaCategory = Literal[
    'company',
    'research paper',
    'news',
    'linkedin profile',
    'github',
    'tweet',
    'movie',
    'song',
    'personal site',
    'pdf',
]


class ExaQuery(BaseModel):
    text: str
    category: ExaCategory | None = None
    livecrawl: bool = False


class SearchResultItem(BaseModel):
    url: str
    id: str
    title: str
    score: float
    published_date: str | None = None
    author: str | None = None
    text: str

    def model_post_init(self, __context) -> None:
        self.text = clean(self.text, lower=False)


class SummarizedContent(BaseModel):
    id: str
    relevance_summary: str
    dense_summary: str


class QueryRequest(BaseModel):
    purpose: str | None = Field(None, description='Research context')
    question: str = Field(..., description='What you want to know')


class QueryPurpose(BaseModel):
    """Purpose and context for a set of queries"""

    purpose: str = Field(..., description='The research purpose for this query set')
    question: str = Field(..., description='Main query theme')
    queries: list[ExaQuery] = Field(..., description='output queries')


# QUERY GENERATION BLOCK ###

# Training data
TRAINING_DATA = [
    # Scholarly/Theoretical
    QueryPurpose(
        purpose='To build a theoretical framework for analyzing wellness industry trends.',
        question='Academic analysis of commodification in the wellness industry',
        queries=[
            ExaQuery(
                text='Here is an academic paper analyzing cultural appropriation in modern wellness industries:',
                category='research paper',
            ),
            ExaQuery(
                text='Here is a scholarly analysis of how luxury brands commodify spiritual practices:',
                category='research paper',
            ),
            ExaQuery(
                text='Here is research on class dynamics in contemporary wellness culture:',
                category='research paper',
            ),
            ExaQuery(
                text="Here is a scholarly analysis of the wellness industry's impact on mental health:",
                category='research paper',
            ),
        ],
    ),
    QueryPurpose(
        purpose="To gather information about Lululemon's history and yoga's commodification in the West.",
        question='Lululemon history and yoga transformation in the West',
        queries=[
            ExaQuery(
                text="Here is information about Lululemon's founding and early history:",
            ),
            ExaQuery(
                text="Here is information about Lululemon's founding and early history:",
                category='news',
            ),
            ExaQuery(
                text="Here is data about Lululemon's growth and current market valuation:",
                livecrawl=True,
            ),
            ExaQuery(
                text="Here is data about Lululemon's growth and current market valuation:",
                category='news',
            ),
            ExaQuery(
                text="Here is an academic overview of yoga's transformation in the West:",
                category='research paper',
            ),
        ],
    ),
    QueryPurpose(
        purpose="To find evidence of cultural appropriation in Lululemon's practices for a critique.",
        question="Critiques of Lululemon's appropriation of yoga",
        queries=[
            ExaQuery(
                text='Here are examples of how Lululemon uses Sanskrit and spiritual language in their marketing:',
            ),
            ExaQuery(
                text="Here are critiques from Indian yoga practitioners about Lululemon's appropriation of yoga:",
            ),
            ExaQuery(
                text="Here are critiques from Indian yoga practitioners about Lululemon's appropriation of yoga:",
                category='research paper',
            ),
            ExaQuery(
                text="Here is criticism from Indian yoga practitioners about Lululemon's appropriation of yoga:",
                category='news',
            ),
        ],
    ),
    QueryPurpose(
        purpose="To analyze class dynamics in Lululemon's marketing and store placement strategies.",
        question="Class-based critique of Lululemon's marketing strategy",
        queries=[
            ExaQuery(
                text='Here is analysis of where Lululemon places their stores and why:',
            ),
            ExaQuery(
                text="Here is data about Lululemon's target customer demographics:",
                category='news',
            ),
            ExaQuery(
                text="Here is data about Lululemon's target customer demographics:",
                category='research paper',
            ),
            ExaQuery(
                text="Here is information about Lululemon's ambassador program and marketing strategy:",
                category='news',
            ),
            ExaQuery(
                text="Here is information about Lululemon's ambassador program and marketing strategy:",
                category='research paper',
            ),
        ],
    ),
    QueryPurpose(
        purpose="To understand Lululemon's role in creating the athleisure market trend.",
        question='History of athleisure fashion',
        queries=[
            ExaQuery(
                text='Here is how Lululemon pioneered the athleisure category in fashion:',
            ),
            ExaQuery(
                text='Here is research about how Lululemon pioneered the athleisure category in fashion:',
                category='research paper',
            ),
        ],
    ),
]


# Create formatted examples
def format_training_examples():
    examples = []
    examples.append('<examples>')
    for purpose in TRAINING_DATA:
        examples.extend((
            '<input>',
            f'**Purpose:** {purpose.purpose}',
            f'**Question:** {purpose.question}',
            '</input>',
            '<output>',
        ))
        for query in purpose.queries:
            examples.extend((
                '<query>',
                f'   Query: "{query.text}"',
                f'   Category: {query.category or "null"}',
                f'   LiveCrawl: {query.livecrawl}',
                '</query>',
            ))
        examples.append('</output>')
    examples.append('</examples>\n')
    return '\n'.join(examples)


VALID_CATEGORIES = [
    'company',
    'research paper',
    'news',
    'linkedin profile',
    'github',
    'tweet',
    'movie',
    'song',
    'personal site',
    'pdf',
]

QUERY_DESCRIPTION = f"""\
A list of optimized Exa queries following best practices:
- Use natural language statements, not questions
- Add descriptive modifiers (detailed, comprehensive, etc.)
- Takes advantage of embedding similarity to find relevant results
- End with a colon
- Specify content type when relevant
- Include specific details
- Use appropriate categories from the allowed list
- Enable livecrawl for recent content needs

Examples from Training Data:
{format_training_examples()}

Remember to:
- If specifying a category, ensure you also have a non-category query for diverse results.
- Use livecrawl **only** when you absolutely need results from the last month.
- If creating either category or livecrawl queries, also create a non-category/non-livecrawl query to fill in gaps.
- Keep queries clear and specific
- End each query with a colon
"""


class PurposeDrivenQuery(Signature):
    """Generate a list of optimized Exa queries based on a purpose and question."""

    purpose: str = InputField(
        description='why do you want to know this thing? (ie: relevant context from your task. more details better.)'
    )
    question: str = InputField(
        description='what do you want to know, more specifically? use natural language, be descriptive.'
    )
    queries: list[ExaQuery] = OutputField(description=QUERY_DESCRIPTION)


# END QUERY GENERATION BLOCK ###


# CONTENT CLEANING BLOCK ###
class ExtractContent(Signature):
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

    original_query: QueryRequest = InputField(
        desc='The query that generated the search results, providing context for determining relevance.'
    )
    content: SearchResultItem = InputField(desc='the raw search result')
    cleaned_response: SummarizedContent | None = OutputField(desc='the cleaned search result')


# END CONTENT CLEANING BLOCK ###

# Remove LM initialization, just keep the generator singleton
_query_generator: Any | None = None
_content_cleaner: Any | None = None


def get_query_generator():
    global _query_generator
    if _query_generator is None:
        _query_generator = dspy.ChainOfThought(PurposeDrivenQuery)
        _query_generator = dspy.asyncify(_query_generator)
    return _query_generator


def get_content_cleaner():
    global _content_cleaner
    if _content_cleaner is None:
        _content_cleaner = dspy.ChainOfThought(ExtractContent)
        _content_cleaner = dspy.asyncify(_content_cleaner)
    return _content_cleaner


async def generate_queries(purpose: str, question: str) -> list[ExaQuery]:
    generator = get_query_generator()
    result = await generator(purpose=purpose, question=question)
    return result.queries


async def summarize_search_items(
    original_query: QueryRequest, content: list[SearchResultItem]
) -> list[SummarizedContent]:
    cleaner = get_content_cleaner()
    results = await asyncio.gather(
        *(cleaner(original_query=original_query, content=item) for item in content)
    )
    return [r.cleaned_response for r in results if r.cleaned_response is not None]


# Example usage
async def main():
    # Note: this does not have the short, semantic ids

    # Initialize DSPy with your preferred LLM
    dspy.settings.configure(lm=dspy.OpenAI('gpt-4'))

    # Example research query
    query_request = QueryRequest(
        purpose='To understand the impact of AI on software development',
        question='How are AI coding assistants changing developer productivity?',
    )

    # Generate optimized search queries
    queries = await generate_queries(query_request.purpose, query_request.question)
    print('\nGenerated Queries:')
    for q in queries:
        print(f'- {q.text} (Category: {q.category}, LiveCrawl: {q.livecrawl})')

    # Example search results (in practice, these would come from your search service)
    mock_results = [
        SearchResultItem(
            url='https://example.com/1',
            id='1',
            title='AI Coding Impact Study',
            score=0.95,
            text='Study shows 40% productivity increase with AI coding assistants...',
        ),
        SearchResultItem(
            url='https://example.com/2',
            id='2',
            title='Developer Survey 2023',
            score=0.85,
            text='Survey of 1000 developers reveals changing workflows with AI...',
        ),
    ]

    # Summarize search results
    summaries = await summarize_search_items(query_request, mock_results)
    print('\nSummarized Results:')
    for summary in summaries:
        print(f'\nID: {summary.id}')
        print(f'Relevance: {summary.relevance_summary}')
        print(f'Summary: {summary.dense_summary}')


# Note that just using these wouldn't be great for the tool design, there's
# some XML formatting functions n whatnot, basic MD formatting works for now


if __name__ == '__main__':
    asyncio.run(main())
