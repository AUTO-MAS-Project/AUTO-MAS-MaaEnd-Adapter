"""回归独立启动进程和并发枚举使用的进程字段。"""

import os
import subprocess
from pathlib import Path

import psutil

from auto_mas_maaend_adapter.auto_proxy import _game_launch_command
from auto_mas_maaend_adapter.tools import game_launcher


def test_launch_command_imports_sdk_in_new_process(tmp_path):
    command = _game_launch_command(
        launcher_path="--help",
        game_path="unused",
        game_arguments="",
    )
    env = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
    env["PYTHONIOENCODING"] = "utf-8"
    result = subprocess.run(
        command,
        cwd=tmp_path,
        env=env,
        capture_output=True,
        timeout=15,
        text=True,
        encoding="utf-8",
    )
    assert result.returncode == 0, result.stderr
    assert "--result-file" in result.stdout


def test_launcher_keeps_process_fields_during_an_overlapping_scan(monkeypatch):
    current = psutil.Process()
    expected = Path(current.exe())
    process_iter = psutil.process_iter
    # psutil 两轮枚举会复用同一 Process 对象。
    list(process_iter())

    def scan_with_overlap(attrs=None):
        candidate = next(
            proc for proc in process_iter(attrs) if proc.pid == current.pid
        )
        next(proc for proc in process_iter(["name"]) if proc.pid == current.pid)
        yield candidate

    monkeypatch.setattr(psutil, "process_iter", scan_with_overlap)
    assert game_launcher._game_running(expected)
