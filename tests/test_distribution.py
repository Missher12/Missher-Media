import hashlib
import json
from pathlib import Path
import zipfile

import pytest

from tools.distribution_archive import SOURCE_DIRECTORIES, SOURCE_FILES, build, source_members


def source_tree(tmp_path):
    for name in SOURCE_FILES:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("17.0.0\n" if name == "VERSION" else "Synthetic source\n")
    for name in SOURCE_DIRECTORIES:
        (tmp_path / name).mkdir(exist_ok=True)
    return tmp_path


def test_source_selection_excludes_generated_and_local_evidence(tmp_path):
    root = source_tree(tmp_path)
    (root / "runtime" / "collector.py").write_text("# current source\n")
    for name in [".superpowers/secret.json", "agent-plugin/node_modules/dependency/index.js", "agent-plugin/payload/runtime/copy.py", "harness-plugin/dist/old.tgz", "runtime/__pycache__/compiled.pyc"]:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("excluded")
    selected = source_members(root)
    assert "runtime/collector.py" in selected
    assert not any("excluded" in data.decode() for data, _ in selected.values())


@pytest.mark.parametrize("kind", ["profile", "symlink"])
def test_source_selection_refuses_private_configuration_or_links(tmp_path, kind):
    root = source_tree(tmp_path)
    if kind == "profile":
        (root / "runtime/profile.json").write_text("{}")
    else:
        (root / "runtime/linked.py").symlink_to(root / "VERSION")
    with pytest.raises(ValueError, match="source_(private_file|symlink)_forbidden"):
        source_members(root)


def test_complete_archive_is_repeatable_and_binds_every_source_file(tmp_path):
    root = source_tree(tmp_path)
    package = root / "harness-plugin"
    for name in ["README.md", "AGENT.md", "DATA_CAPABILITIES.md", "QUICKSTART.md", "AGENT_INSTALL.md", "scripts/install-current-profile.mjs", "scripts/verify-package.mjs"]:
        path = package / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("Synthetic component\n")
    (root / "examples/posts.sample.json").write_text('{"synthetic":true}\n')
    output = root / "dist/v17.0.0"
    output.mkdir(parents=True)
    for name in ["missher-media-missher-17.0.0.tgz", "missher-dsh-media-missher-17.0.0.tgz", "Media-Missher-Agent-Setup-v17.0.0.zip"]:
        (output / name).write_bytes(b"synthetic component bytes")
    first = build(root, None)
    checksums = (output / "SHA256SUMS.txt").read_bytes()
    complete = (output / "Media-Missher-v17.0.0.zip").read_bytes()
    second = build(root, None)
    assert first == second
    assert (output / "SHA256SUMS.txt").read_bytes() == checksums
    assert (output / "Media-Missher-v17.0.0.zip").read_bytes() == complete
    with zipfile.ZipFile(output / "Media-Missher-Source-v17.0.0.zip") as archive:
        prefix = "Media-Missher-Source-v17.0.0/"
        manifest = json.loads(archive.read(prefix + "SOURCE_MANIFEST.json"))
        assert manifest["sourceTreeSha256"] == first["sourceTreeSha256"]
        assert not any("/dist/" in name for name in archive.namelist())
        for name, digest in manifest["files"].items():
            assert hashlib.sha256(archive.read(prefix + name)).hexdigest() == digest
