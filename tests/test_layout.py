"""迁移基线：模块命名与包结构检查。"""

import re
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1] / "src" / "auto_mas_maaend_adapter"
SNAKE_CASE = re.compile(r"^[a-z][a-z0-9_]*\.py$")


def test_module_names_are_snake_case():
    bad = [
        str(path.relative_to(PACKAGE))
        for path in PACKAGE.rglob("*.py")
        if not SNAKE_CASE.match(path.name) and path.name != "__init__.py"
    ]
    assert bad == []


def test_legacy_entries_are_moved():
    moved = {
        "auto_proxy.py",
        "config_session.py",
        "expander.py",
        "manual_update.py",
        "notifications.py",
        "tools/endfield_launcher.py",
    }
    for name in moved:
        assert (PACKAGE / name).is_file(), name
    for legacy in ("AutoProxy.py", "ScriptConfig.py", "Update.py", "manager.py", "registration.py"):
        assert not (PACKAGE / legacy).exists(), legacy
