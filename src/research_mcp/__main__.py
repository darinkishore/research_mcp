from __future__ import annotations

import uvloop

from research_mcp.db import init_db
from research_mcp.server import main


if __name__ == '__main__':
    uvloop.run(init_db())
    uvloop.run(main())
