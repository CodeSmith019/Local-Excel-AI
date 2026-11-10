"""Spreadsheet operations package."""

from backend.excel.adapter import OpError
from backend.ops.registry import (
    REGISTRY,
    OpSpec,
    build_cell_patch,
    execute,
    implemented_ops,
    register,
)

__all__ = [
    "REGISTRY",
    "OpError",
    "OpSpec",
    "build_cell_patch",
    "execute",
    "implemented_ops",
    "register",
]

