import asyncio
import sys


async def forward(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while data := await reader.read(65536):
            writer.write(data)
            await writer.drain()
        if writer.can_write_eof():
            writer.write_eof()
    finally:
        writer.close()


async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        upstream_reader, upstream_writer = await asyncio.open_connection("127.0.0.1", 9090)
    except OSError as exc:
        print(f"Relay could not connect to Reburp at 127.0.0.1:9090: {exc}", file=sys.stderr)
        writer.close()
        await writer.wait_closed()
        return

    try:
        await asyncio.gather(
            forward(reader, upstream_writer),
            forward(upstream_reader, writer),
        )
    finally:
        upstream_writer.close()
        writer.close()
        await asyncio.gather(upstream_writer.wait_closed(), writer.wait_closed())


async def main() -> None:
    server = await asyncio.start_server(handle_client, "0.0.0.0", 9091)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
