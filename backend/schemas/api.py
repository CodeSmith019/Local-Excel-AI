"""API request and response schemas."""

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    """Request payload for starting or continuing a chat turn."""

    message: str = Field(description="User instruction for the spreadsheet")
    thread_id: str | None = Field(
        default=None, description="Optional conversation / checkpoint thread ID"
    )


class ConfirmRequest(BaseModel):
    """Request payload for confirming or rejecting a previewed patch."""

    thread_id: str = Field(description="Thread ID awaiting confirmation")
    approved: bool = Field(description="True to apply changes, False to cancel")


class UndoResponse(BaseModel):
    """Response payload for an undo operation."""

    restored: bool = Field(description="True if a snapshot was successfully restored")
    summary: str = Field(description="Summary of the undone change or status message")

