from __future__ import annotations

from pathlib import Path
import json
import time

import pytest

from .conftest import LocalSite
from .support import LiveChrome, run_cli


pytestmark = [pytest.mark.integration, pytest.mark.real_chrome]


def _script(tmp_path: Path, environment: dict[str, str], tab_id: str, script: str, *extra: str):
    result = run_cli(tmp_path, environment, "run-script", "--tab-id", tab_id, "--script", script, *extra)
    assert result.returncode == 0, (result.stderr.decode(errors="replace"), result.payload)
    return result.payload["result"]["result"]


def _open_demo(live_chrome: LiveChrome, test_site: LocalSite, tmp_path: Path) -> tuple[dict[str, str], str]:
    environment = live_chrome.environment(tmp_path)
    opened = run_cli(tmp_path, environment, "open-tab", "--url", test_site.url("/demo"))
    assert opened.returncode == 0, opened.payload
    return environment, opened.payload["result"]["tab_id"]


def test_helper_is_installed_on_use_only_and_survives_reload(
    live_chrome: LiveChrome, test_site: LocalSite, tmp_path: Path
) -> None:
    environment, tab_id = _open_demo(live_chrome, test_site, tmp_path)

    # The probe must not name the helper global itself: mentioning it is what triggers installation.
    probe = "({ helper: typeof window['__ab' + 'Demo'], root: document.getElementById('__ab-demo-root') === null })"
    untouched = _script(tmp_path, environment, tab_id, probe)
    assert untouched == {"helper": "undefined", "root": True}

    status = _script(tmp_path, environment, tab_id, "__abDemo.status()")
    assert status["installed"] is True and status["presentation"] is True

    navigated = run_cli(tmp_path, environment, "navigate", "--tab-id", tab_id, "--url", test_site.url("/demo"))
    assert navigated.returncode == 0
    assert _script(tmp_path, environment, tab_id, probe)["helper"] == "undefined"
    assert _script(tmp_path, environment, tab_id, "__abDemo.status().installed") is True

    assert _script(tmp_path, environment, tab_id, "async (arg) => arg.x * 2", "--arg-json", json.dumps({"x": 21})) == 42
    assert _script(tmp_path, environment, tab_id, "async arg => arg.x", "--arg-json", json.dumps({"x": 7})) == 7


def test_helper_actions_by_selector_and_text(
    live_chrome: LiveChrome, test_site: LocalSite, tmp_path: Path
) -> None:
    environment, tab_id = _open_demo(live_chrome, test_site, tmp_path)
    results = _script(tmp_path, environment, tab_id, """async () => {
      await __abDemo.setPresentation(false);
      const r = {};
      r.click = await __abDemo.click({ text: 'Save' });
      r.wait = await __abDemo.waitFor({ text: 'Saved' }, { timeoutMs: 3000 });
      r.aria = await __abDemo.click({ text: 'Close dialog' });
      r.nth = await __abDemo.click({ text: 'Duplicate', nth: 1 });
      r.type = await __abDemo.type({ selector: '#agent-name' }, 'My Agent');
      r.textarea = await __abDemo.type({ selector: '#notes' }, 'line');
      r.append = await __abDemo.type({ selector: '#notes' }, ' two', { clear: false });
      r.editor = await __abDemo.type({ selector: '#editor' }, 'rich');
      r.press = await __abDemo.press('k', { meta: true });
      r.hover = await __abDemo.hover({ text: 'Hover me' });
      r.select = await __abDemo.select({ selector: '#runtime' }, { label: 'Codex' });
      r.scroll = await __abDemo.scroll({ selector: '#scroller' }, { y: 300 });
      r.wrapped = await __abDemo.hover({ text: 'Wrapped label' });
      r.state = {
        events: window.events,
        name: document.getElementById('agent-name').value,
        notes: document.getElementById('notes').value,
        editor: document.getElementById('editor').textContent,
        runtime: document.getElementById('runtime').value,
        scrollTop: document.getElementById('scroller').scrollTop,
      };
      return r;
    }""")
    for key in ("click", "wait", "aria", "nth", "type", "textarea", "append", "editor", "press", "hover", "select", "scroll", "wrapped"):
        assert results[key]["ok"] is True, (key, results[key])
    state = results["state"]
    assert state["events"][:3] == ["save", "close", "dup1"]
    assert "change:My Agent" in state["events"]
    assert "key:k+meta" in state["events"]
    assert "hover" in state["events"]
    assert state["name"] == "My Agent"
    assert state["notes"] == "line two"
    assert state["editor"] == "rich"
    assert state["runtime"] == "c"
    assert state["scrollTop"] == 300
    assert results["select"]["label"] == "Codex"


