"""测试 prune_check.py — 冗余扫描规则。"""

import json
import os
import tempfile
from pathlib import Path

import pytest

from agent_toolkit.pipeline.prune_check import scan


class TestScanEmptyDir:
    """空目录检测。"""

    def test_empty_directory(self, tmp_path: Path):
        empty = tmp_path / "empty_dir"
        empty.mkdir()
        result = scan(tmp_path)
        assert any(r["type"] == "empty_dir" and r["path"] == str(empty) for r in result)

    def test_non_empty_directory_no_empty_report(self, tmp_path: Path):
        (tmp_path / "file.txt").write_text("hello")
        result = scan(tmp_path)
        assert not any(r["type"] == "empty_dir" for r in result)


class TestScanCacheDir:
    """缓存目录检测。"""

    def test_pycache_detected(self, tmp_path: Path):
        pycache = tmp_path / "__pycache__"
        pycache.mkdir()
        (pycache / "foo.cpython-311.pyc").write_text("x")
        result = scan(tmp_path)
        assert any(r["type"] == "cache_dir" and r["path"] == str(pycache) for r in result)

    def test_node_modules_detected(self, tmp_path: Path):
        nm = tmp_path / "node_modules"
        nm.mkdir()
        result = scan(tmp_path)
        assert any(r["type"] == "cache_dir" and r["path"] == str(nm) for r in result)


class TestScanDebugFile:
    """调试/临时文件检测。"""

    @pytest.mark.parametrize("name", [
        "debug.log",
        "tmp.txt",
        "temp_file.py",
        "old_backup.sql",
        "draft.md",
        "demo_script.py",
    ])
    def test_debug_pattern_detected(self, tmp_path: Path, name: str):
        (tmp_path / name).write_text("x")
        result = scan(tmp_path)
        assert any(r["type"] == "debug_file" and name in r["path"] for r in result)

    def test_normal_file_not_detected(self, tmp_path: Path):
        (tmp_path / "main.py").write_text("x")
        result = scan(tmp_path)
        assert not any(r["type"] == "debug_file" for r in result)


class TestScanEmptyFile:
    """空文件检测。"""

    def test_empty_file_detected(self, tmp_path: Path):
        (tmp_path / "empty.py").write_text("")
        result = scan(tmp_path)
        assert any(r["type"] == "empty_file" and "empty.py" in r["path"] for r in result)

    def test_non_empty_file_not_detected(self, tmp_path: Path):
        (tmp_path / "data.txt").write_text("hello")
        result = scan(tmp_path)
        assert not any(r["type"] == "empty_file" for r in result)


class TestScanDuplicateName:
    """同名文件检测。"""

    def test_duplicate_name_detected(self, tmp_path: Path):
        dir_a = tmp_path / "a"
        dir_a.mkdir()
        (dir_a / "utils.py").write_text("x")
        dir_b = tmp_path / "b"
        dir_b.mkdir()
        (dir_b / "utils.py").write_text("y")
        result = scan(tmp_path)
        assert any(r["type"] == "duplicate_name" and "utils.py" in r["path"] for r in result)

    def test_ignored_names_not_reported(self, tmp_path: Path):
        dir_a = tmp_path / "a"
        dir_a.mkdir()
        (dir_a / "__init__.py").write_text("x")
        dir_b = tmp_path / "b"
        dir_b.mkdir()
        (dir_b / "__init__.py").write_text("y")
        result = scan(tmp_path)
        assert not any(r["type"] == "duplicate_name" for r in result)


class TestScanNonExistent:
    """路径不存在。"""

    def test_non_existent_path(self):
        result = scan(Path("/nonexistent/path/12345"))
        assert len(result) == 1
        assert result[0]["type"] == "error"
        assert "nonexistent" in result[0]["path"]
        assert result[0]["reason"] == "路径不存在"


class TestScanGitIgnored:
    """.git 目录应被跳过内部扫描，但本身作为 cache_dir 报告。"""

    def test_git_dir_reported_as_cache(self, tmp_path: Path):
        git = tmp_path / ".git"
        git.mkdir()
        (git / "config").write_text("x")
        result = scan(tmp_path)
        # .git 本身应作为 cache_dir 被报告
        assert any(r["type"] == "cache_dir" and ".git" in r["path"] for r in result)
        # .git 内部文件不应被单独报告
        assert not any(r["path"].endswith("config") for r in result)
