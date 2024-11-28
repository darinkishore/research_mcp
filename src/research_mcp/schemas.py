from typing import Any


def get_search_tool_schema() -> dict[str, Any]:
    """Return the JSON schema for the search tool."""
    return {
        'type': 'object',
        'properties': {
            'purpose': {
                'type': 'string',
                'description': get_purpose_description(),
            },
            'question': {
                'type': 'string',
                'description': get_question_description(),
            },
        },
        'required': ['purpose', 'question'],
    }


def get_purpose_description() -> str:
    """Return the description for the purpose field."""
    return """Why you need this information - provide detailed context to generate better queries.
    
    Include:
    - Your broader research context or goal
    - How you plan to use this information
    - Any specific perspective or lens you're analyzing from
    - Level of technical depth needed
    - Timeline relevance (historical, current, future trends)
    
    Example: "I'm writing an academic paper analyzing how luxury brands commodify spiritual practices, 
    focusing on the intersection of capitalism and cultural appropriation in the wellness industry"
    """


def get_question_description() -> str:
    """Return the description for the question field."""
    return """Your specific research question or topic - be precise and detailed.
    
    Include:
    - Key concepts or terms you're investigating
    - Specific aspects you want to focus on
    - Any relevant timeframes
    - Types of sources that would be most valuable
    - Any specific examples or cases you're interested in
    
    Example: "How do modern wellness companies incorporate and market traditional spiritual practices? 
    Looking for both academic analysis and concrete examples from major brands"
    """


def format_resource_content(
    result_id: str,
    title: str,
    author: str | None,
    content: str,
) -> str:
    """Format the content for a resource."""
    return f"""# [{result_id}]
## Title: {title}

**Author:** {author}

## Full Content

<content>
{content}
</content>
"""


def format_query_results_summary(query_text: str, category: str | None, livecrawl: bool) -> str:
    """Format the header for query results."""
    return f"""
# Results for Query: {query_text}
{'Category: ' + category if category else ''}
{'Crawled recently' if livecrawl else ''}
""".strip()


def format_result_summary(
    result_id: str, title: str, author: str, relevance_summary: str, summary: str
) -> str:
    """Format an individual result summary."""
    return f"""\
## [{result_id}] {title}
**Author:** {author}

### Relevance to Your Query
{relevance_summary}

### Summary
{summary}
"""
