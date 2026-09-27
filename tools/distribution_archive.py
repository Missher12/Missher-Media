"""Assemble a reproducible private delivery without local runtime or browser data."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import tempfile
import zipfile

SOURCE_DIRECTORIES = (".github", "runtime", "media-missher", "openclaw-media-missher", "agent-plugin", "harness-plugin", "tools", "tests", "docs", "examples")
SOURCE_FILES = (".gitignore", ".media-missher-source-tree", "VERSION", "LICENSE", "COPYRIGHT.md", "THIRD_PARTY_NOTICES.md", "README.md", "AGENT_INSTALL.md", "DATA_CAPABILITIES.md", "QUICKSTART.md", "PROJECT_CONTEXT.md", "HANDOVER.md", "AGENTS.md", "install.sh", "install.ps1", "Install-Media-Missher-from-GitHub.command")
SKIP = frozenset({"node_modules", "lib", "payload", "dist", ".work", ".git", ".superpowers", ".pytest_cache", "__pycache__", ".DS_Store"})
FORBIDDEN = frozenset({".env", "cookies", "cookies.json", "credentials", "credentials.json", "browser-profile", "chrome-profile", "screenshots", "recovery", "profile.json"})
EPOCH = (2026, 9, 27, 0, 0, 0)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def source_members(root: Path) -> dict[str, tuple[bytes, int]]:
    members: dict[str, tuple[bytes, int]] = {}
    for name in SOURCE_FILES:
        path = root / name
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"source_file_invalid:{name}")
        members[name] = (path.read_bytes(), 0o755 if path.stat().st_mode & 0o111 else 0o644)
    for name in SOURCE_DIRECTORIES:
        for path in sorted((root / name).rglob("*")):
            relative = path.relative_to(root)
            if SKIP.intersection(relative.parts) or path.suffix in {".pyc", ".pyo"}:
                continue
            if path.is_symlink():
                raise ValueError(f"source_symlink_forbidden:{relative}")
            if not path.is_file():
                continue
            if FORBIDDEN.intersection(relative.parts) or path.name.startswith(".env.") or path.name.endswith(".trace.json"):
                raise ValueError(f"source_private_file_forbidden:{relative}")
            members[relative.as_posix()] = (path.read_bytes(), 0o755 if path.stat().st_mode & 0o111 else 0o644)
    return members


def json_bytes(value) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode()


def zip_members(path: Path, prefix: str, members: dict[str, tuple[bytes, int]]) -> None:
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".package-", suffix=".zip") as temporary:
        with zipfile.ZipFile(temporary.name, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for name, (data, mode) in sorted(members.items()):
                info = zipfile.ZipInfo(f"{prefix}/{name}", EPOCH)
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = (0o100000 | mode) << 16
                archive.writestr(info, data)
        path.write_bytes(Path(temporary.name).read_bytes())


def build(root: Path, validation_path: Path | None) -> dict:
    version = (root / "VERSION").read_text().strip()
    output = root / "dist" / f"v{version}"
    output.mkdir(parents=True, exist_ok=True)
    names = {
        "agent": f"missher-media-missher-{version}.tgz",
        "agent_setup": f"Media-Missher-Agent-Setup-v{version}.zip",
        "harness": f"dsh-media-missher-{version}.tgz",
        "source": f"Media-Missher-Source-v{version}.zip",
        "complete": f"Media-Missher-v{version}.zip",
    }
    for key in ("agent", "agent_setup", "harness"):
        if not (output / names[key]).is_file():
            raise ValueError(f"distribution_component_missing:{key}")
    source = source_members(root)
    source_hashes = {name: digest(data) for name, (data, _) in sorted(source.items())}
    source_digest = digest(json_bytes(source_hashes))
    source["SOURCE_MANIFEST.json"] = (json_bytes({"version": version, "files": source_hashes, "sourceTreeSha256": source_digest}), 0o644)
    zip_members(output / names["source"], f"Media-Missher-Source-v{version}", source)
    validation = json.loads(validation_path.read_text()) if validation_path else {"version": version, "status": "not-run", "realPlatformAcceptance": False}
    if validation.get("version") != version:
        raise ValueError("distribution_validation_version_mismatch")
    (output / "VALIDATION.json").write_bytes(json_bytes(validation))
    package = {"version": version, "private": True, "sourceTreeSha256": source_digest, "sourceFileCount": len(source_hashes), "agentPackage": names["agent"], "harnessPackage": names["harness"], "sourcePackage": names["source"], "setupFile": names["agent_setup"], "packageFile": names["agent"], "packageSha256": digest((output / names["agent"]).read_bytes()), "setupSha256": digest((output / names["agent_setup"]).read_bytes()), "runtimeVersion": version, "completePackage": names["complete"], "realPlatformAcceptance": False}
    (output / "PACKAGE.json").write_bytes(json_bytes(package))
    readme = f"""# Media@Missher {version} 私有交付

优先使用 `{names['complete']}`，内含安装说明、字段能力、合成示例、组件包、源码及验证记录。

通用 Agent 使用 `{names['agent_setup']}`；DSH 使用 `{names['harness']}` 及完整包附带的安装器。

先核对 SHA256SUMS.txt。首次安装依赖仍需要包源，当前真实平台采集未在本轮执行。验证范围见 VALIDATION.json。

原有本机安装与旧候选归档未替换。软件与仓库保持私有，见完整包 LICENSE。
"""
    (output / "README.md").write_text(readme)
    delivery: dict[str, tuple[bytes, int]] = {}
    for name in ("LICENSE", "COPYRIGHT.md", "THIRD_PARTY_NOTICES.md", "AGENT_INSTALL.md", "DATA_CAPABILITIES.md", "QUICKSTART.md"):
        delivery[name] = ((root / name).read_bytes(), 0o644)
    for name in ("README.md", "VALIDATION.json", "PACKAGE.json"):
        delivery[name] = ((output / name).read_bytes(), 0o644)
    for key in ("agent_setup", "source"):
        delivery[names[key]] = ((output / names[key]).read_bytes(), 0o644)
    delivery[f"harness-plugin/dist/{names['harness']}"] = ((output / names["harness"]).read_bytes(), 0o644)
    for name in ("README.md", "AGENT.md", "DATA_CAPABILITIES.md", "QUICKSTART.md", "AGENT_INSTALL.md", "scripts/install-current-profile.mjs", "scripts/verify-package.mjs"):
        delivery[f"harness-plugin/{name}"] = ((root / "harness-plugin" / name).read_bytes(), 0o644)
    for path in sorted((root / "examples").iterdir()):
        if not path.is_file() or path.is_symlink():
            raise ValueError("distribution_example_invalid")
        delivery[f"examples/{path.name}"] = (path.read_bytes(), 0o644)
    inner_checksums = "".join(f"{digest(data)}  {name}\n" for name, (data, _) in sorted(delivery.items()))
    delivery["SHA256SUMS.txt"] = (inner_checksums.encode(), 0o644)
    zip_members(output / names["complete"], f"Media-Missher-v{version}", delivery)
    checked = [*names.values(), "PACKAGE.json", "VALIDATION.json", "README.md"]
    (output / "SHA256SUMS.txt").write_text("".join(f"{digest((output / name).read_bytes())}  {name}\n" for name in sorted(checked)))
    return {"version": version, "sourceFiles": len(source_hashes), "sourceTreeSha256": source_digest, "assets": checked}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--validation", type=Path)
    arguments = parser.parse_args()
    print(json.dumps(build(arguments.root.resolve(), arguments.validation), ensure_ascii=False, indent=2))
