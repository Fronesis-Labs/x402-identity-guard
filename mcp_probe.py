import asyncio
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

URL = "https://mcp.fronesislabs.com/mcp"


async def main():
    print(f"Connecting to: {URL}")

    async with streamablehttp_client(URL) as (
        read_stream,
        write_stream,
        _,
    ):
        async with ClientSession(read_stream, write_stream) as session:
            print("\nInitializing...")
            result = await session.initialize()

            print("\n=== SERVER ===")
            print(result.serverInfo)

            print("\n=== TOOLS ===")
            tools = await session.list_tools()

            for tool in tools.tools:
                print(f"\n--- {tool.name} ---")
                print(tool.description)
                print(tool.inputSchema)


if __name__ == "__main__":
    asyncio.run(main())