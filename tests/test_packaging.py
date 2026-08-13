import os
import re
from pathlib import Path
import subprocess
import sys

import pytest


REPO = Path(__file__).resolve().parents[1]
SKILL = REPO / "media-missher"
RUNTIME_SCRIPTS = REPO / "runtime" / "scripts"
DOCUMENTATION = (
    SKILL / "SKILL.md",
    SKILL / "references" / "configuration.md",
    SKILL / "references" / "commands.md",
    SKILL / "references" / "troubleshooting.md",
    SKILL / "references" / "validation.md",
    SKILL / "references" / "licensing.md",
    REPO / "PROJECT_CONTEXT.md",
)
PACKAGE_ROOTS = (
    REPO / "runtime",
    REPO / "media-missher",
    REPO / "openclaw-media-missher",
)


def parse_skill_frontmatter(text):
    match = re.match(r"\A---\n(?P<header>.*?)\n---\n", text, re.S)
    assert match, "SKILL.md must use exact YAML frontmatter delimiters"
    parsed = {}
    for line in match.group("header").splitlines():
        field = re.fullmatch(r"([a-z_]+):\s+(\S.*)", line)
        assert field, f"invalid frontmatter line: {line!r}"
        key, value = field.groups()
        assert key not in parsed, f"duplicate frontmatter key: {key}"
        parsed[key] = value
    assert set(parsed) == {"name", "description"}
    return parsed


def parse_openai_interface(text):
    assert text.startswith("interface:\n")
    parsed = {}
    for line in text.splitlines()[1:]:
        field = re.fullmatch(r'  ([a-z_]+): "([^"\n]+)"', line)
        assert field, f"invalid openai.yaml line: {line!r}"
        key, value = field.groups()
        assert key not in parsed, f"duplicate interface key: {key}"
        parsed[key] = value
    return parsed


def test_skill_frontmatter_is_codex_compatible():
    text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    frontmatter = parse_skill_frontmatter(text)
    assert frontmatter["name"] == "media-missher"


@pytest.mark.parametrize(
    "text",
    (
        "---\nname: media-missher\ndescription: valid\n--- trailing\n# Body\n",
        "---\nname: media-missher\nname: duplicate\ndescription: valid\n---\n",
        "---\nname: media-missher\ninvalid line\ndescription: valid\n---\n",
        "---\nname: media-missher\ndescription:\n---\n",
    ),
)
def test_skill_frontmatter_rejects_malformed_metadata(text):
    with pytest.raises(AssertionError):
        parse_skill_frontmatter(text)


def test_skill_has_only_allowed_top_level_entries():
    assert {path.name for path in SKILL.iterdir()} == {
        "SKILL.md",
        "agents",
        "scripts",
        "references",
    }
    for directory in ("agents", "scripts", "references"):
        assert (SKILL / directory).is_dir()


def test_openai_metadata_has_required_interface():
    metadata = SKILL / "agents" / "openai.yaml"
    assert metadata.is_file()
    interface = parse_openai_interface(metadata.read_text(encoding="utf-8"))
    assert set(interface) == {
        "display_name",
        "short_description",
        "default_prompt",
    }
    assert all(interface.values())
    assert interface["display_name"] == "Media@Missher V15.2.1"
    assert 25 <= len(interface["short_description"]) <= 64
    assert "$media-missher" in interface["default_prompt"]


def test_skill_contains_no_bundled_engine_or_generated_artifacts():
    forbidden = {
        "engine",
        ".venv",
        "data",
        "__pycache__",
        ".pytest_cache",
        "openclaw.skill.json",
    }
    assert not forbidden.intersection(path.name for path in SKILL.rglob("*"))
    assert all(path.is_file() for path in (SKILL / "scripts").iterdir())


def test_source_packages_contain_no_private_browser_or_runtime_artifacts():
    forbidden_directory_names = {
        ".superpowers",
        "browser-profile",
        "browser_profiles",
        "cookies",
        "recovery",
        "screenshots",
        "state",
    }
    failures = []
    for root in PACKAGE_ROOTS:
        for path in root.rglob("*"):
            relative = path.relative_to(root)
            lowered_parts = {part.casefold() for part in relative.parts}
            if forbidden_directory_names.intersection(lowered_parts):
                failures.append(relative.as_posix())
            if path.is_file() and (
                path.name == ".env"
                or path.name.startswith(".env.")
                or path.name.endswith(".trace.json")
                or path.suffix.casefold() == ".png"
            ):
                failures.append(relative.as_posix())
    assert failures == []


