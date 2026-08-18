"""Short-lived Playwright connection and browser target-resolution boundary."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from playwright.async_api import async_playwright

from browser_automation.contracts import TabSummary
from browser_automation.errors import BrowserError, browser_unavailable, tab_not_found
from browser_automation.runtime.chrome_launcher import ChromeAvailability, ChromeLauncher
from browser_automation.runtime.config import BrowserRuntimeConfig

logger = logging.getLogger(__name__)

ConfigFactory = Callable[[], BrowserRuntimeConfig]
LauncherFactory = Callable[[BrowserRuntimeConfig], ChromeLauncher]
PlaywrightFactory = Callable[[], Any]
PendingReadyHook = Callable[[ChromeAvailability], Awaitable[None]]


@dataclass(slots=True)
class BrowserSession:
    """One connected first-context view owned by BrowserRuntime."""

    browser: Any
    context: Any

    async def target_id_for_page(self, page: Any) -> str:
        cdp_session = await self.context.new_cdp_session(page)
        try:
            response = await cdp_session.send("Target.getTargetInfo")
        finally:
            await cdp_session.detach()
        target_info = response.get("targetInfo") if isinstance(response, dict) else None
        target_id = target_info.get("targetId") if isinstance(target_info, dict) else None
        if not isinstance(target_id, str) or not target_id:
            raise BrowserError(
                "BROWSER_OPERATION_FAILED",
                "Chrome did not provide an addressable target identifier for the page.",
                retryable=True,
                exit_status=5,
            )
        return target_id

    async def summarize_page(self, page: Any) -> TabSummary:
        target_id = await self.target_id_for_page(page)
        try:
            title = await page.title()
        except Exception:
            title = None
        return {"tab_id": target_id, "url": page.url or "", "title": title}

    async def list_tabs(self) -> list[TabSummary]:
        tabs: list[TabSummary] = []
        for page in list(self.context.pages):
            if page.is_closed():
                continue
            try:
                tabs.append(await self.summarize_page(page))
            except Exception as exc:
                if page.is_closed():
                    logger.debug("A page closed while browser targets were being listed: %s", exc)
                    continue
                raise BrowserError(
                    "BROWSER_OPERATION_FAILED",
                    "Chrome target metadata could not be read for an addressable page.",
                    retryable=True,
                    exit_status=5,
                ) from exc
        return tabs

    async def resolve_page(self, tab_id: str) -> Any:
        for page in list(self.context.pages):
            if page.is_closed():
                continue
            try:
                candidate_id = await self.target_id_for_page(page)
            except Exception:
                continue
            if candidate_id == tab_id:
                return page
        raise tab_not_found(tab_id)


class BrowserRuntime:
    """Own atomic Chrome establishment, connection, target lookup, and disconnect."""

    def __init__(
        self,
        *,
        config_factory: ConfigFactory = BrowserRuntimeConfig.from_environment,
        launcher_factory: LauncherFactory = ChromeLauncher,
        playwright_factory: PlaywrightFactory = async_playwright,
        pending_ready_hook: PendingReadyHook | None = None,
    ) -> None:
        self._config_factory = config_factory
        self._launcher_factory = launcher_factory
        self._playwright_factory = playwright_factory
        self._pending_ready_hook = pending_ready_hook
        self._operation_lock = asyncio.Lock()
        self._last_endpoint: str | None = None

    @property
    def endpoint(self) -> str:
        if self._last_endpoint is not None:
            return self._last_endpoint
        return self._config_factory().endpoint

    @asynccontextmanager
    async def session(self) -> AsyncIterator[BrowserSession]:
        async with self._operation_lock:
            config = self._config_factory()
            self._last_endpoint = config.endpoint
            availability: ChromeAvailability | None = None
            playwright: Any | None = None
            try:
                availability = await self._launcher_factory(config).ensure_available()
                if availability.is_pending_owned and self._pending_ready_hook is not None:
                    await self._pending_ready_hook(availability)
                async with asyncio.timeout(config.establishment_timeout_seconds):
                    playwright = await self._playwright_factory().start()
                    browser = await playwright.chromium.connect_over_cdp(config.endpoint)
                    if not browser.contexts:
                        raise browser_unavailable(
                            "Chrome exposed no browser context at the configured CDP endpoint."
                        )
                    context = browser.contexts[0]
                if availability.is_pending_owned:
                    availability.promote()
            except BaseException as exc:
                cleanup_error = await self._cleanup_failed_start(availability, playwright)
                if isinstance(exc, asyncio.CancelledError):
                    raise
                if cleanup_error is not None:
                    logger.error("Unable to clean up a failed Chrome session start: %s", cleanup_error)
                    raise browser_unavailable(
                        "Chrome startup failed and its owned process group could not be cleaned up."
                    ) from cleanup_error
                if isinstance(exc, BrowserError):
                    raise
                logger.error("Unable to connect to Chrome over CDP: %s", exc)
                raise browser_unavailable() from exc

            try:
                yield BrowserSession(browser=browser, context=context)
            finally:
                await self._disconnect(playwright)

    async def _cleanup_failed_start(
        self,
        availability: ChromeAvailability | None,
        playwright: Any | None,
    ) -> BaseException | None:
        cleanup_error: BaseException | None = None
        if availability is not None and availability.is_pending_owned:
            try:
                await availability.abort()
            except BaseException as exc:
                cleanup_error = exc
        try:
            await self._disconnect(playwright)
        except BaseException as exc:
            cleanup_error = cleanup_error or exc
        return cleanup_error

    async def _disconnect(self, playwright: Any | None) -> None:
        """Stop only the Playwright client; never close Chrome, contexts, or pages."""

        if playwright is None:
            return
        stop_task = asyncio.create_task(playwright.stop())
        cancellation: asyncio.CancelledError | None = None
        while not stop_task.done():
            try:
                await asyncio.shield(stop_task)
            except asyncio.CancelledError as exc:
                cancellation = exc
        try:
            stop_task.result()
        except Exception as exc:
            logger.warning("Failed to cleanly disconnect the Playwright client: %s", exc)
        if cancellation is not None:
            raise cancellation
