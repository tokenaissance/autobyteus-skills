from __future__ import annotations

import re
import tomllib

import pytest

from .support import PROJECT_ROOT


pytestmark = pytest.mark.integration


def test_skill_resolves_only_its_relative_launcher_from_the_advertised_file() -> None:
    skill_path = PROJECT_ROOT / "SKILL.md"
    skill = skill_path.read_text(encoding="utf-8")
    launcher_reference = "scripts/browser"

    assert PROJECT_ROOT.name == "browser-automation"
    assert skill.startswith(
        "---\n"
        "name: browser-automation\n"
        "description: Operate a local Chrome/Chromium session through the bundled browser CLI "
    )
    assert "# Browser Automation" in skill

    launcher_mentions = re.findall(r"`(scripts/[^`]+)`", skill)
    assert launcher_mentions
    assert set(launcher_mentions) == {launcher_reference}
    resolved_launcher = skill_path.parent / launcher_reference
    assert resolved_launcher.is_file()
    assert resolved_launcher.stat().st_mode & 0o111

    assert "exact path of this `SKILL.md` that the runtime advertised and that you read" in skill
    assert "directory containing that exact file" in skill
    assert "current task workspace" in skill
    assert "invoke the resolved launcher with Bash" in skill
    assert "Keep the task workspace as the shell working directory for every call" in skill
    assert "do not depend on a persistent shell variable or other shell state" in skill

    for rejected_public_prerequisite in (
        "SKILL_DIR",
        "BROWSER_CLI",
        "$CODEX_HOME",
        ".codex/skills",
        ".claude/skills",
        "/Users/",
        "/home/",
        "~/",
    ):
        assert rejected_public_prerequisite not in skill

    assert "unsupported rather than guessing or scanning" in skill
    assert "Do not use a vendor-specific skill home, register a PATH command, change into the skill bundle" in skill
    assert "activate an environment, or invoke Python/uv directly" in skill
    assert not re.search(r"(?m)^\s*(?:export\s+)?[A-Z][A-Z0-9_]*=", skill)
    assert not re.search(r"(?m)^\s*(?:\$\s*)?cd(?:\s|$)", skill)

    assert "run_script(tab_id, script, arg)" in skill
    assert "--script '(arg) => ({title: document.title, label: arg.label})'" in skill
    assert "--arg-json '{\"label\":\"direct\"}'" in skill
    assert "optional when the content already exists" in skill
    assert "Do not choose an alternate source merely because JavaScript is nontrivial" in skill
    assert "Prefer a workspace-relative `--script-file`" not in skill

    metadata = (PROJECT_ROOT / "agents" / "openai.yaml").read_text(encoding="utf-8")
    assert 'display_name: "Browser Automation"' in metadata
    assert 'short_description: "Automate explicit tabs in a live Chrome session"' in metadata
    assert 'default_prompt: "Use $browser-automation to inspect and operate the relevant Chrome tab safely."' in metadata


def test_bundle_and_package_publish_only_the_generic_entrypoints() -> None:
    project = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert project["project"]["name"] == "browser-automation"
    assert project["project"]["scripts"] == {
        "browser": "browser_automation.cli:main",
        "browser-mcp-server": "browser_automation.mcp.server:main",
    }

    assert {path.name for path in (PROJECT_ROOT / "scripts").iterdir()} == {"browser", "browser-mcp"}
    source_packages = {
        path.name
        for path in (PROJECT_ROOT / "src").iterdir()
        if path.is_dir() and not path.name.endswith(".egg-info") and path.name != "__pycache__"
    }
    assert source_packages == {"browser_automation"}

    runtime_path = PROJECT_ROOT / "src" / "browser_automation" / "runtime"
    assert {path.name for path in runtime_path.iterdir() if path.suffix == ".py"} == {
        "__init__.py",
        "config.py",
        "chrome_launcher.py",
        "session.py",
    }
    assert not (PROJECT_ROOT / "src" / "browser_automation" / "runtime.py").exists()

    removed_distribution = "brui" + "-core"
    removed_namespace = "brui" + "_core"
    active_runtime_files = [
        PROJECT_ROOT / "pyproject.toml",
        PROJECT_ROOT / "uv.lock",
        *sorted((PROJECT_ROOT / "src").rglob("*.py")),
    ]
    for path in active_runtime_files:
        content = path.read_text(encoding="utf-8")
        assert removed_distribution not in content.lower(), path
        assert removed_namespace not in content.lower(), path
