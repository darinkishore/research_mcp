from __future__ import annotations

import asyncio

import uvloop
from stackprinter import set_excepthook

from . import server
from .server import main


set_excepthook(style='darkbg2')


def run_server():
    """Entry point for the research-mcp command."""
    return uvloop.run(main())


# Optionally expose other important items at package level
__all__ = ['main', 'run_server', 'server']
