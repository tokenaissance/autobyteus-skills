import os

import pytest

from video_audio.errors import MediaError
from video_audio.json_codec import StrictJsonError, dumps_strict, loads_strict
from video_audio.paths import LegacyPathPolicy, WorkspacePathPolicy


def test_legacy_policy_matches_former_resolve_path(monkeypatch):
    policy = LegacyPathPolicy()
    monkeypatch.delenv("AUTOBYTEUS_AGENT_WORKSPACE", raising=False)
    assert policy.input("a/b.mp4") == "a/b.mp4"
    monkeypatch.setenv("AUTOBYTEUS_AGENT_WORKSPACE", "/ws")
    assert policy.input("a/b.mp4") == os.path.join("/ws", "a/b.mp4")
    assert policy.output("/abs/out.mp4") == "/abs/out.mp4"
    assert policy.input("/etc/anything") == "/etc/anything"  # no confinement, no existence check


def test_workspace_policy_confines_and_protects_outputs(tmp_path):
    (tmp_path / "in.mp4").write_bytes(b"x")
    policy = WorkspacePathPolicy(str(tmp_path))
    assert policy.input("in.mp4") == str(tmp_path / "in.mp4")
    assert policy.output("sub/out.mp4") == str(tmp_path / "sub" / "out.mp4")
    assert (tmp_path / "sub").is_dir()
    with pytest.raises(MediaError) as missing:
        policy.input("nope.mp4")
    assert missing.value.code == "INPUT_NOT_FOUND"
    with pytest.raises(MediaError) as escape:
        policy.output("../out.mp4")
    assert escape.value.code == "ARTIFACT_PATH_REJECTED"
    with pytest.raises(MediaError) as absolute:
        policy.output("/etc/out.mp4")
    assert absolute.value.code == "ARTIFACT_PATH_REJECTED"
    (tmp_path / "exists.mp4").write_bytes(b"x")
    with pytest.raises(MediaError) as exists:
        policy.output("exists.mp4")
    assert exists.value.code == "ARTIFACT_EXISTS"
    assert WorkspacePathPolicy(str(tmp_path), overwrite=True).output("exists.mp4") == str(tmp_path / "exists.mp4")


def test_workspace_policy_rejects_symlink_escape(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "link").symlink_to(outside)
    with pytest.raises(MediaError) as err:
        WorkspacePathPolicy(str(ws)).output("link/out.mp4")
    assert err.value.code == "ARTIFACT_PATH_REJECTED"


def test_strict_json_rejects_non_finite():
    for bad in ("NaN", "Infinity", "1e999", "{"):
        with pytest.raises(StrictJsonError):
            loads_strict(bad)
    with pytest.raises(StrictJsonError):
        dumps_strict(float("nan"))
    assert loads_strict('[{"a": 1}]') == [{"a": 1}]
