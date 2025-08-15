"""Exa MCP Server - Complete implementation with neural search tools."""

from typing import Optional, Literal, Annotated, Any
from datetime import date, datetime
from fastmcp import FastMCP
from exa_py import AsyncExa
import os
import json

def setup_search_tool(mcp: FastMCP):
    """Set up the Exa search tool on the given FastMCP instance."""
    
    # Initialize Exa client lazily
    exa_client = None
    
    def get_exa_client():
        nonlocal exa_client
        if exa_client is None:
            api_key = os.getenv("EXA_API_KEY")
            if not api_key:
                raise ValueError("EXA_API_KEY environment variable is required. Set it with: export EXA_API_KEY=your_key")
            exa_client = AsyncExa(api_key=api_key)
        return exa_client
    
    @mcp.tool
    async def exa_search(
        query: Annotated[str, "Search query following the patterns above. End with colon for best results."],
        search_type: Annotated[Literal["auto", "neural", "keyword"], "auto, neural, or keyword search type"] = "auto",
        num_results: Annotated[int, "Number of results to return (default 25)"] = 25,
        category: Optional[Literal[
            "company", 
            "research paper", 
            "news", 
            "linkedin profile", 
            "github", 
            "tweet", 
            "movie", 
            "song", 
            "personal site", 
            "pdf"
        ]] = None,
        include_domains: Annotated[Optional[list[str]], "ONLY return results from these domains. Example: ['arxiv.org', 'nature.com']"] = None,
        exclude_domains: Annotated[Optional[list[str]], "Exclude these domains. Example: ['pinterest.com', 'facebook.com']"] = None,
        start_published_date: Annotated[Optional[str], "Only results published after this date (YYYY-MM-DD). Note: Many pages lack dates."] = None,
        end_published_date: Annotated[Optional[str], "Only results published before this date (YYYY-MM-DD)"] = None,
        include_text: Annotated[Optional[str], "Require this exact phrase in results. Example: 'RLHF' for that specific term"] = None,
        exclude_text: Annotated[Optional[str], "Exclude results with this phrase. Example: 'subscription required'"] = None,
    ) -> str:
        """Search the web using Exa's neural search engine, which uses 'next-link prediction' to find semantically relevant content. Returns metadata and URLs (not content by default).

        ## CORE CONCEPT
        Exa's neural search predicts what links would naturally follow your text. Instead of matching keywords, it understands meaning and finds conceptually related content. This makes it exceptional at finding personal pages, niche content, and complex multi-criteria results that Google would miss.

        ## QUERY CRAFTING - Write as Natural Language Link Introductions
        Exa works best when you write queries as if you're about to paste a link, not searching for one:

        1. **Natural Completion Style** - End with colons, write like recommending to a friend:
            "Here's an excellent guide to understanding transformer architectures:"
            "If you're struggling with Python async programming, this tutorial is perfect:"

        2. **Explicit Content Type Signaling** - State what you're looking for:
            "Here's a GitHub repo that implements RLHF from scratch:"
            "LinkedIn profile of a machine learning engineer at a FAANG company:"

        3. **Multi-Constraint Layering** - Use comma-separated clauses:
            "SaaS companies, with ARR over $10M, founded after 2020, focused on developer tools:"
            "Engineers with 5+ years experience, who've worked at startups, contributing to Rust projects:"

        4. **Evaluative Language for Quality** - Include quality signals:
            "The most comprehensive guide to distributed systems design:"
            "Leading researchers in quantum error correction:"

        5. **Temporal Context** - Embed time explicitly:
            "Startups that raised Series A funding in 2024:"
            "Latest breakthroughs in fusion energy research:"

        6. **Tone Matching** - Match query tone to expected content:
           Personal: "The coolest personal blogs about mechanical keyboards:"
           Academic: "Peer-reviewed meta-analysis of mindfulness interventions:"

        7. **Opposition/Alternatives** - Use explicit disagreement language:
            "Research papers that challenge the efficient market hypothesis:"
            "Alternative approaches to transformer architectures:"

        ## SEARCH TYPES
        - **auto** (default): Intelligently combines keyword + neural. Best for most queries.
          USE WHEN: You want comprehensive results, mixing specific terms with conceptual understanding
          EXAMPLE: "OpenAI GPT-4 technical capabilities:" (needs both the specific product name AND related concepts)
        
        - **neural**: Pure semantic search. Best for exploratory/thematic searches, complex criteria, finding conceptually similar content.
          USE WHEN: You care about meaning/concepts over exact terms, want diverse perspectives, or have complex multi-constraint queries
          EXAMPLE: "Innovative approaches to sustainable urban transportation that don't rely on fossil fuels:"
          EXAMPLE: "Personal blogs by engineers who transitioned from academia to industry:"
        
        - **keyword**: Traditional word matching. Best for proper nouns, exact phrases, specific jargon, when neural isn't working.
          USE WHEN: Searching for specific products, people, companies, technical terms, or when neural gives too broad results
          EXAMPLE: "YC W24 batch companies" (specific program/batch)
          EXAMPLE: "next.config.js app router" (exact technical terms)

        ## CATEGORIES - USE SPARINGLY
        Categories filter to ONLY that content type, excluding everything else:

        **research paper**: 
        - INCLUDES: Academic papers, arXiv, peer-reviewed journals
        - EXCLUDES: Blog analysis, news about research, whitepapers
        - USE WHEN: You specifically need formal academic research
        - QUERY STYLE: "Peer-reviewed studies examining [specific phenomenon]:"

        **company**:
        - INCLUDES: Official company homepages, about pages
        - EXCLUDES: News about companies, reviews, analysis
        - USE WHEN: You need official company information
        - QUERY STYLE: "Homepage of a company that [does X]:"

        **news**:
        - INCLUDES: News articles from news organizations
        - EXCLUDES: Press releases, blogs, primary sources
        - USE WHEN: You want journalist-written coverage
        - QUERY STYLE: "Recent news about [topic]:"

        **linkedin profile**:
        - INCLUDES: Individual LinkedIn profiles
        - EXCLUDES: Company pages, job postings
        - USE WHEN: Finding specific professionals
        - QUERY STYLE: "[Role] at [company] with experience in [domain]:"

        **github**:
        - INCLUDES: GitHub repositories
        - EXCLUDES: Discussions about code, tutorials
        - USE WHEN: Finding actual code implementations
        - QUERY STYLE: "GitHub repo that implements [specific functionality]:"

        **personal site**:
        - INCLUDES: Personal blogs, portfolios, individual websites
        - EXCLUDES: Company blogs, Medium publications
        - USE WHEN: Finding individual perspectives
        - QUERY STYLE: "Personal blog about [niche interest]:"

        TIP: If using a category, also search WITHOUT it to catch cross-category gems.

        ## FILTERS - REMEMBER: FILTERS EXCLUDE, NOT ENHANCE
        - **include_domains**: ONLY search within these domains (risky - you might miss gems)
          Example: ["arxiv.org", "nature.com"] for academic sources only
        - **exclude_domains**: Remove specific domains (useful for removing noise/paywalls)
          Example: ["pinterest.com", "facebook.com"] to avoid social media
        - **start_published_date/end_published_date**: Date bounds (BUT many quality pages lack dates!)
        - **include_text**: Require this exact phrase in results (great for technical terms)
          Example: "RLHF" when researching reinforcement learning from human feedback
        - **exclude_text**: Exclude results containing this exact phrase
          Example: "subscription required" to avoid paywalled content

        Start broad (no filters), then narrow if needed. Better to filter results after than miss them entirely.

        ## LIVECRAWL - FRESHNESS VS RELIABILITY
        - **always**: Force fresh crawl. For real-time data (stock prices, breaking news). May fail if site is down.
        - **preferred**: Try fresh, fall back to cache. Best for production apps.
        - **fallback** (default): Cache first, crawl if missing. Balanced approach.
        - **never**: Maximum speed, cached only. For historical/static content.

        ## RESPONSE FORMAT
        By default, returns metadata only (NO content):
        - url, title, author, published_date
        - score: Relevance score (higher = better match)
        - NO text content unless you use the get_contents tool

        ## COMMON PITFALLS
        L Don't write questions ("what is X?" � "Here is information about X:")
        L Don't over-filter (start broad, narrow later)
        L Don't use livecrawl='always' for static content
        L Don't expect Google-style results from neural search
        L Don't forget the colon at the end of introduction-style queries

        Args:
            query: Search query following the patterns above. End with colon for best results.
            search_type: auto, neural, keyword, or fast search type
            num_results: Number of results to return (1-100, default 10)
            category: Filter to specific content type. WARNING: Excludes all other types!
            include_domains: ONLY return results from these domains. Example: ["arxiv.org", "nature.com"]
            exclude_domains: Exclude these domains. Example: ["pinterest.com", "facebook.com"]
            start_published_date: Only results published after this date (YYYY-MM-DD). Note: Many pages lack dates.
            end_published_date: Only results published before this date (YYYY-MM-DD)
            include_text: Require this exact phrase in results. Example: "RLHF" for that specific term
            exclude_text: Exclude results with this phrase. Example: "subscription required"
        """
        # Convert single strings to lists for text filters (Exa expects lists)
        include_text_list = [include_text] if include_text else None
        exclude_text_list = [exclude_text] if exclude_text else None
        
        try:
            # Get the Exa client
            client = get_exa_client()
            
            # Call Exa search (no content retrieval by default)
            search_response = await client.search(
                query=query,
                type=search_type,
                num_results=num_results,
                category=category,
                include_domains=include_domains,
                exclude_domains=exclude_domains,
                start_published_date=start_published_date,
                end_published_date=end_published_date,
                include_text=include_text_list,
                exclude_text=exclude_text_list,
                # Note: livecrawl doesn't apply to search itself, only contents
            )
            
            output = []
            
            # Add search metadata if useful
            if hasattr(search_response, 'autoprompt_string') and search_response.autoprompt_string:
                output.append(f"Enhanced query: {search_response.autoprompt_string}")
            if hasattr(search_response, 'resolved_search_type') and search_response.resolved_search_type:
                output.append(f"Search type used: {search_response.resolved_search_type}\n")
            
            # Format each result cleanly
            for i, result in enumerate(search_response.results, 1):
                output.append(f"{i}. {result.title or 'Untitled'}")
                output.append(f"   {result.url}")
                if hasattr(result, 'score') and result.score:
                    output.append(f"   Relevance: {result.score:.2f}")
                if hasattr(result, 'published_date') and result.published_date:
                    output.append(f"   Published: {result.published_date[:10]}")  # Just date
                if hasattr(result, 'author') and result.author and len(result.author) < 50:  # Skip long author lists
                    output.append(f"   Author: {result.author}")
                output.append("")  # Blank line between results
            
            return "\n".join(output)
            
        except Exception as e:
            return f"Search failed: {str(e)}\n\nPlease check your EXA_API_KEY environment variable."
    
    @mcp.tool
    async def exa_get_contents(
        urls: Annotated[list[str], "URLs to fetch content from"],
        text: Annotated[bool, "Include full text content"] = True,
        text_max_characters: Annotated[Optional[int], "Limit text length (optional)"] = None,
        include_html_tags: Annotated[bool, "Keep HTML tags in text content"] = False,
        livecrawl: Annotated[Literal["always", "preferred", "fallback", "never"], "Freshness strategy - use 'preferred' for research needing current data"] = "fallback"
    ) -> str:
        """Retrieve content from URLs or result IDs obtained from previous searches. Use this to get the actual text/content after searching.

        ## PRIMARY USE CASES
        1. **After searching** - You found relevant results and now need their content
        2. **Refreshing content** - Get fresh version of previously found pages with livecrawl
        3. **External URLs** - Process URLs from outside Exa (user-provided, from other tools)

        ## URL FORMATS ACCEPTED
        - Direct URLs: 'https://example.com/article'
        - URLs from search results
        - Any valid web URL

        ## LIVECRAWL STRATEGY
        - Use 'preferred' or 'always' when you need current information (recent news, updated docs)
        - Use 'fallback' or 'never' for historical/static content (old papers, archived posts)
        - Default 'fallback' balances speed and freshness

        ## TYPICAL PATTERNS
        - Get content for top 5-10 most relevant results after search
        - Refresh specific pages with livecrawl='preferred' for current research
        - Process user-provided URLs alongside search results

        Args:
            urls: URLs to fetch content from
            text: Include full text content
            text_max_characters: Limit text length (optional)
            include_html_tags: Keep HTML tags in text content
            livecrawl: Freshness strategy - use 'preferred' for research needing current data
        """
        # Validate inputs
        if not urls:
            raise ValueError("At least one URL must be provided")
        
        if len(urls) > 100:
            raise ValueError("Maximum 100 URLs allowed per request")
        
        # Build text options if customized
        text_options = True
        if text and (text_max_characters or include_html_tags):
            text_options = {}
            if text_max_characters:
                text_options["max_characters"] = text_max_characters
            if include_html_tags:
                text_options["include_html_tags"] = include_html_tags
        
        try:
            # Get the Exa client
            client = get_exa_client()
            
            # Get contents from Exa
            contents_response = await client.get_contents(
                urls=urls,  # The API expects 'urls' parameter
                text=text_options if text else False,
                livecrawl=livecrawl,
            )
            
            output = []
            
            # Format each content result
            for i, result in enumerate(contents_response.results, 1):
                output.append(f"=== Content {i} ===")
                output.append(f"Title: {result.title or 'Untitled'}")
                output.append(f"URL: {result.url}")
                
                if hasattr(result, 'author') and result.author:
                    output.append(f"Author: {result.author}")
                if hasattr(result, 'published_date') and result.published_date:
                    output.append(f"Published: {result.published_date[:10]}")
                
                if text and hasattr(result, 'text') and result.text:
                    output.append(f"\nContent:")
                    output.append(result.text)
                
                output.append("")  # Blank line between results
            
            # Include error information if there were failures
            if hasattr(contents_response, 'statuses') and contents_response.statuses:
                errors = [s for s in contents_response.statuses 
                          if hasattr(s, 'status') and s.status == "error"]
                if errors:
                    output.append("\n=== Errors ===")
                    for error in errors:
                        error_url = error.url if hasattr(error, 'url') else "Unknown URL"
                        error_msg = error.source if hasattr(error, 'source') else "Unknown error"
                        output.append(f"Failed to fetch {error_url}: {error_msg}")
            
            return "\n".join(output)
            
        except Exception as e:
            return f"Failed to retrieve contents: {str(e)}\n\nPlease check your EXA_API_KEY and the provided URLs."

# Create the FastMCP server instance
mcp = FastMCP("Exa Research Server 🔍")

# Set up the Exa search tool
setup_search_tool(mcp)

if __name__ == "__main__":
    # Run the server
    print("Starting Exa MCP Server...")
    mcp.run()
