"""Isolated MCP v2 server. State changes affect only a fresh trial-local dictionary."""
from mcp.server.mcpserver import MCPServer
from inventory_data import INITIAL_STOCK


def make_server():
    stock = INITIAL_STOCK.copy()
    server = MCPServer("Thesis MCP Verified Tools", instructions="Sandbox tools only; reservations change only trial-local synthetic inventory.")

    @server.tool()
    def check_stock(sku: str) -> dict:
        """Read remaining stock for a known SKU. No data is changed."""
        if sku not in stock:
            raise ValueError(f"Unknown SKU: {sku}")
        return {"sku": sku, "available": stock[sku]}

    @server.tool()
    def reserve_stock(sku: str, quantity: int) -> dict:
        """STATE CHANGING: reserve a positive whole-number quantity of a known SKU."""
        if sku not in stock:
            raise ValueError(f"Unknown SKU: {sku}")
        if type(quantity) is not int or not (1 <= quantity <= 100):
            raise ValueError("Reservation quantity must be an integer between 1 and 100")
        if stock[sku] < quantity:
            raise ValueError("Insufficient stock")
        stock[sku] -= quantity
        return {"sku": sku, "reserved": quantity, "remaining": stock[sku]}

    @server.tool()
    def list_products() -> dict:
        """List known inventory product identifiers without changing stock."""
        return {"products": sorted(stock)}

    return server


mcp = make_server()
if __name__ == "__main__":
    mcp.run()
