```markdown
# test-mcp-http

Test HTTP MCP server endpoints using curl to verify transport, tool listing, and tool invocation.

## When to use

- After converting an MCP server from stdio to HTTP transport
- Verifying a new MCP server is reachable and responding correctly
- Debugging tool registration or invocation failures over HTTP

## Steps

### 1. Check server is running

```bash
curl -s http://localhost:<PORT>/health
# or check process
ps aux | grep <server_name>
```

### 2. List available tools

```bash
curl -s -X POST http://localhost:<PORT>/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' | jq .
```

Expected: `result.tools` array with name/description/inputSchema for each tool.

### 3. Invoke a tool

```bash
curl -s -X POST http://localhost:<PORT>/mcp \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": 2,
    "method": "tools/call",
    "params": {
      "name": "<tool_name>",
      "arguments": { "<key>": "<value>" }
    }
  }' | jq .
```

Expected: `result.content` array with tool output.

### 4. Check for streamable-http (SSE)

If the server uses streamable-http transport, include the Accept header:

```bash
curl -s -X POST http://localhost:<PORT>/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' | jq .
```

### 5. Common failure modes

| Symptom | Likely cause |
|---|---|
| `Connection refused` | Server not running or wrong port |
| `404` on `/mcp` | Wrong endpoint path (try `/`, `/sse`, `/messages`) |
| `result.tools` empty | Tools not registered at startup |
| Timeout | Server blocked on startup (e.g. model loading) |
| `error.code -32601` | Method not found — check method name spelling |

## Notes

- Default MCP HTTP port conventions vary; check server config or `settings.json`
- Use `jq .result.tools[].name` to quickly list just tool names
- For servers with auth, add `-H "Authorization: Bearer <token>"`
- If testing from Claude Code, the server must be registered in `settings.json` under `mcpServers`
```