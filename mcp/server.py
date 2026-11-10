import base64
import hmac
import json
import os
from typing import Any
from urllib.parse import quote

import httpx
import uvicorn
from mcp.server import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.types import ASGIApp, Receive, Scope, Send


REBURP_URL = os.environ.get("REBURP_URL", "http://127.0.0.1:9090").rstrip("/")
HTTP_METHODS = {"get", "post", "put", "patch", "delete"}
mcp = MCPServer("reburp")


class BearerAuth:
    def __init__(self, app: ASGIApp, token: str) -> None:
        self.app = app
        self.token = token

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        authorization_headers = [
            value for name, value in scope["headers"] if name.lower() == b"authorization"
        ]
        if len(authorization_headers) == 1:
            authorization = authorization_headers[0].decode("latin-1")
            scheme, separator, supplied_token = authorization.partition(" ")
            if separator and scheme.lower() == "bearer" and hmac.compare_digest(supplied_token, self.token):
                await self.app(scope, receive, send)
                return

        response = PlainTextResponse(
            "Unauthorized",
            status_code=401,
            headers={"WWW-Authenticate": 'Bearer realm="reburp-mcp"'},
        )
        await response(scope, receive, send)


async def get_openapi() -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=10, trust_env=False) as client:
            response = await client.get(f"{REBURP_URL}/openapi.json")
            response.raise_for_status()
            spec = response.json()
    except (httpx.HTTPError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Failed to load Reburp OpenAPI from {REBURP_URL}: {exc}") from exc
    if not isinstance(spec, dict) or not isinstance(spec.get("paths"), dict):
        raise RuntimeError(f"Invalid Reburp OpenAPI document at {REBURP_URL}/openapi.json")
    return spec


def find_operation(spec: dict[str, Any], operation_id: str) -> tuple[str, str, dict[str, Any]]:
    for path, path_item in spec["paths"].items():
        for method, operation in path_item.items():
            if method in HTTP_METHODS and operation.get("operationId") == operation_id:
                return path, method, operation
    raise ValueError(f"Unknown Reburp operationId: {operation_id}. Use search_operations first.")


def resolve_ref(spec: dict[str, Any], ref: str) -> Any:
    if not ref.startswith("#/"):
        raise ValueError(f"Unsupported OpenAPI reference: {ref}")
    value: Any = spec
    for part in ref[2:].split("/"):
        value = value[part.replace("~1", "/").replace("~0", "~")]
    return value


def referenced_components(spec: dict[str, Any], operation: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            ref = value.get("$ref")
            if ref and ref not in result:
                result[ref] = resolve_ref(spec, ref)
                visit(result[ref])
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(operation)
    return result


def scalar(value: Any) -> str:
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, (str, int, float)):
        return str(value)
    raise ValueError(f"Unsupported parameter value type: {type(value).__name__}")


def parameter_pairs(values: dict[str, Any]) -> list[tuple[str, str]]:
    pairs = []
    for name, value in values.items():
        if isinstance(value, list):
            pairs.extend((name, scalar(item)) for item in value)
        else:
            pairs.append((name, scalar(value)))
    return pairs


@mcp.tool()
async def status() -> dict[str, Any]:
    """Check whether Burp Community and Reburp are running."""
    try:
        async with httpx.AsyncClient(timeout=10, trust_env=False) as client:
            response = await client.get(f"{REBURP_URL}/api/status")
            response.raise_for_status()
            return response.json()
    except (httpx.HTTPError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Failed to read Reburp status at {REBURP_URL}: {exc}") from exc


@mcp.tool()
async def search_operations(
    query: str = "", tag: str = "", offset: int = 0, limit: int = 50
) -> dict[str, Any]:
    """Search live Reburp operations by name, path, description, or tag. Results are paginated."""
    if offset < 0 or not 1 <= limit <= 100:
        raise ValueError("offset must be nonnegative and limit must be between 1 and 100")
    spec = await get_openapi()
    matches = []
    for path, path_item in spec["paths"].items():
        for method, operation in path_item.items():
            if method not in HTTP_METHODS:
                continue
            tags = operation.get("tags", [])
            haystack = " ".join(
                [
                    operation["operationId"],
                    path,
                    operation.get("summary", ""),
                    operation.get("description", ""),
                    *tags,
                ]
            ).lower()
            if query.lower() not in haystack or (tag and not any(tag.lower() == item.lower() for item in tags)):
                continue
            matches.append(
                {
                    "operation_id": operation["operationId"],
                    "method": method.upper(),
                    "path": path,
                    "summary": operation.get("summary", ""),
                    "tags": tags,
                }
            )
    return {
        "total": len(matches),
        "offset": offset,
        "limit": limit,
        "operations": matches[offset : offset + limit],
    }


@mcp.tool()
async def describe_operation(operation_id: str) -> dict[str, Any]:
    """Read one live OpenAPI operation, including request/response schemas and examples."""
    spec = await get_openapi()
    path, method, operation = find_operation(spec, operation_id)
    return {
        "operation_id": operation_id,
        "method": method.upper(),
        "path": path,
        "operation": operation,
        "referenced_components": referenced_components(spec, operation),
    }


@mcp.tool()
async def call_operation(
    operation_id: str,
    path_parameters: dict[str, Any] | None = None,
    query_parameters: dict[str, Any] | None = None,
    body: Any = None,
) -> dict[str, Any]:
    """Call a Reburp operation by operationId. Describe it first to get exact parameters and JSON body."""
    spec = await get_openapi()
    path, method, operation = find_operation(spec, operation_id)
    path_template = path
    parameters = spec["paths"][path].get("parameters", []) + operation.get("parameters", [])
    path_parameters = path_parameters or {}
    query_parameters = query_parameters or {}
    expected_path = {item["name"] for item in parameters if item["in"] == "path"}
    expected_query = {item["name"] for item in parameters if item["in"] == "query"}
    missing_path = expected_path - path_parameters.keys()
    unknown_path = path_parameters.keys() - expected_path
    missing_query = {
        item["name"] for item in parameters if item["in"] == "query" and item.get("required")
    } - query_parameters.keys()
    unknown_query = query_parameters.keys() - expected_query
    if missing_path or unknown_path or missing_query or unknown_query:
        raise ValueError(
            f"Invalid parameters for {operation_id}: missing path={sorted(missing_path)}, "
            f"unknown path={sorted(unknown_path)}, missing query={sorted(missing_query)}, "
            f"unknown query={sorted(unknown_query)}"
        )
    for name, value in path_parameters.items():
        path = path.replace("{" + name + "}", quote(scalar(value), safe=""))
    request_body = operation.get("requestBody")
    if request_body and request_body.get("required") and body is None:
        raise ValueError(f"{operation_id} requires a JSON body")
    if body is not None and not request_body:
        raise ValueError(f"{operation_id} does not accept a request body")

    try:
        async with httpx.AsyncClient(timeout=120, trust_env=False) as client:
            response = await client.request(
                method.upper(),
                f"{REBURP_URL}{path}",
                params=parameter_pairs(query_parameters),
                json=body if body is not None else None,
            )
    except httpx.HTTPError as exc:
        raise RuntimeError(f"Failed to call {operation_id} ({method.upper()} {path_template}): {exc}") from exc

    content_type = response.headers.get("content-type", "")
    if not response.content:
        result: Any = None
    elif "json" in content_type:
        try:
            result = response.json()
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"Invalid JSON response from {operation_id} ({method.upper()} {path_template}): {exc}"
            ) from exc
    elif content_type.startswith("text/"):
        result = response.text
    else:
        result = {"base64": base64.b64encode(response.content).decode("ascii")}
    return {"status_code": response.status_code, "content_type": content_type, "body": result}


@mcp.custom_route("/health", methods=["GET"])
async def health(_: Any) -> JSONResponse:
    return JSONResponse({"status": "ok"})


if __name__ == "__main__":
    token = os.environ.get("MCP_BEARER_TOKEN", "")
    if len(token) < 32 or any(character.isspace() for character in token):
        raise RuntimeError("MCP_BEARER_TOKEN must contain at least 32 characters and no whitespace")
    security = TransportSecuritySettings(
        allowed_hosts=["127.0.0.1:*", "localhost:*"],
        allowed_origins=["http://127.0.0.1:*", "http://localhost:*"],
    )
    app = mcp.streamable_http_app(
        host="0.0.0.0",
        stateless_http=True,
        json_response=True,
        transport_security=security,
    )
    uvicorn.run(BearerAuth(app, token), host="0.0.0.0", port=8765)
