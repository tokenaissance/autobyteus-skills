"""Transport-neutral result contracts for browser operations.

No postponed annotations here: `NotRequired` keys must stay visible to `TypedDict` (and MCP schemas).
`dialogs` is also nullable because FastMCP serializes an absent optional key as null; the CLI omits it.
"""

from typing import Any, Literal, NotRequired, TypedDict

WaitUntil = Literal["domcontentloaded", "load", "networkidle"]
CleaningMode = Literal["raw", "text", "thorough"]
ImageFormat = Literal["png", "jpeg"]


class TabSummary(TypedDict):
    tab_id: str
    url: str
    title: str | None


class DialogReportPayload(TypedDict):
    """A page dialog the operation's own tab raised, and what happened to it."""

    tab_id: str
    type: Literal["alert", "confirm", "prompt", "beforeunload"]
    message: str
    default_value: str
    outcome: Literal["closed", "accepted", "dismissed"]
    decided_by: Literal["agent", "unblock"] | None


class OpenTabResult(TabSummary):
    dialogs: NotRequired[list[DialogReportPayload] | None]


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
    dialogs: NotRequired[list[DialogReportPayload] | None]


class NavigateResult(TypedDict):
    tab_id: str
    url: str
    ok: bool
    status: int | None
    dialogs: NotRequired[list[DialogReportPayload] | None]


class ArtifactResult(TypedDict):
    path: str
    media_type: str
    bytes_written: int


class ReadPageInlineResult(TypedDict):
    tab_id: str
    url: str
    output_mode: Literal["inline"]
    content: str
    dialogs: NotRequired[list[DialogReportPayload] | None]


class ReadPageArtifactResult(TypedDict):
    tab_id: str
    url: str
    output_mode: Literal["artifact"]
    artifact: ArtifactResult
    dialogs: NotRequired[list[DialogReportPayload] | None]


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
    dialogs: NotRequired[list[DialogReportPayload] | None]


class DomSnapshotArtifactResult(TypedDict):
    tab_id: str
    url: str
    output_mode: Literal["artifact"]
    artifact: ArtifactResult
    dialogs: NotRequired[list[DialogReportPayload] | None]


class RunScriptInlineResult(TypedDict):
    tab_id: str
    url: str
    output_mode: Literal["inline"]
    result: Any
    dialogs: NotRequired[list[DialogReportPayload] | None]


class RunScriptArtifactResult(TypedDict):
    tab_id: str
    url: str
    output_mode: Literal["artifact"]
    artifact: ArtifactResult
    dialogs: NotRequired[list[DialogReportPayload] | None]


class ScreenshotResult(TypedDict):
    tab_id: str
    url: str
    artifact: ArtifactResult
    dialogs: NotRequired[list[DialogReportPayload] | None]


class StartRecordingResult(TypedDict):
    tab_id: str
    output_file: str
    fps: int
    started_at: str


class StopRecordingResult(TypedDict):
    tab_id: str
    artifact: ArtifactResult
    duration_seconds: float
    frames: int
    end_reason: Literal["stopped", "target_closed"]


class ErrorPayload(TypedDict):
    code: str
    message: str
    retryable: bool
    details: NotRequired[dict[str, Any]]


ReadPageResult = ReadPageInlineResult | ReadPageArtifactResult
DomSnapshotResult = DomSnapshotInlineResult | DomSnapshotArtifactResult
RunScriptResult = RunScriptInlineResult | RunScriptArtifactResult
