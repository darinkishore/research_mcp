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


def format_date(date_str: str | None) -> str | None:
    """Format date string to yyyy-mm-dd format."""
    if not date_str:
        return None
    try:
        # Parse ISO format date
        date = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
        return date.strftime('%Y-%m-%d')
    except (ValueError, AttributeError):
        return None


def format_result_summary(
    result_id: str,
    title: str,
    author: str | None,
    relevance_summary: str,
    summary: str,
    published_date: str | None = None,
) -> str:
    """Format an individual result summary."""
    formatted_date = format_date(published_date)
    date_element = f'\n<date>{formatted_date}</date>' if formatted_date else ''
    author_element = f'\n<author>{author}</author>' if author else ''
    return f"""\
<result id="{result_id}">

<title>{title}</title>
{date_element}
{author_element}

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
        # Truncate author if longer than 120 chars
        author = result['author']
        if author:
            if len(author) > 120:
                author = author[:120] + '...'
            author_element = f'<author>{author}</author>\n'
        else:
            author_element = ''

        formatted_date = format_date(result['published_date'])
        date_element = f'<date>{formatted_date}</date>\n' if formatted_date else ''

        text = f"""<text id="{result['id']}">
<title>{result['title']}</title>
{author_element}{date_element}
<content>
{result['content']}
</content>
</text>"""
        formatted.append(text.strip())

    return '\n\n'.join(formatted)
