"""Typed graph state. Nodes overwrite the keys they return.

The state has no credentials, no order intent, and no approval flag that a
node is allowed to set true.
"""

from __future__ import annotations

from typing import TypedDict


class AnalysisState(TypedDict, total=False):
    run_id: str
    created_at: str
    instruments: list[str]
    horizon: str
    include_news: bool
    include_macro: bool
    include_derivatives: bool
    include_inference: bool
    accepted: list[dict]
    rejected: list[dict]
    evidence: list[dict]
    quality: dict
    node_status: dict
    errors: list[dict]
    missing: list[str]
    conflicts: list[dict]
    inference: dict
    report: dict
