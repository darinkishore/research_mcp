# research exa server

does a big ol search

throws a big ol net

finds a lot of things. 

clone the repo,

then add the snippet below to your MCP client, replacing $DIR with the directory it's currently in.

ensure both EXA and OPENAI API keys are set. Braintrust optional. 

```json

"research": {
      "command": "uv",
      "args": [
        "--directory",
        "/$DIR/research_mcp",
        "run",
        "research-mcp"
      ],
      "env": {
        "EXA_API_KEY": "xxx",
        "OPENAI_API_KEY": "sk-yyy"
      }
    }
  }

```



blog post abt development: https://www.darinkishore.com/posts/mcp#building-tools-that-learn
