from datetime import datetime
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
    published_date: str | None = None,
) -> str:
    """Format the content for a resource."""
    date_element = f'\n<published_date>{published_date}</published_date>' if published_date else ''
    return f"""<resource id="{result_id}">
<title>{title}</title>

<author>{author}</author>{date_element}

<content>
{content}
</content>
</resource>"""


def wrap_in_results_tag(content: str) -> str:
    """Wrap the content in the results format."""
    return f"""<results>
{content}
</results>"""


def format_query_results_summary(query_text: str, category: str | None, livecrawl: bool) -> str:
    """Format the header for query results."""
    return f"""
<query>
<text>{query_text}</text>
{f'<category>{category}</category>' if category else ''}
{'<crawl-status>recent</crawl-status>' if livecrawl else ''}
</query>
""".strip()


def format_result_summary(
    result_id: str,
    title: str,
    author: str,
    relevance_summary: str,
    summary: str,
    published_date: datetime | None = None,
) -> str:
    """Format an individual result summary."""
    date_element = f'\n<date>{published_date.strftime("%Y-%m-%d")}</date>' if published_date else ''
    return f"""\
<result id="{result_id}">

<title>{title}</title>
{date_element}
<author>{author}</author>

<relevance>
{relevance_summary}
</relevance>

<summary>
{summary}
</summary>
</result>"""


def format_full_texts_response(results: list[dict]) -> str:
    """Format multiple full text results with clear separation."""
    formatted = []
    for result in results:
        text = f"""<text id="{result['id']}">
<title>{result['title']}</title>
<author>{result['author'] or 'Unknown'}</author>
<date>{result['published_date'] or 'Unknown'}</date>

<content>
{result['content']}
</content>
</text>"""
        formatted.append(text.strip())

    return '\n\n'.join(formatted)
