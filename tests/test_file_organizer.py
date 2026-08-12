"""文件整理器的安全回归测试。 / Safety regression tests for the organizer."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


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
        self.assertEqual(len(plan["plan_id"]), 16)
        self.assertEqual(plan["excluded_categories"], ["代码与数据", "其他"])

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
        plan = MODULE.build_plan(self.target)
        with self.assertRaises(MODULE.OrganizerError):
            MODULE.organize(self.target, confirmed=False, plan_id=plan["plan_id"])
        self.assertTrue((self.target / "report.pdf").exists())

    def test_organize_requires_matching_preview_plan(self) -> None:
        source = self.write_file("report.pdf", b"v1")
        plan = MODULE.build_plan(self.target)

        with self.assertRaises(MODULE.OrganizerError):
            MODULE.organize(self.target, confirmed=True)

        source.write_bytes(b"v2 changed")
        with self.assertRaises(MODULE.OrganizerError):
            MODULE.organize(self.target, confirmed=True, plan_id=plan["plan_id"])
        self.assertTrue(source.exists())

    def test_stale_plan_rejects_destination_created_after_preview(self) -> None:
        source = self.write_file("海报.png", b"new")
        plan = MODULE.build_plan(self.target)
        destination = Path(plan["moves"][0]["destination"])
        destination.parent.mkdir(parents=True)
        destination.write_bytes(b"arrived later")

        with self.assertRaises(MODULE.OrganizerError):
            MODULE.organize(self.target, confirmed=True, plan_id=plan["plan_id"])

        self.assertEqual(source.read_bytes(), b"new")
        self.assertEqual(destination.read_bytes(), b"arrived later")
        self.assertFalse((destination.parent / "海报 (1).png").exists())

    def test_execution_race_does_not_change_planned_destination(self) -> None:
        source = self.write_file("海报.png", b"new")
        plan = MODULE.build_plan(self.target)
        destination = Path(plan["moves"][0]["destination"])
        original_managed_directory = MODULE._managed_directory
        injected = False

        def create_racing_file(path: Path, target: Path, create: bool):
            """模拟校验后目标被占用。 / Simulate a destination occupied after validation."""
            nonlocal injected
            result = original_managed_directory(path, target, create)
            if path.name == "图片" and create and not injected:
                destination.write_bytes(b"arrived during execution")
                injected = True
            return result

        with mock.patch.object(MODULE, "_managed_directory", side_effect=create_racing_file):
            result = MODULE.organize(self.target, confirmed=True, plan_id=plan["plan_id"])

        self.assertEqual(result["moved_count"], 0)
        self.assertEqual(result["failed_count"], 1)
        self.assertEqual(source.read_bytes(), b"new")
        self.assertEqual(destination.read_bytes(), b"arrived during execution")
        self.assertFalse((destination.parent / "海报 (1).png").exists())

    def test_organize_renames_conflicts_and_writes_manifest(self) -> None:
        self.write_file("照片.jpg", b"new")
        existing = self.write_file("已整理/图片/照片.jpg", b"existing")
        plan = MODULE.build_plan(self.target)

        result = MODULE.organize(self.target, confirmed=True, plan_id=plan["plan_id"])

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
        plan = MODULE.build_plan(self.target)
        organize_result = MODULE.organize(self.target, confirmed=True, plan_id=plan["plan_id"])
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
        plan = MODULE.build_plan(self.target)
        MODULE.organize(self.target, confirmed=True, plan_id=plan["plan_id"])
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
            plan = MODULE.build_plan(self.target)
            MODULE.organize(self.target, confirmed=True, plan_id=plan["plan_id"])
        self.assertEqual(list(outside.iterdir()), [])

    def test_safe_mode_skips_code_and_unknown_files(self) -> None:
        self.write_file("文案.docx")
        self.write_file("脚本.py")
        self.write_file("模型.unknown")

        safe_plan = MODULE.build_plan(self.target)
        self.assertEqual([Path(item["source"]).name for item in safe_plan["moves"]], ["文案.docx"])
        skipped = {Path(item["path"]).name: item["reason"] for item in safe_plan["skipped"]}
        self.assertEqual(skipped["脚本.py"], "安全模式排除分类：代码与数据")
        self.assertEqual(skipped["模型.unknown"], "安全模式排除分类：其他")

        all_categories = MODULE.normalize_excluded_categories([], include_risky=True)
        full_plan = MODULE.build_plan(self.target, all_categories)
        self.assertEqual(full_plan["total_files"], 3)

    def test_html_report_hides_names_and_never_overwrites(self) -> None:
        self.write_file("客户名单.xlsx", b"private")
        report_path = Path(self.temporary.name) / "preview.html"
        plan = MODULE.build_plan(self.target)

        created = MODULE.render_report(plan, report_path, reveal_names=False)
        report = created.read_text(encoding="utf-8")
        self.assertIn(plan["plan_id"], report)
        self.assertIn("已隐藏文件名 .xlsx", report)
        self.assertNotIn("客户名单", report)
        self.assertNotIn(str(self.target), report)

        with self.assertRaises(MODULE.OrganizerError):
            MODULE.render_report(plan, report_path, reveal_names=False)

        with self.assertRaises(MODULE.OrganizerError):
            MODULE.render_report(plan, self.target / "整理报告.html", reveal_names=False)

    def test_cli_preview_organize_history_and_undo(self) -> None:
        source = self.write_file("口播脚本.txt", b"script")

        preview = subprocess.run(
            [sys.executable, "-X", "utf8", str(SCRIPT), "preview", str(self.target), "--json"],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        preview_payload = json.loads(preview.stdout)
        self.assertEqual(preview_payload["total_files"], 1)
        self.assertTrue(source.exists())

        report_path = Path(self.temporary.name) / "cli-preview.html"
        report = subprocess.run(
            [
                sys.executable, "-X", "utf8", str(SCRIPT), "report", str(self.target),
                "--output", str(report_path), "--json",
            ],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        report_payload = json.loads(report.stdout)
        self.assertEqual(report_payload["plan_id"], preview_payload["plan_id"])
        self.assertTrue(report_path.exists())
        self.assertNotIn("口播脚本", report_path.read_text(encoding="utf-8"))

        execute = subprocess.run(
            [
                sys.executable, "-X", "utf8", str(SCRIPT), "organize", str(self.target),
                "--confirm", "--plan-id", preview_payload["plan_id"], "--json",
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
