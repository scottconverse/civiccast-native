# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Public request-validation errors without submitted values or exception context."""

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from pydantic_core import PydanticKnownError
from starlette.responses import JSONResponse

# Only these fixed application messages may cross the public error boundary.
# Never forward arbitrary ValueError text, input values or validator context.
PUBLIC_VALIDATION_MESSAGES = {
    "control_characters": "This field cannot contain control characters.",
    "recording_location": (
        "Use a local recording location: a file:// URI (for example "
        "file:///C:/recordings), a Windows drive path (C:\\recordings), "
        "or an absolute POSIX path. Relative paths and non-file schemes "
        "are not supported."
    ),
    "empty_publish_selection": (
        "No surfaces or overrides were selected, so nothing would be published. "
        "Omit the field to publish the Portal surface only, "
        "or list the surface ids to publish."
    ),
}


async def request_validation_response(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    errors = []
    for error in exc.errors():
        kind = error["type"]
        # Rebuild standard messages rather than forwarding a validator's msg:
        # ValueError text, JSON decoder context and union tags can contain secrets.
        # Numeric schema limits still produce useful length/range feedback.
        context = {
            key: value for key, value in error.get("ctx", {}).items() if type(value) in (int, float)
        }
        try:
            message = PydanticKnownError(kind, context).message()
        except (KeyError, TypeError):
            public_message = PUBLIC_VALIDATION_MESSAGES.get(kind)
            if public_message is None:
                kind = "value_error"
                message = "Invalid value. Check this field and try again."
            else:
                message = public_message
        location = list(error.get("loc", ()))
        if error["type"] == "extra_forbidden" and location:
            # An unrecognized field name is also arbitrary submitted input.
            location[-1] = "(extra field)"
        errors.append({"type": kind, "loc": location, "msg": message})
    return JSONResponse(status_code=422, content={"detail": errors})
