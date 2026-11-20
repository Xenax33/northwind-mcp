"""Our error format: every refusal has a fixed code, a message and a hint.

Tools raise `NorthwindError`. It subclasses the SDK's `ToolError`, so the SDK
returns it to the client as a tool result with `isError: true` and the JSON
below as text, which the model reads and can act on. Anything else that is
raised counts as a crash: the SDK logs it on the server and the model sees only
"Error executing tool <name>", so no SQL, paths or stack traces leak out.

The hints are fixed sentences written here, not generated: they tell the
calling model which tool or argument to use instead.
"""

from __future__ import annotations

import json
from typing import Literal

from mcp.server.mcpserver.exceptions import ToolError

ErrorCode = Literal[
    "not_found",  # the ID does not exist
    "invalid_argument",  # the request is malformed or contradictory
    "discontinued",  # the product is no longer sold
    "out_of_stock",  # not enough units in stock for the order
    "declined",  # the user declined (or the client could not ask)
]


class NorthwindError(ToolError):
    def __init__(self, code: ErrorCode, message: str, hint: str | None = None) -> None:
        self.code = code
        self.message = message
        self.hint = hint
        super().__init__(json.dumps(self.to_dict(), ensure_ascii=False))

    def to_dict(self) -> dict[str, str]:
        body = {"error": self.code, "message": self.message}
        if self.hint:
            body["hint"] = self.hint
        return body
