from synapsekb.mcp.auth import McpSecurityMiddleware
from synapsekb.mcp.tools import mcp

app = McpSecurityMiddleware(mcp.streamable_http_app())
