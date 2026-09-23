from mcp.server import MCPServer
from pydantic import BaseModel

mcp = MCPServer('Autonomous Portfolio Company Data Onboarding Agent')

class Health(BaseModel):
    status: str
    version: str

@mcp.tool()
def healthcheck() -> Health:
    """Return service health."""
    return Health(status="ok", version="0.1.0")

@mcp.resource("project://policies")
def policies() -> str:
    return 'Read-only discovery | Generated SQL runs in sandbox first | Human certifies metrics/joins | No raw PII in model context'

app = mcp.streamable_http_app()
