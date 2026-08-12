"""文件整理器的安全回归测试。 / Safety regression tests for the organizer."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "file-organizer-cn" / "scripts" / "file_organizer.py"
SPEC = importlib.util.spec_from_file_location("file_organizer_cn", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class FileOrganizerTests(unittest.TestCase):
    """验证预览、整理和撤销边界。 / Verify preview, organize, and undo boundaries."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.target = Path(self.temporary.name).resolve() / "普通资料"
        self.target.mkdir()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def write_file(self, relative: str, content: bytes = b"test") -> Path:
        """创建测试文件。 / Create a test file."""
        path = self.target / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path

    def test_classification_is_case_insensitive(self) -> None:
        self.assertEqual(MODULE.classify_file(Path("report.PDF")), "PDF")
        self.assertEqual(MODULE.classify_file(Path("photo.JPEG")), "图片")
        self.assertEqual(MODULE.classify_file(Path("unknown.xyz")), "其他")

    def test_preview_performs_zero_writes(self) -> None:
        source = self.write_file("课程报告.docx", b"document")
        before = sorted(str(path.relative_to(self.target)) for path in self.target.rglob("*"))
        plan = MODULE.build_plan(self.target)
        after = sorted(str(path.relative_to(self.target)) for path in self.target.rglob("*"))

        self.assertEqual(before, after)
        self.assertTrue(source.exists())
        self.assertFalse((self.target / MODULE.OUTPUT_DIR_NAME).exists())
        self.assertFalse((self.target / MODULE.STATE_DIR_NAME).exists())
        self.assertEqual(plan["total_files"], 1)
        self.assertEqual(plan["moves"][0]["category"], "文档")

    def test_preview_skips_directories_hidden_temp_and_symlinks(self) -> None:
        self.write_file("普通图片.png")
        self.write_file(".secret.txt")
        self.write_file("video.mp4.crdownload")
        self.write_file("~$报告.docx")
        self.write_file("课程/project.txt")
        link = self.target / "link.txt"
        try:
            link.symlink_to(self.target / "普通图片.png")
        except (OSError, NotImplementedError):
            link = None

        plan = MODULE.build_plan(self.target)
        self.assertEqual([Path(item["source"]).name for item in plan["moves"]], ["普通图片.png"])
        reasons = {Path(item["path"]).name: item["reason"] for item in plan["skipped"]}
        self.assertEqual(reasons[".secret.txt"], "隐藏或系统文件")
        self.assertEqual(reasons["video.mp4.crdownload"], "临时或未下载完成")
        self.assertEqual(reasons["~$报告.docx"], "锁文件")
        self.assertEqual(reasons["课程"], "已有子文件夹")
        if link is not None:
            self.assertEqual(reasons["link.txt"], "符号链接")

    def test_organize_requires_confirmation(self) -> None:
        self.write_file("report.pdf")
        with self.assertRaises(MODULE.OrganizerError):
            MODULE.organize(self.target, confirmed=False)
        self.assertTrue((self.target / "report.pdf").exists())

    def test_organize_renames_conflicts_and_writes_manifest(self) -> None:
        self.write_file("照片.jpg", b"new")
        existing = self.write_file("已整理/图片/照片.jpg", b"existing")

        result = MODULE.organize(self.target, confirmed=True)

        self.assertEqual(result["moved_count"], 1)
        self.assertEqual(existing.read_bytes(), b"existing")
        renamed = self.target / "已整理" / "图片" / "照片 (1).jpg"
        self.assertEqual(renamed.read_bytes(), b"new")
        manifest = Path(result["manifest"])
        self.assertTrue(manifest.exists())
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        self.assertEqual(payload["moves"][0]["destination"], str(renamed))
        self.assertEqual(payload["moves"][0]["state"], "moved")

    def test_undo_restores_latest_run(self) -> None:
        original = self.write_file("作业.pdf", b"homework")
        organize_result = MODULE.organize(self.target, confirmed=True)
        moved = self.target / "已整理" / "PDF" / "作业.pdf"
        self.assertFalse(original.exists())
        self.assertTrue(moved.exists())

        undo_result = MODULE.undo(self.target, confirmed=True)

        self.assertEqual(undo_result["restored_count"], 1)
        self.assertEqual(original.read_bytes(), b"homework")
        self.assertFalse(moved.exists())
        payload = json.loads(Path(organize_result["manifest"]).read_text(encoding="utf-8"))
        self.assertEqual(payload["moves"][0]["state"], "restored")

    def test_undo_never_overwrites_new_file(self) -> None:
        original = self.write_file("总结.txt", b"old")
        MODULE.organize(self.target, confirmed=True)
        original.write_bytes(b"new")

        result = MODULE.undo(self.target, confirmed=True)

        self.assertEqual(result["restored_count"], 0)
        self.assertEqual(result["conflict_count"], 1)
        self.assertEqual(original.read_bytes(), b"new")
        self.assertEqual((self.target / "已整理" / "文档" / "总结.txt").read_bytes(), b"old")

        original.unlink()
        retry = MODULE.undo(self.target, confirmed=True)
        self.assertEqual(retry["restored_count"], 1)
        self.assertEqual(original.read_bytes(), b"old")

    def test_large_file_scan_is_read_only(self) -> None:
        large = self.write_file("素材/video.bin", b"x" * 2048)
        before = large.read_bytes()

        result = MODULE.find_large_files(self.target, min_size_mb=0.001, limit=10)

        self.assertEqual(result["total_files"], 1)
        self.assertEqual(Path(result["files"][0]["path"]), large)
        self.assertEqual(large.read_bytes(), before)

    def test_rejects_home_root_and_project_root(self) -> None:
        with self.assertRaises(MODULE.OrganizerError):
            MODULE.validate_target(Path.home().resolve())

        self.write_file("package.json", b"{}")
        (self.target / "src").mkdir()
        with self.assertRaises(MODULE.OrganizerError):
            MODULE.validate_target(self.target)

    def test_rejects_symlinked_output_or_state_directories(self) -> None:
        outside = Path(self.temporary.name).resolve() / "outside"
        outside.mkdir()
        self.write_file("素材.png")
        output_link = self.target / MODULE.OUTPUT_DIR_NAME
        try:
            output_link.symlink_to(outside, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("当前系统不允许创建目录符号链接")

        with self.assertRaises(MODULE.OrganizerError):
            MODULE.organize(self.target, confirmed=True)
        self.assertEqual(list(outside.iterdir()), [])

    def test_cli_preview_organize_history_and_undo(self) -> None:
        source = self.write_file("口播脚本.txt", b"script")

        preview = subprocess.run(
            [sys.executable, "-X", "utf8", str(SCRIPT), "preview", str(self.target), "--json"],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        self.assertEqual(json.loads(preview.stdout)["total_files"], 1)
        self.assertTrue(source.exists())

        execute = subprocess.run(
            [
                sys.executable, "-X", "utf8", str(SCRIPT), "organize", str(self.target),
                "--confirm", "--json",
            ],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        self.assertEqual(json.loads(execute.stdout)["moved_count"], 1)

        history = subprocess.run(
            [sys.executable, "-X", "utf8", str(SCRIPT), "history", str(self.target), "--json"],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        self.assertEqual(len(json.loads(history.stdout)["history"]), 1)

        reverse = subprocess.run(
            [
                sys.executable, "-X", "utf8", str(SCRIPT), "undo", str(self.target),
                "--confirm", "--json",
            ],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        self.assertEqual(json.loads(reverse.stdout)["restored_count"], 1)
        self.assertEqual(source.read_bytes(), b"script")


if __name__ == "__main__":
    unittest.main()
