"""Transport-neutral result contracts for browser operations."""

from __future__ import annotations

from typing import Any, Literal, NotRequired, TypedDict

WaitUntil = Literal["domcontentloaded", "load", "networkidle"]
CleaningMode = Literal["raw", "text", "thorough"]
ImageFormat = Literal["png", "jpeg"]


class TabSummary(TypedDict):
    tab_id: str
    url: str
    title: str | None


class HealthCheckResult(TypedDict):
    connected: bool
    endpoint: str
    context_count: int
    page_count: int


class ListTabsResult(TypedDict):
    tabs: list[TabSummary]


class CloseTabResult(TypedDict):
    tab_id: str
    closed: bool


class NavigateResult(TypedDict):
    tab_id: str
    url: str
    ok: bool
    status: int | None


class ArtifactResult(TypedDict):
    path: str
    media_type: str
    bytes_written: int


class ReadPageInlineResult(TypedDict):
    tab_id: str
    url: str
    output_mode: Literal["inline"]
    content: str


class ReadPageArtifactResult(TypedDict):
    tab_id: str
    url: str
    output_mode: Literal["artifact"]
    artifact: ArtifactResult


class BoundingBox(TypedDict):
    x: float
    y: float
    width: float
    height: float


class DomSnapshotElement(TypedDict):
    element_id: str
    tag_name: str
    dom_id: str | None
    css_selector: str
    role: str | None
    name: str | None
    text: str | None
    href: str | None
    value: str | None
    bounding_box: BoundingBox | None


class DomSnapshotInlineResult(TypedDict):
    tab_id: str
    url: str
    output_mode: Literal["inline"]
    elements: list[DomSnapshotElement]
    total_candidates: int
    returned_elements: int
    truncated: bool


class DomSnapshotArtifactResult(TypedDict):
    tab_id: str
    url: str
    output_mode: Literal["artifact"]
    artifact: ArtifactResult


class RunScriptInlineResult(TypedDict):
    tab_id: str
    url: str
    output_mode: Literal["inline"]
    result: Any


class RunScriptArtifactResult(TypedDict):
    tab_id: str
    url: str
    output_mode: Literal["artifact"]
    artifact: ArtifactResult


class ScreenshotResult(TypedDict):
    tab_id: str
    url: str
    artifact: ArtifactResult


class ErrorPayload(TypedDict):
    code: str
    message: str
    retryable: bool
    details: NotRequired[dict[str, Any]]


ReadPageResult = ReadPageInlineResult | ReadPageArtifactResult
DomSnapshotResult = DomSnapshotInlineResult | DomSnapshotArtifactResult
RunScriptResult = RunScriptInlineResult | RunScriptArtifactResult
