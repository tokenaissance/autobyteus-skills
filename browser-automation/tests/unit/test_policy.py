from pathlib import Path

import pytest

from browser_automation.errors import BrowserError
from browser_automation.json_codec import loads_strict
from browser_automation.policy import ArtifactPolicy, validate_timeout, validate_url


def test_url_and_timeout_policy_is_strict() -> None:
    assert validate_url("https://example.com/a") == "https://example.com/a"
    with pytest.raises(BrowserError, match="http") as invalid_scheme:
        validate_url("file:///etc/passwd")
    assert invalid_scheme.value.code == "INVALID_URL"
    with pytest.raises(BrowserError) as invalid_timeout:
        validate_timeout(0)
    assert invalid_timeout.value.code == "INVALID_ARGUMENT"


def test_artifact_policy_confines_and_preserves_workspace(tmp_path: Path) -> None:
    policy = ArtifactPolicy(tmp_path)
    artifact = policy.write_text("artifacts/page.txt", "hello", overwrite=False, media_type="text/plain")
    assert Path(artifact["path"]).read_text() == "hello"
    assert artifact["bytes_written"] == 5

    with pytest.raises(BrowserError) as existing:
        policy.write_text("artifacts/page.txt", "changed", overwrite=False, media_type="text/plain")
    assert existing.value.code == "ARTIFACT_EXISTS"
    assert Path(artifact["path"]).read_text() == "hello"

    for rejected in ("/tmp/out.txt", "../out.txt"):
        with pytest.raises(BrowserError) as error:
            policy.resolve_output(rejected, overwrite=False)
        assert error.value.code == "ARTIFACT_PATH_REJECTED"


@pytest.mark.parametrize("writer_kind", ["bytes", "text", "json"])
def test_no_overwrite_commit_atomically_preserves_an_interleaving_winner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    writer_kind: str,
) -> None:
    policy = ArtifactPolicy(tmp_path)
    relative = f"artifacts/race-{writer_kind}.out"
    output = tmp_path / relative
    original_commit = policy.commit_temporary

    def interleaving_commit(temporary: Path, destination: Path, *, overwrite: bool) -> None:
        assert not destination.exists()
        destination.write_bytes(b"other-process")
        original_commit(temporary, destination, overwrite=overwrite)

    monkeypatch.setattr(policy, "commit_temporary", interleaving_commit)
    with pytest.raises(BrowserError) as collision:
        if writer_kind == "bytes":
            policy.write_bytes(relative, b"this-process", overwrite=False, media_type="application/octet-stream")
        elif writer_kind == "text":
            policy.write_text(relative, "this-process", overwrite=False, media_type="text/plain")
        else:
            policy.write_json(relative, {"writer": "this-process"}, overwrite=False)

    assert collision.value.code == "ARTIFACT_EXISTS"
    assert collision.value.exit_status == 2
    assert output.read_bytes() == b"other-process"
    assert list(output.parent.glob(f".{output.name}.*.tmp")) == []


@pytest.mark.parametrize("writer_kind", ["bytes", "text", "json"])
def test_explicit_overwrite_replaces_existing_generic_artifact(
    tmp_path: Path,
    writer_kind: str,
) -> None:
    policy = ArtifactPolicy(tmp_path)
    relative = f"artifacts/replace-{writer_kind}.out"
    output = tmp_path / relative
    output.parent.mkdir(parents=True)
    output.write_bytes(b"old")

    if writer_kind == "bytes":
        policy.write_bytes(relative, b"new", overwrite=True, media_type="application/octet-stream")
        assert output.read_bytes() == b"new"
    elif writer_kind == "text":
        policy.write_text(relative, "new", overwrite=True, media_type="text/plain")
        assert output.read_text() == "new"
    else:
        policy.write_json(relative, {"value": "new"}, overwrite=True)
        assert loads_strict(output.read_text()) == {"value": "new"}
    assert list(output.parent.glob(f".{output.name}.*.tmp")) == []


@pytest.mark.parametrize("value", [float("nan"), {"nested": [float("inf")]}, -float("inf")])
def test_json_artifact_rejects_non_finite_values_without_leaving_files(tmp_path: Path, value) -> None:
    policy = ArtifactPolicy(tmp_path)
    with pytest.raises(BrowserError) as failure:
        policy.write_json("artifacts/value.json", value, overwrite=False)
    assert failure.value.code == "BROWSER_OPERATION_FAILED"
    assert not (tmp_path / "artifacts/value.json").exists()
    assert list(tmp_path.rglob("*.tmp")) == []


@pytest.mark.parametrize(
    "value",
    [
        "\ud800",
        "\udfff",
        {"nested": ["\ud800"]},
        {"nested": ["\udfff"]},
    ],
)
def test_json_artifact_escapes_lone_surrogates_for_utf8_publication(tmp_path: Path, value) -> None:
    policy = ArtifactPolicy(tmp_path)
    policy.write_json("artifacts/value.json", value, overwrite=False)

    artifact_bytes = (tmp_path / "artifacts/value.json").read_bytes()
    assert loads_strict(artifact_bytes.decode("utf-8", errors="strict")) == value