def test_helper_errors_are_structured_values(
    live_chrome: LiveChrome, test_site: LocalSite, tmp_path: Path
) -> None:
    environment, tab_id = _open_demo(live_chrome, test_site, tmp_path)
    results = _script(tmp_path, environment, tab_id, """async () => ({
      ambiguous: await __abDemo.click({ text: 'Duplicate' }),
      missing: await __abDemo.click({ text: 'Nope' }),
      disabled: await __abDemo.click({ text: 'Disabled action' }),
      bare: await __abDemo.click('Save'),
      both: await __abDemo.click({ text: 'Save', selector: '#save' }),
      badSelector: await __abDemo.click({ selector: '##' }),
      notEditable: await __abDemo.type({ selector: '#save' }, 'x'),
      timeout: await __abDemo.waitFor({ text: 'Never' }, { timeoutMs: 200 }),
      events: window.events,
    })""")
    assert results["ambiguous"]["error"]["code"] == "AMBIGUOUS"
    assert len(results["ambiguous"]["error"]["candidates"]) == 2
    assert results["missing"]["error"]["code"] == "NOT_FOUND"
    assert results["disabled"]["error"]["code"] == "NOT_FOUND"
    assert results["bare"]["error"]["code"] == "INVALID_TARGET"
    assert results["both"]["error"]["code"] == "INVALID_TARGET"
    assert results["badSelector"]["error"]["code"] == "INVALID_TARGET"
    assert results["notEditable"]["error"]["code"] == "NOT_EDITABLE"
    assert results["timeout"]["error"]["code"] == "TIMEOUT"
    assert all(result["ok"] is False for key, result in results.items() if key != "events")
    assert results["events"] == []


def test_presentation_overlays_are_transient_and_never_block(
    live_chrome: LiveChrome, test_site: LocalSite, tmp_path: Path
) -> None:
    environment, tab_id = _open_demo(live_chrome, test_site, tmp_path)
    during = _script(tmp_path, environment, tab_id, """async () => {
      await __abDemo.click({ text: 'Save' });
      await __abDemo.caption('Create your first agent', { position: 'bottom' });
      await __abDemo.highlight({ selector: '#agent-name' }, { durationMs: 200 });
      const root = document.getElementById('__ab-demo-root');
      return {
        pointerEvents: getComputedStyle(root).pointerEvents,
        cursor: root.querySelectorAll('[data-ab-demo="cursor"]').length,
        caption: root.querySelector('[data-ab-demo="caption"]').textContent,
        highlight: root.querySelectorAll('[data-ab-demo="highlight"]').length,
        topElementIsSave: document.elementFromPoint(
          document.getElementById('save').getBoundingClientRect().left + 3,
          document.getElementById('save').getBoundingClientRect().top + 3,
        ).id,
      };
    }""")
    assert during == {
        "pointerEvents": "none",
        "cursor": 1,
        "caption": "Create your first agent",
        "highlight": 1,
        "topElementIsSave": "save",
    }
    time.sleep(0.9)
    after = _script(tmp_path, environment, tab_id, """() => {
      __abDemo.hideCaption();
      const root = document.getElementById('__ab-demo-root');
      return ['click', 'caption', 'highlight', 'cursor'].map((kind) => root.querySelectorAll(`[data-ab-demo="${kind}"]`).length);
    }""")
    assert after == [0, 0, 0, 1]


def test_targets_are_hit_tested_like_a_person_with_an_open_modal(
    live_chrome: LiveChrome, test_site: LocalSite, tmp_path: Path
) -> None:
    environment, tab_id = _open_demo(live_chrome, test_site, tmp_path)
    results = _script(tmp_path, environment, tab_id, """async () => {
      await __abDemo.setPresentation(false);
      const r = {};
      r.background = await __abDemo.click({ text: 'Cancel' });
      await __abDemo.click({ text: 'Open modal' });
      r.coveredText = await __abDemo.click({ text: 'Save' });
      r.coveredSelector = await __abDemo.click({ selector: '#save' });
      r.modal = await __abDemo.click({ text: 'Cancel' });
      r.far = await __abDemo.click({ text: 'Far away' });
      r.events = window.events;
      return r;
    }""")
    assert results["background"]["ok"] is True
    for key in ("coveredText", "coveredSelector"):
        assert results[key]["ok"] is False
        assert results[key]["error"]["code"] == "OBSCURED"
        assert results[key]["error"]["covering"]["tag"] == "div"
    assert results["modal"]["ok"] is True
    assert results["far"]["ok"] is True
    assert results["events"] == ["bg-cancel", "modal-cancel", "far"]
