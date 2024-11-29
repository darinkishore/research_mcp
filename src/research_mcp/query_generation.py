from __future__ import annotations

import dspy
from research_mcp.tracing import traced
from dspy import InputField, OutputField, Signature

from research_mcp.dspy_init import get_dspy_lm
from research_mcp.models import ExaQuery, QueryPurpose

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

# Remove LM initialization, just keep the generator singleton
_query_generator = None


def get_query_generator():
    global _query_generator
    if _query_generator is None:
        get_dspy_lm()  # Ensure DSPy is initialized
        _query_generator = dspy.ChainOfThought(PurposeDrivenQuery)
        _query_generator = dspy.asyncify(_query_generator)
    return _query_generator


class PurposeDrivenQuery(Signature):
    """Generate a list of optimized Exa queries based on a purpose and question."""

    purpose: str = InputField(
        description='why do you want to know this thing? (ie: relevant context from your task. more details better.)'
    )
    question: str = InputField(
        description='what do you want to know, more specifically? use natural language, be descriptive.'
    )

    queries: list[ExaQuery] = OutputField(description=QUERY_DESCRIPTION)


# Update the generate_queries function
@traced(type='llm')
async def generate_queries(purpose: str, question: str) -> list[ExaQuery]:
    generator = get_query_generator()
    result = await generator(
        purpose=purpose,
        question=question,
    )
    return result.queries


# TODO: use as docs for tool
