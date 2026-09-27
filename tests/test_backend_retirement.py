from pathlib import Path
import pytest
from runtime.media_missher_runtime.contracts import normalize_backend,ContractError
ROOT=Path(__file__).resolve().parents[1]


def test_no_executable_browserskill_payload_remains():
    for name in ['browser_skill.py','bsk_session.py','bsk_page.py','computer_use.py']:
        assert not (ROOT/'runtime/media_missher_runtime'/name).exists()
    cli=(ROOT/'runtime/media_missher_runtime/cli.py').read_text()
    assert 'class BrowserSkillDispatcher' not in cli
    archive=(ROOT/'agent-plugin/scripts/archive.mjs').read_text()
    assert "'bsk_session'" not in archive and "'browser_skill'" not in archive


def test_retired_request_is_refused_before_optional_driver_import(monkeypatch):
    import builtins
    original=builtins.__import__
    def checked(name,*args,**kwargs):
        if 'bsk_session' in name or 'browser_skill' in name:pytest.fail('retired driver imported')
        return original(name,*args,**kwargs)
    monkeypatch.setattr(builtins,'__import__',checked)
    with pytest.raises(ContractError,match='backend-retired-browserskill'):normalize_backend('browserskill')


def test_public_help_offers_only_chrome_cdp(capsys):
    import run_collection
    from runtime.media_missher_runtime.cli import build_parser
    pages = [run_collection.build_parser().format_help()]
    for command in ('creator', 'search'):
        with pytest.raises(SystemExit) as stopped:
            build_parser().parse_args([command, '--help'])
        assert stopped.value.code == 0
        pages.append(capsys.readouterr().out)
    for help_text in pages:
        assert '--backend' in help_text
        assert 'Chrome CDP' in help_text
        assert '--browser-assist' not in help_text
        assert 'browserskill' not in help_text
        assert 'computer_use' not in help_text
