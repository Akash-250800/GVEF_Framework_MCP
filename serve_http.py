"""Optional local HTTP deployment of the real MCP tool server.

Runs on localhost:8000/mcp; does NOT expose to the public internet.
"""
from server import make_server

if __name__ == "__main__":
    mcp = make_server()
    mcp.run(transport="streamable-http", host="127.0.0.1", port=8000, stateless_http=True, json_response=True)
