from __future__ import annotations

import uvloop
from stackprinter import set_excepthook

from . import server

set_excepthook(style='darkbg2')


def main():
    """Main entry point for the package."""
    uvloop.run(server.main())


# Optionally expose other important items at package level
__all__ = ['main', 'server']
