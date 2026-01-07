"""
MCP Client for Cinema Chat
Communicates with the MCP server via stdio (subprocess)
"""
import asyncio
import json
import os
from typing import Any, Dict
from loguru import logger

class MCPClient:
    """Simple MCP client that communicates with MCP server via subprocess"""

    def __init__(self, server_script_path: str):
        self.server_script_path = server_script_path
        self.process = None
        self.request_id = 0
        self._lock = asyncio.Lock()  # Serialize stdio access (required for request/response matching)

    async def start(self):
        """Start the MCP server as a subprocess"""
        # Use venv python to ensure httpx and other dependencies are available
        import sys
        python_path = sys.executable  # Use the same python that's running the bot
        logger.info(f"[MCP] Starting MCP server: {self.server_script_path} with {python_path}")
        self.process = await asyncio.create_subprocess_exec(
            python_path,
            self.server_script_path,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        # Send initialization request
        await self._send_request("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {
                "name": "cinema-chat-bot",
                "version": "1.0.0"
            }
        })

        # Read initialization response
        response = await self._read_response()
        logger.info(f"[MCP] Server initialized: {response}")

    async def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> str:
        """Call an MCP tool and return the result

        Note: We use a lock to serialize stdio access because:
        1. Multiple concurrent writes to stdin could interleave
        2. We need to match responses to requests (no out-of-order handling)
        3. The timeout prevents the lock from being held forever if MCP server hangs
        """
        # Acquire lock with timeout to prevent deadlock
        try:
            await asyncio.wait_for(self._lock.acquire(), timeout=15.0)
        except asyncio.TimeoutError:
            logger.error(f"[MCP] Timeout acquiring lock for {tool_name} - another request is stuck!")
            return json.dumps({"error": "MCP client busy - previous request stuck", "tool": tool_name})

        try:
            self.request_id += 1
            request_id = self.request_id

            logger.info(f"[MCP] Calling tool: {tool_name} (request {request_id})")

            await self._send_request("tools/call", {
                "name": tool_name,
                "arguments": arguments
            }, request_id=request_id)

            # Add timeout to prevent hanging forever
            try:
                response = await asyncio.wait_for(self._read_response(), timeout=10.0)
            except asyncio.TimeoutError:
                logger.error(f"[MCP] Timeout waiting for response to {tool_name} (request {request_id})")
                return json.dumps({"error": "MCP server timeout", "tool": tool_name, "request_id": request_id})

            if "result" in response:
                # Extract text content from MCP response
                contents = response["result"].get("content", [])
                if contents and len(contents) > 0:
                    text = contents[0].get("text", "")
                    logger.info(f"[MCP] Tool result for request {request_id}: {text[:200]}")
                    return text

            logger.error(f"[MCP] Unexpected response for request {request_id}: {response}")
            return json.dumps({"error": f"Unexpected response: {response}"})

        finally:
            # Always release the lock, even if there was an error
            self._lock.release()

    async def _send_request(self, method: str, params: Dict[str, Any], request_id: int = None):
        """Send a JSON-RPC request to the MCP server"""
        if request_id is None:
            request_id = self.request_id

        message = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params
        }

        json_str = json.dumps(message) + "\n"
        self.process.stdin.write(json_str.encode())
        await self.process.stdin.drain()

    async def _read_response(self) -> Dict[str, Any]:
        """Read a JSON-RPC response from the MCP server"""
        line = await self.process.stdout.readline()
        return json.loads(line.decode())

    async def stop(self):
        """Stop the MCP server"""
        if self.process:
            self.process.terminate()
            await self.process.wait()
            logger.info("[MCP] Server stopped")


# Global MCP client instance
_mcp_client = None

async def get_mcp_client() -> MCPClient:
    """Get or create the global MCP client"""
    global _mcp_client
    if _mcp_client is None:
        # Path to MCP server
        server_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "mcp_server",
            "server.py"
        )
        _mcp_client = MCPClient(server_path)
        await _mcp_client.start()
    return _mcp_client
