"""Authoritative transport-neutral browser application boundary."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from browser_automation.cleaning import clean_html
from browser_automation.contracts import (
    CloseTabResult,
    DomSnapshotResult,
    HealthCheckResult,
    ListTabsResult,
    NavigateResult,
    OpenTabResult,
    ReadPageResult,
    RunScriptResult,
    ScreenshotResult,
    StartRecordingResult,
    StopRecordingResult,
    TabSummary,
)
from browser_automation.dom_snapshot import DOM_SNAPSHOT_SCRIPT, normalize_snapshot
from browser_automation.errors import (
    BrowserError,
    browser_operation_failed,
    dialog_decision_required,
    invalid_argument,
)
from browser_automation.json_codec import StrictJsonError, dumps_strict
from browser_automation.policy import (
    ArtifactPolicy,
    validate_choice,
    validate_dialog_option,
    validate_matcher,
    validate_tab_id,
    validate_timeout,
    validate_url,
)
from browser_automation.presentation import ensure_installed, script_uses_helper
from browser_automation.recording import RecordingService
from browser_automation.runtime import BrowserRuntime, BrowserSession
from browser_automation.runtime.dialogs import DialogDecision, DialogHandling
from browser_automation.script import normalize_script

WAIT_UNTIL_VALUES = ("domcontentloaded", "load", "networkidle")
CLEANING_MODES = ("raw", "text", "thorough")
IMAGE_FORMATS = ("png", "jpeg")
ResultT = TypeVar("ResultT")
MIN_RECORDING_FPS = 1
MAX_RECORDING_FPS = 60


class BrowserApplication:
    """Own validation, command sequencing, result creation, and safe effects."""

    def __init__(
        self,
        *,
        runtime: BrowserRuntime | None = None,
        artifact_policy: ArtifactPolicy | None = None,
        recording_service: RecordingService | None = None,
    ) -> None:
        self._runtime = runtime or BrowserRuntime()
        self._artifacts = artifact_policy or ArtifactPolicy.from_environment()
        self._recordings = recording_service or RecordingService()

    async def health_check(self) -> HealthCheckResult:
        async with self._runtime.session() as session:
            return {
                "connected": True,
                "endpoint": self._runtime.endpoint,
                "context_count": len(session.browser.contexts),
                "page_count": len([page for page in session.context.pages if not page.is_closed()]),
            }

    async def list_tabs(self) -> ListTabsResult:
        async with self._runtime.session() as session:
            return {"tabs": await session.list_tabs()}

    async def attach_tab(
        self,
        *,
        url_contains: str | None = None,
        title_contains: str | None = None,
    ) -> TabSummary:
        url_match = validate_matcher(url_contains, name="url_contains")
        title_match = validate_matcher(title_contains, name="title_contains")
        if not url_match and not title_match:
            raise invalid_argument("Provide at least one matcher: url_contains or title_contains.")

        async with self._runtime.session() as session:
            matches: list[tuple[Any, str | None]] = []
            for page in list(session.context.pages):
                if page.is_closed() or (url_match and url_match.lower() not in (page.url or "").lower()):
                    continue
                title: str | None = None
                try:
                    title = await page.title()
                except Exception:
                    pass
                if title_match and (not title or title_match.lower() not in title.lower()):
                    continue
                matches.append((page, title))

            if not matches:
                raise BrowserError(
                    "NO_TAB_MATCH",
                    "No tab matched the requested criteria.",
                    retryable=True,
                    exit_status=4,
                )
            if len(matches) > 1:
                raise BrowserError(
                    "AMBIGUOUS_TAB_MATCH",
                    "Multiple tabs matched; provide more specific criteria.",
                    retryable=True,
                    exit_status=4,
                    details={"match_count": len(matches)},
                )
            page, title = matches[0]
            return {
                "tab_id": await session.target_id_for_page(page),
                "url": page.url or "",
                "title": title,
            }

    async def open_tab(
        self,
        *,
        url: str | None = None,
        wait_until: str = "domcontentloaded",
        timeout_ms: int = 60_000,
    ) -> OpenTabResult:
        target_url = validate_url(url) if url is not None else None
        wait_mode = validate_choice(wait_until, name="wait_until", allowed=WAIT_UNTIL_VALUES)
        timeout = validate_timeout(timeout_ms)

        async def work(session: BrowserSession) -> OpenTabResult:
            page = None
            try:
                page, _tab_id = await session.open_target()
                if target_url:
                    await page.goto(target_url, wait_until=wait_mode, timeout=timeout)
                return await session.summarize_page(page)
            except PlaywrightTimeoutError as exc:
                if page is not None and not page.is_closed():
                    await page.close()
                raise BrowserError(
                    "NAVIGATION_TIMEOUT",
                    "The new tab did not finish navigation before the timeout.",
                    retryable=True,
                    exit_status=5,
                    details={"url": target_url, "timeout_ms": timeout},
                ) from exc
            except BrowserError:
                if page is not None and not page.is_closed():
                    await page.close()
                raise
            except Exception as exc:
                if page is not None and not page.is_closed():
                    await page.close()
                raise browser_operation_failed("The tab could not be opened.") from exc
        return await self._tab_operation(work, dialog_decision=None, can_decide=False)

    async def close_tab(self, *, tab_id: str) -> CloseTabResult:
        target_id = validate_tab_id(tab_id)
        async def work(session: BrowserSession) -> CloseTabResult:
            page = await session.resolve_target(target_id)
            try:
                await page.close()
            except Exception as exc:
                raise browser_operation_failed("The tab could not be closed.") from exc
            return {"tab_id": target_id, "closed": True}
        return await self._tab_operation(work, dialog_decision=None, can_decide=False)

    async def navigate(
        self,
        *,
        tab_id: str,
        url: str,
        wait_until: str = "domcontentloaded",
        timeout_ms: int = 60_000,
        dialog: str | None = None,
        prompt_text: str | None = None,
    ) -> NavigateResult:
        target_id = validate_tab_id(tab_id)
        decision = validate_dialog_option(dialog, prompt_text)
        target_url = validate_url(url)
        wait_mode = validate_choice(wait_until, name="wait_until", allowed=WAIT_UNTIL_VALUES)
        timeout = validate_timeout(timeout_ms)
        async def work(session: BrowserSession) -> NavigateResult:
            page = await session.resolve_target(target_id)
            try:
                response = await page.goto(target_url, wait_until=wait_mode, timeout=timeout)
            except PlaywrightTimeoutError as exc:
                raise BrowserError(
                    "NAVIGATION_TIMEOUT",
                    "Navigation did not finish before the timeout.",
                    retryable=True,
                    exit_status=5,
                    details={"tab_id": target_id, "url": target_url, "timeout_ms": timeout},
                ) from exc
            except Exception as exc:
                raise browser_operation_failed("Navigation failed.") from exc
            return {
                "tab_id": target_id,
                "url": page.url or target_url,
                "ok": bool(response and response.ok),
                "status": response.status if response else None,
            }
        return await self._tab_operation(work, dialog_decision=decision, can_decide=True)

    async def read_page(
        self,
        *,
        tab_id: str,
        cleaning_mode: str = "thorough",
        output_file: str | None = None,
        overwrite: bool = False,
    ) -> ReadPageResult:
        target_id = validate_tab_id(tab_id)
        mode = validate_choice(cleaning_mode, name="cleaning_mode", allowed=CLEANING_MODES)
        async def work(session: BrowserSession) -> ReadPageResult:
            page = await session.resolve_target(target_id)
            try:
                content = clean_html(await page.content(), mode)
            except Exception as exc:
                raise browser_operation_failed("The page content could not be read.") from exc
            if output_file is None:
                return {
                    "tab_id": target_id,
                    "url": page.url or "",
                    "output_mode": "inline",
                    "content": content,
                }
            media_type = "text/plain" if mode == "text" else "text/html"
            artifact = self._artifacts.write_text(
                output_file,
                content,
                overwrite=overwrite,
                media_type=media_type,
            )
            return {
                "tab_id": target_id,
                "url": page.url or "",
                "output_mode": "artifact",
                "artifact": artifact,
            }
        return await self._tab_operation(work, dialog_decision=None, can_decide=False)

    async def screenshot(
        self,
        *,
        tab_id: str,
        output_file: str,
        full_page: bool = True,
        image_format: str = "png",
        overwrite: bool = False,
    ) -> ScreenshotResult:
        target_id = validate_tab_id(tab_id)
        output_format = validate_choice(image_format, name="image_format", allowed=IMAGE_FORMATS)
        self._validate_bool(full_page, "full_page")
        self._validate_bool(overwrite, "overwrite")
        output = self._artifacts.resolve_output(output_file, overwrite=overwrite)
        allowed_suffixes = {"png": {".png"}, "jpeg": {".jpg", ".jpeg"}}
        if output.suffix.lower() not in allowed_suffixes[output_format]:
            raise invalid_argument(
                "The output file extension must match the requested image format.",
                output_file=output_file,
                image_format=output_format,
            )

        async def work(session: BrowserSession) -> ScreenshotResult:
            page = await session.resolve_target(target_id)
            temporary = self._artifacts.temporary_sibling(output)
            try:
                await page.screenshot(path=str(temporary), full_page=full_page, type=output_format)
                self._artifacts.commit_temporary(temporary, output, overwrite=overwrite)
            except BrowserError:
                temporary.unlink(missing_ok=True)
                raise
            except Exception as exc:
                temporary.unlink(missing_ok=True)
                raise browser_operation_failed("The screenshot could not be captured.") from exc
            return {
                "tab_id": target_id,
                "url": page.url or "",
                "artifact": self._artifacts.artifact_metadata(
                    output,
                    media_type="image/png" if output_format == "png" else "image/jpeg",
                ),
            }
        return await self._tab_operation(work, dialog_decision=None, can_decide=False)

    async def dom_snapshot(
        self,
        *,
        tab_id: str,
        include_non_interactive: bool = False,
        include_bounding_boxes: bool = True,
        max_elements: int = 200,
        output_file: str | None = None,
        overwrite: bool = False,
    ) -> DomSnapshotResult:
        target_id = validate_tab_id(tab_id)
        self._validate_bool(include_non_interactive, "include_non_interactive")
        self._validate_bool(include_bounding_boxes, "include_bounding_boxes")
        if isinstance(max_elements, bool) or not 1 <= max_elements <= 2_000:
            raise invalid_argument("max_elements must be in range 1..2000.", max_elements=max_elements)

        async def work(session: BrowserSession) -> DomSnapshotResult:
            page = await session.resolve_target(target_id)
            try:
                raw = await page.evaluate(
                    DOM_SNAPSHOT_SCRIPT,
                    {
                        "includeNonInteractive": include_non_interactive,
                        "includeBoundingBoxes": include_bounding_boxes,
                        "maxElements": max_elements,
                    },
                )
            except Exception as exc:
                raise browser_operation_failed("The DOM snapshot could not be captured.") from exc
            snapshot = normalize_snapshot(raw, max_elements=max_elements)
            url = page.url or ""
            if output_file is None:
                return {
                    "tab_id": target_id,
                    "url": url,
                    "output_mode": "inline",
                    **snapshot,
                }
            artifact = self._artifacts.write_json(
                output_file,
                {"tab_id": target_id, "url": url, **snapshot},
                overwrite=overwrite,
            )
            return {
                "tab_id": target_id,
                "url": url,
                "output_mode": "artifact",
                "artifact": artifact,
            }
        return await self._tab_operation(work, dialog_decision=None, can_decide=False)

    async def run_script(
        self,
        *,
        tab_id: str,
        script: str,
        arg: Any | None = None,
        output_file: str | None = None,
        overwrite: bool = False,
        dialog: str | None = None,
        prompt_text: str | None = None,
    ) -> RunScriptResult:
        target_id = validate_tab_id(tab_id)
        decision = validate_dialog_option(dialog, prompt_text)
        normalized = normalize_script(script)
        try:
            dumps_strict(arg)
        except StrictJsonError as exc:
            raise invalid_argument("The script argument must be strict finite JSON.") from exc
        async def work(session: BrowserSession) -> RunScriptResult:
            page = await session.resolve_target(target_id)
            if script_uses_helper(normalized):
                # Same session as the script: install (or keep) the presentation helper first.
                try:
                    await ensure_installed(page)
                except Exception as exc:
                    raise BrowserError(
                        "SCRIPT_FAILED",
                        "The presentation helper could not be installed in the page.",
                        retryable=True,
                        exit_status=5,
                        details={"tab_id": target_id, "detail": "presentation_helper_install_failed"},
                    ) from exc
            try:
                result = await page.evaluate(normalized, arg)
            except Exception as exc:
                raise BrowserError(
                    "SCRIPT_FAILED",
                    "The JavaScript evaluation failed.",
                    retryable=False,
                    exit_status=5,
                    details={"tab_id": target_id},
                ) from exc
            try:
                dumps_strict(result)
            except StrictJsonError as exc:
                raise BrowserError(
                    "SCRIPT_FAILED",
                    "The script result is not strict finite JSON.",
                    retryable=False,
                    exit_status=5,
                ) from exc
            url = page.url or ""
            if output_file is None:
                return {
                    "tab_id": target_id,
                    "url": url,
                    "output_mode": "inline",
                    "result": result,
                }
            artifact = self._artifacts.write_json(
                output_file,
                {"tab_id": target_id, "url": url, "result": result},
                overwrite=overwrite,
            )
            return {
                "tab_id": target_id,
                "url": url,
                "output_mode": "artifact",
                "artifact": artifact,
            }
        return await self._tab_operation(work, dialog_decision=decision, can_decide=True)

    async def start_recording(
        self,
        *,
        tab_id: str,
        output_file: str,
        fps: int = 25,
        overwrite: bool = False,
    ) -> StartRecordingResult:
        """Start recording one tab to MP4 in the background; other operations stay unaffected."""

        target_id = validate_tab_id(tab_id)
        self._validate_bool(overwrite, "overwrite")
        if isinstance(fps, bool) or not isinstance(fps, int) or not MIN_RECORDING_FPS <= fps <= MAX_RECORDING_FPS:
            raise invalid_argument(f"fps must be in range {MIN_RECORDING_FPS}..{MAX_RECORDING_FPS}.", fps=fps)
        output = self._artifacts.resolve_output(output_file, overwrite=overwrite)
        if output.suffix.lower() != ".mp4":
            raise invalid_argument("The recording output file must end in .mp4.", output_file=output_file)
        # Same establishment and tab lookup as every other operation, before the worker starts.
        async with self._runtime.session() as session:
            await session.resolve_page(target_id)
        config = self._runtime.config()
        temporary = self._artifacts.temporary_sibling(output)
        try:
            return await self._recordings.start(
                endpoint=config.endpoint,
                port=config.port,
                tab_id=target_id,
                output=output,
                temp=temporary,
                fps=fps,
                overwrite=overwrite,
            )
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise

    async def stop_recording(self, *, tab_id: str) -> StopRecordingResult:
        """Finish the tab's recording (or report one that already ended) and return the MP4."""

        target_id = validate_tab_id(tab_id)
        return await self._recordings.stop(port=self._runtime.config().port, tab_id=target_id)

    async def _tab_operation(
        self,
        work: Callable[[BrowserSession], Awaitable[ResultT]],
        *,
        dialog_decision: DialogDecision | None,
        can_decide: bool,
    ) -> ResultT:
        """Run one tab operation; report its own tab's dialogs or require a decision for them."""

        dialogs: DialogHandling | None = None
        try:
            async with self._runtime.session(dialog_decision) as session:
                dialogs = session.dialogs
                result = await work(session)
        except BrowserError as exc:
            # A dialog dismissed only to unblock the page explains any failure it caused.
            if dialogs is not None and dialogs.decision_required:
                reports = [report.to_payload() for report in dialogs.reports]
                raise dialog_decision_required(reports, can_decide=can_decide) from exc
            raise
        # Read after disconnect so a dialog raised after the work, before disconnect, is included.
        reports = [report.to_payload() for report in dialogs.reports]
        if dialogs.decision_required:
            raise dialog_decision_required(reports, can_decide=can_decide)
        if reports:
            return {**result, "dialogs": reports}  # type: ignore[return-value]
        return result

    def read_input_text(self, relative_path: str) -> str:
        """Read a CLI-requested source file through the authoritative workspace policy."""

        return self._artifacts.read_text(relative_path)

    @staticmethod
    def _validate_bool(value: bool, name: str) -> None:
        if not isinstance(value, bool):
            raise invalid_argument(f"{name} must be a boolean.")