@pytest.mark.parametrize(
    "script_name",
    (
        "scrape_all.py",
        "scrape_bilibili.py",
        "scrape_xhs.py",
        "scrape_douyin.py",
        "scrape_weibo.py",
    ),
)
def test_all_runtime_entrypoint_help_is_offline_and_has_no_removed_root_flag(script_name):
    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    completed = subprocess.run(
        [sys.executable, str(RUNTIME_SCRIPTS / script_name), "--help"],
        check=False,
        capture_output=True,
        text=True,
        timeout=5,
        env=environment,
    )

    assert completed.returncode == 0
    assert "{creator,search}" in completed.stdout
    assert "--engine-root" not in completed.stdout

    creator_help = subprocess.run(
        [sys.executable, str(RUNTIME_SCRIPTS / script_name), "creator", "--help"],
        check=False,
        capture_output=True,
        text=True,
        timeout=5,
        env=environment,
    )
    assert creator_help.returncode == 0
    assert "--allow-navigation" in creator_help.stdout
    assert "--engine-root" not in creator_help.stdout


def test_documentation_covers_shared_runtime_operations_and_recovery():
    corpus = "\n".join(path.read_text(encoding="utf-8") for path in DOCUMENTATION)
    required = (
        "MEDIA_MISSHER_HOME",
        "~/.local/share/media-missher",
        "platform_uids",
        "0600",
        "0700",
        "scrape_all.py",
        "scrape_bilibili.py",
        "scrape_xhs.py",
        "scrape_douyin.py",
        "scrape_weibo.py",
        "scripts/preflight.py",
        "--live",
        "scripts/run_collection.py",
        "--allow-navigation",
        "scripts/validate_run.py",
        "tools/install_media_missher.py",
        "--runtime-only",
        "--codex-only",
        ".media-missher-owner.json",
        ".media-missher-install.lock",
        ".media-missher-release",
        "previous-",
        "timestamp",
        "Trash",
        "risk-stopped",
        "--collect-as-much-as-safe",
        "remote Feishu write",
    )

    for phrase in required:
        assert phrase in corpus, f"documentation is missing {phrase!r}"


def test_validation_documentation_defines_the_strict_five_key_diagnostic_contract():
    text = (SKILL / "references" / "validation.md").read_text(encoding="utf-8")

    assert "`counts`, `paths`, `platforms`, `status`, and `diagnostics`" in text
    assert "exactly `kind` and `code`" in text
    for kind in (
        "ok",
        "result",
        "not-run",
        "dependency",
        "precondition",
        "source-response",
        "risk-stop",
        "timeout",
        "collector-contract",
        "internal",
    ):
        assert f"`{kind}`" in text
    for code in (
        "count-shortfall",
        "incomplete-record",
        "screenshot-shortfall",
        "preflight-aborted",
        "prior-risk-stop",
        "module-not-found",
        "precondition-failed",
        "xhs-browser-assist-unsupported",
        "bsk-missing",
        "bsk-unhealthy",
        "bsk-incompatible",
        "bsk-busy",
        "bsk-transport",
        "bsk-timeout",
        "bsk-target-ambiguous",
        "bsk-session-start",
        "bsk-tab-list",
        "bsk-tab-borrow",
        "bsk-snapshot",
        "bsk-click",
        "bsk-tab-return",
        "bsk-session-stop",
        "source-response-failed",
        "http-403",
        "http-429",
        "payload-461",
        "payload-471",
        "payload-999",
        "challenge",
        "risk-signal",
        "platform-timeout",
        "creator-capture-timeout",
        "detail-capture-timeout",
        "invalid-records",
        "unexpected",
    ):
        assert f"`{code}`" in text


def test_skill_preserves_read_only_requests_and_requires_collection_authorization():
    text = (SKILL / "SKILL.md").read_text(encoding="utf-8")

    assert "Keep code review, audit, explanation, and planning read-only" in text
    assert "Require explicit authorization to collect" in text
    assert "--allow-navigation" in text
    assert "separate explicit authorization" in text


