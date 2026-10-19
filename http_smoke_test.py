"""Verify real MCP communication over local Streamable HTTP transport."""
import asyncio
from mcp import Client


async def main():
    async with Client("http://127.0.0.1:8000/mcp") as client:
        catalog = await client.list_tools()
        print("HTTP MCP tools:", [t.name for t in catalog.tools])
        result = await client.call_tool("check_stock", {"sku": "PEN"})
        if result.is_error:
            raise RuntimeError(f"MCP returned an error: {result.content}")
        print("Stock result:", result.structured_content)
        print("LOCAL MCP HTTP CONNECTION: SUCCESS")


if __name__ == "__main__":
    asyncio.run(main())