def test_documentation_carries_the_bounded_xhs_detail_action_contract():
    skill = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    commands = (SKILL / "references" / "commands.md").read_text(encoding="utf-8")
    validation = (SKILL / "references" / "validation.md").read_text(
        encoding="utf-8"
    )
    troubleshooting = (SKILL / "references" / "troubleshooting.md").read_text(
        encoding="utf-8"
    )

    assert "at most one Xiaohongshu detail open" in skill
    assert "at most three" in commands
    assert "comment container" in commands
    assert "does not refresh or reopen" in commands
    assert "1,500" in commands
    assert "partial" in validation
    assert "Do not refresh or reopen" in troubleshooting


def test_documentation_records_xhs_cdp_only_browser_ownership():
    skill = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    commands = (SKILL / "references" / "commands.md").read_text(encoding="utf-8")
    configuration = (SKILL / "references" / "configuration.md").read_text(
        encoding="utf-8"
    )
    openclaw = (REPO / "openclaw-media-missher" / "SKILL.md").read_text(
        encoding="utf-8"
    )

    for text in (skill, commands, configuration, openclaw):
        assert "xhs-browser-assist-unsupported" in text
    assert "Xiaohongshu uses Playwright/CDP only" in skill
    assert "BrowserSkill assistance is limited to Bilibili" in commands
    assert "--browser-assist off" in commands


def test_documentation_distinguishes_live_cdp_probe_from_controller_page_preflight():
    corpus = "\n".join(path.read_text(encoding="utf-8") for path in DOCUMENTATION)

    assert "Live preflight probes the existing CDP endpoint" in corpus
    assert (
        "The runtime controller checks each selected platform page and login state "
        "before creating output"
    ) in corpus


def test_project_context_records_clean_boundaries_and_release_state():
    text = (REPO / "PROJECT_CONTEXT.md").read_text(encoding="utf-8")

    assert (REPO / "VERSION").read_text(encoding="ascii") == "15.2.1\n"

    for phrase in (
        "Source boundary",
        "Runtime boundary",
        "Adapter boundary",
        "Live acceptance",
        "Cutover",
        "Current limitations",
        "~/.codex/skills/media-missher",
        "~/.openclaw/workspace/skills/media-missher",
    ):
        assert phrase in text


def test_v15_docs_cover_assist_screenshot_and_unverified_live_boundary():
    corpus = "\n".join(path.read_text(encoding="utf-8") for path in DOCUMENTATION)
    codex_skill = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    openclaw_skill = (REPO / "openclaw-media-missher" / "SKILL.md").read_text(
        encoding="utf-8"
    )

    assert "# Media@Missher V15.2.1" in codex_skill
    assert "# Media@Missher V15.2.1" in openclaw_skill
    for phrase in (
        "--browser-assist",
        "--screenshot-mode",
        "BrowserSkill 0.1.10",
        "extension 0.1.6",
        "Playwright/CDP",
        "article",
        "full_page_fallback",
        "screenshot_path",
        "screenshot_sha256",
        "screenshot_observed_at",
        "private GitHub",
        "V15 Xiaohongshu live acceptance passed",
    ):
        assert phrase in corpus, f"V15 documentation is missing {phrase!r}"
    assert "defaults to `off`" in corpus
    assert "bundled skill sync" in corpus
    assert "positive count" in corpus


def test_gitignore_keeps_private_v15_artifacts_out_of_source_control():
    lines = set((REPO / ".gitignore").read_text(encoding="utf-8").splitlines())
    assert {
        ".superpowers/",
        ".env",
        ".env.*",
        "*.trace.json",
        "screenshots/",
        "run-*/screenshots/",
    }.issubset(lines)


def test_offline_ci_has_no_live_browser_or_artifact_upload_configuration():
    workflow = REPO / ".github" / "workflows" / "ci.yml"
    text = workflow.read_text(encoding="utf-8")

    assert "--disable-socket" in text
    assert "--allow-unix-socket" in text
    assert "--with-requirements runtime/requirements.lock" in text
    assert "--with playwright" not in text
    assert "compileall" in text
    assert "scan_active_residuals.py" in text
    for entrypoint in (
        "scrape_all.py",
        "scrape_bilibili.py",
        "scrape_xhs.py",
        "scrape_douyin.py",
        "scrape_weibo.py",
    ):
        assert f"{entrypoint} --help" in text
    lowered = text.casefold()
    for forbidden in (
        "secrets.",
        "services:",
        "upload-artifact",
        "screenshot upload",
        "cdp_url",
        "bsk session start",
    ):
        assert forbidden not in lowered
