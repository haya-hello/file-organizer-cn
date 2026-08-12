#!/usr/bin/env python3
"""跨平台、安全优先的文件整理工具。 / Cross-platform, safety-first file organizer."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import stat
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional


VERSION = "1.0.0"
STATE_DIR_NAME = ".file-organizer-cn"
OUTPUT_DIR_NAME = "已整理"

CATEGORIES: dict[str, set[str]] = {
    "文档": {".doc", ".docx", ".txt", ".md", ".rtf", ".odt", ".pages"},
    "表格": {".xls", ".xlsx", ".csv", ".numbers", ".ods", ".tsv"},
    "演示文稿": {".ppt", ".pptx", ".key", ".odp"},
    "PDF": {".pdf"},
    "图片": {
        ".jpg", ".jpeg", ".png", ".gif", ".webp", ".heic", ".bmp",
        ".tif", ".tiff", ".svg", ".psd", ".ai",
    },
    "视频": {".mp4", ".mov", ".avi", ".mkv", ".wmv", ".flv", ".webm", ".m4v"},
    "音频": {".mp3", ".wav", ".flac", ".aac", ".m4a", ".ogg", ".wma"},
    "压缩包": {".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz", ".zst"},
    "安装包": {".exe", ".msi", ".dmg", ".pkg", ".deb", ".rpm", ".apk", ".appimage"},
    "电子书": {".epub", ".mobi", ".azw3", ".djvu"},
    "字体": {".ttf", ".otf", ".woff", ".woff2", ".eot"},
    "代码与数据": {
        ".py", ".pyw", ".js", ".jsx", ".ts", ".tsx", ".html", ".htm",
        ".css", ".scss", ".less", ".json", ".jsonl", ".yaml", ".yml",
        ".xml", ".toml", ".ini", ".cfg", ".sql", ".ipynb", ".java",
        ".kt", ".kts", ".c", ".h", ".cpp", ".hpp", ".cs", ".go",
        ".rs", ".rb", ".php", ".swift", ".sh", ".ps1", ".bat", ".cmd",
    },
}

TEMP_SUFFIXES = (
    ".part", ".partial", ".crdownload", ".download", ".tmp", ".temp", ".opdownload",
)
SYSTEM_FILENAMES = {"thumbs.db", "desktop.ini", ".ds_store", ".localized"}
PROJECT_MARKERS = {
    "package.json", "pyproject.toml", "cargo.toml", "go.mod", "pom.xml",
    "build.gradle", "composer.json", "gemfile", "cmakelists.txt",
}
PROJECT_DIR_MARKERS = {"src", "app", "lib", "packages"}
VCS_MARKERS = {".git", ".hg", ".svn"}
UNDOABLE_STATES = {"moved", "undo_conflict", "undo_error", "undo_missing"}


class OrganizerError(RuntimeError):
    """用户可处理的整理错误。 / User-actionable organizer error."""


def now_iso() -> str:
    """返回 UTC 时间。 / Return a UTC timestamp."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def format_size(size_bytes: int) -> str:
    """格式化字节数。 / Format a byte count."""
    value = float(size_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TB"


def classify_file(path: Path) -> str:
    """按扩展名分类。 / Classify a file by extension."""
    suffix = path.suffix.lower()
    for category, extensions in CATEGORIES.items():
        if suffix in extensions:
            return category
    return "其他"


def _alias_candidates(alias: str) -> list[Path]:
    """返回常见用户目录候选。 / Return common user-folder candidates."""
    home = Path.home()
    onedrive = os.environ.get("OneDrive") or os.environ.get("OneDriveConsumer")
    bases = [home]
    if onedrive:
        bases.append(Path(onedrive))

    names: dict[str, tuple[str, ...]] = {
        "downloads": ("Downloads", "下载"),
        "desktop": ("Desktop", "桌面"),
        "documents": ("Documents", "文档"),
        "pictures": ("Pictures", "图片"),
    }
    return [base / name for base in bases for name in names[alias]]


def resolve_target(raw_target: str) -> Path:
    """解析目录别名或路径。 / Resolve a folder alias or path."""
    alias_map = {
        "downloads": "downloads", "download": "downloads", "下载": "downloads",
        "下载文件夹": "downloads", "desktop": "desktop", "桌面": "desktop",
        "documents": "documents", "document": "documents", "文档": "documents",
        "pictures": "pictures", "picture": "pictures", "图片": "pictures",
    }
    normalized = raw_target.strip().lower()
    alias = alias_map.get(normalized) or alias_map.get(raw_target.strip())
    if alias:
        candidates = _alias_candidates(alias)
        for candidate in candidates:
            if candidate.is_dir():
                return candidate.resolve()
        tried = "、".join(str(path) for path in candidates)
        raise OrganizerError(f"找不到目录别名 {raw_target!r}。已尝试：{tried}")

    target = Path(raw_target).expanduser()
    try:
        return target.resolve(strict=True)
    except FileNotFoundError as exc:
        raise OrganizerError(f"目标目录不存在：{target}") from exc
    except OSError as exc:
        raise OrganizerError(f"无法解析目标目录：{target}（{exc}）") from exc


def _is_relative_to(path: Path, parent: Path) -> bool:
    """兼容 Python 3.9 的路径包含判断。 / Python 3.9 compatible containment check."""
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _protected_system_paths() -> list[Path]:
    """返回当前系统的受保护目录。 / Return protected system directories."""
    raw_paths: list[str] = []
    if os.name == "nt":
        for key in ("SystemRoot", "ProgramFiles", "ProgramFiles(x86)", "ProgramData"):
            value = os.environ.get(key)
            if value:
                raw_paths.append(value)
    else:
        raw_paths.extend(("/System", "/Library", "/usr", "/etc", "/var", "/bin", "/sbin"))

    paths: list[Path] = []
    for value in raw_paths:
        try:
            path = Path(value).resolve()
        except OSError:
            continue
        if path.exists():
            paths.append(path)
    return paths


def _looks_like_project_root(target: Path) -> bool:
    """识别明显的代码仓库根目录。 / Detect an obvious source-project root."""
    try:
        names = {entry.name.lower() for entry in target.iterdir()}
    except OSError:
        return False
    if names & VCS_MARKERS:
        return True
    marker_count = len(names & PROJECT_MARKERS)
    return marker_count >= 2 or (marker_count >= 1 and bool(names & PROJECT_DIR_MARKERS))


def validate_target(target: Path) -> None:
    """拒绝高风险目录。 / Reject high-risk target directories."""
    if not target.is_dir():
        raise OrganizerError(f"目标不是文件夹：{target}")
    if target.parent == target:
        raise OrganizerError("拒绝整理磁盘根目录。请指定下载、桌面或某个普通文件夹。")

    try:
        home = Path.home().resolve()
    except OSError:
        home = Path.home()
    if target == home:
        raise OrganizerError("拒绝直接整理整个用户主目录。请缩小到下载、桌面或某个子文件夹。")

    for protected in _protected_system_paths():
        if target == protected or _is_relative_to(target, protected):
            raise OrganizerError(f"拒绝整理系统目录：{target}")

    if _looks_like_project_root(target):
        raise OrganizerError("目标看起来是代码仓库根目录。为避免打散项目文件，请改选普通资料文件夹。")


def _windows_hidden_or_system(path: Path) -> bool:
    """识别 Windows 隐藏或系统属性。 / Detect Windows hidden or system attributes."""
    try:
        attributes = path.lstat().st_file_attributes
    except (AttributeError, OSError):
        return False
    return bool(attributes & (stat.FILE_ATTRIBUTE_HIDDEN | stat.FILE_ATTRIBUTE_SYSTEM))


def skip_reason(path: Path) -> Optional[str]:
    """返回跳过原因。 / Return a reason to skip a path."""
    name = path.name
    lower_name = name.lower()
    if path.is_symlink():
        return "符号链接"
    if path.is_dir():
        return "已有子文件夹"
    if not path.is_file():
        return "非普通文件"
    if name.startswith(".") or lower_name in SYSTEM_FILENAMES or _windows_hidden_or_system(path):
        return "隐藏或系统文件"
    if name.startswith("~$") or lower_name.startswith(".~lock."):
        return "锁文件"
    if lower_name.endswith(TEMP_SUFFIXES):
        return "临时或未下载完成"
    return None


def _path_key(path: Path) -> str:
    """生成保守的冲突比较键。 / Build a conservative collision key."""
    return os.path.normcase(str(path)).casefold()


def unique_destination(directory: Path, filename: str, reserved: set[str]) -> Path:
    """生成不覆盖现有文件的目标路径。 / Build a non-overwriting destination path."""
    source_name = Path(filename)
    stem = source_name.stem
    suffix = source_name.suffix
    candidate = directory / filename
    number = 1
    while candidate.exists() or _path_key(candidate) in reserved:
        candidate = directory / f"{stem} ({number}){suffix}"
        number += 1
    reserved.add(_path_key(candidate))
    return candidate


def build_plan(target: Path) -> dict[str, Any]:
    """构建只读整理计划。 / Build a read-only organization plan."""
    validate_target(target)
    output_root = target / OUTPUT_DIR_NAME
    reserved: set[str] = set()
    moves: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []

    try:
        entries = sorted(target.iterdir(), key=lambda path: path.name.casefold())
    except PermissionError as exc:
        raise OrganizerError(f"没有权限读取目标目录：{target}") from exc
    except OSError as exc:
        raise OrganizerError(f"读取目标目录失败：{target}（{exc}）") from exc

    for entry in entries:
        reason = skip_reason(entry)
        if reason:
            skipped.append({"path": str(entry), "reason": reason})
            continue
        category = classify_file(entry)
        destination = unique_destination(output_root / category, entry.name, reserved)
        try:
            size_bytes = entry.lstat().st_size
        except OSError as exc:
            skipped.append({"path": str(entry), "reason": f"无法读取文件信息：{exc}"})
            continue
        moves.append({
            "source": str(entry),
            "destination": str(destination),
            "category": category,
            "size_bytes": size_bytes,
        })

    category_data: dict[str, dict[str, int]] = defaultdict(lambda: {"count": 0, "size_bytes": 0})
    for move in moves:
        category_data[move["category"]]["count"] += 1
        category_data[move["category"]]["size_bytes"] += move["size_bytes"]

    return {
        "action": "preview",
        "target": str(target),
        "output_root": str(output_root),
        "total_files": len(moves),
        "total_size_bytes": sum(move["size_bytes"] for move in moves),
        "categories": dict(sorted(category_data.items())),
        "moves": moves,
        "skipped": skipped,
        "safety": {
            "recursive": False,
            "deletes_files": False,
            "overwrites_files": False,
            "confirmation_required": True,
        },
    }


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    """原子写入 JSON 状态。 / Atomically write JSON state."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def _managed_directory(path: Path, target: Path, create: bool) -> Optional[Path]:
    """校验工具管理目录没有越界。 / Validate that a managed directory stays in bounds."""
    if path.is_symlink():
        raise OrganizerError(f"安全检查失败：管理目录不能是符号链接：{path}")
    if path.exists() and not path.is_dir():
        raise OrganizerError(f"安全检查失败：管理路径已被普通文件占用：{path}")
    if not path.exists():
        if not create:
            return None
        path.mkdir(parents=True, exist_ok=False)
    resolved = path.resolve()
    if not _is_relative_to(resolved, target):
        raise OrganizerError(f"安全检查失败：管理目录超出目标文件夹：{path}")
    return resolved


def _manifest_path(target: Path) -> Path:
    """生成唯一历史记录路径。 / Build a unique history path."""
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    state_dir = _managed_directory(target / STATE_DIR_NAME, target, create=True)
    assert state_dir is not None
    history_dir = _managed_directory(state_dir / "history", target, create=True)
    assert history_dir is not None
    return history_dir / f"{stamp}.json"


def organize(target: Path, confirmed: bool) -> dict[str, Any]:
    """执行带记录的整理。 / Execute a journaled organization run."""
    if not confirmed:
        raise OrganizerError("正式整理必须显式添加 --confirm；请先运行 preview 并让用户确认方案。")

    plan = build_plan(target)
    if not plan["moves"]:
        return {
            **plan,
            "action": "organize",
            "status": "nothing_to_do",
            "moved_count": 0,
            "failed_count": 0,
            "manifest": None,
        }

    _managed_directory(target / OUTPUT_DIR_NAME, target, create=False)
    manifest_path = _manifest_path(target)
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "tool_version": VERSION,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "status": "in_progress",
        "target": str(target),
        "output_root": plan["output_root"],
        "moves": [{**move, "state": "planned", "error": None} for move in plan["moves"]],
    }
    _atomic_write_json(manifest_path, manifest)

    moved_count = 0
    failures: list[dict[str, str]] = []
    reserved: set[str] = set()
    for item in manifest["moves"]:
        source = Path(item["source"])
        planned_destination = Path(item["destination"])
        try:
            if not source.exists() or not source.is_file() or source.is_symlink():
                raise OrganizerError("源文件已不存在、不是普通文件或已变成符号链接")
            output_root = _managed_directory(target / OUTPUT_DIR_NAME, target, create=True)
            assert output_root is not None
            category_dir = _managed_directory(output_root / item["category"], target, create=True)
            assert category_dir is not None
            destination = unique_destination(category_dir, planned_destination.name, reserved)
            shutil.move(str(source), str(destination))
            item["destination"] = str(destination)
            item["state"] = "moved"
            moved_count += 1
        except Exception as exc:
            item["state"] = "failed"
            item["error"] = str(exc)
            failures.append({"source": str(source), "error": str(exc)})
        manifest["updated_at"] = now_iso()
        _atomic_write_json(manifest_path, manifest)

    manifest["status"] = "completed" if not failures else "partial"
    manifest["updated_at"] = now_iso()
    _atomic_write_json(manifest_path, manifest)
    return {
        "action": "organize",
        "status": manifest["status"],
        "target": str(target),
        "output_root": plan["output_root"],
        "moved_count": moved_count,
        "failed_count": len(failures),
        "failures": failures,
        "manifest": str(manifest_path),
        "undo_command": f'undo "{target}" --confirm',
    }


def _load_manifest(path: Path) -> dict[str, Any]:
    """读取并校验历史记录。 / Read and minimally validate a history manifest."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise OrganizerError(f"无法读取历史记录 {path}：{exc}") from exc
    if payload.get("schema_version") != 1 or not isinstance(payload.get("moves"), list):
        raise OrganizerError(f"历史记录格式不受支持：{path}")
    return payload


def list_history(target: Path, limit: int = 10) -> dict[str, Any]:
    """列出整理历史。 / List organization history."""
    validate_target(target)
    state_dir = _managed_directory(target / STATE_DIR_NAME, target, create=False)
    history_dir = _managed_directory(state_dir / "history", target, create=False) if state_dir else None
    items: list[dict[str, Any]] = []
    if history_dir:
        for path in sorted(history_dir.glob("*.json"), reverse=True):
            try:
                payload = _load_manifest(path)
            except OrganizerError as exc:
                items.append({"manifest": str(path), "status": "invalid", "error": str(exc)})
                continue
            states = Counter(item.get("state", "unknown") for item in payload["moves"])
            items.append({
                "manifest": str(path),
                "created_at": payload.get("created_at"),
                "updated_at": payload.get("updated_at"),
                "status": payload.get("status", "unknown"),
                "states": dict(states),
                "undoable_count": sum(states.get(state, 0) for state in UNDOABLE_STATES),
            })
            if len(items) >= max(limit, 1):
                break
    return {"action": "history", "target": str(target), "history": items}


def _latest_undoable_manifest(target: Path) -> Path:
    """查找最近仍可撤销的记录。 / Find the latest still-undoable manifest."""
    state_dir = _managed_directory(target / STATE_DIR_NAME, target, create=False)
    history_dir = _managed_directory(state_dir / "history", target, create=False) if state_dir else None
    if not history_dir:
        raise OrganizerError("没有找到整理历史，无法撤销。")
    for path in sorted(history_dir.glob("*.json"), reverse=True):
        try:
            payload = _load_manifest(path)
        except OrganizerError:
            continue
        if any(item.get("state") in UNDOABLE_STATES for item in payload["moves"]):
            return path
    raise OrganizerError("没有仍可撤销的整理记录。")


def undo(target: Path, confirmed: bool, manifest_arg: Optional[str] = None) -> dict[str, Any]:
    """撤销一次整理且不覆盖原位置。 / Undo one run without overwriting original paths."""
    if not confirmed:
        raise OrganizerError("撤销操作必须显式添加 --confirm。请先查看 history 并让用户确认。")
    validate_target(target)
    manifest_path = Path(manifest_arg).expanduser().resolve() if manifest_arg else _latest_undoable_manifest(target)
    state_dir = _managed_directory(target / STATE_DIR_NAME, target, create=False)
    history_root = _managed_directory(state_dir / "history", target, create=False) if state_dir else None
    if not history_root:
        raise OrganizerError("没有找到整理历史，无法撤销。")
    if not _is_relative_to(manifest_path, history_root):
        raise OrganizerError("只能撤销当前目标文件夹中的历史记录。")

    payload = _load_manifest(manifest_path)
    if Path(payload.get("target", "")).resolve() != target:
        raise OrganizerError("历史记录与当前目标文件夹不匹配。")

    restored = 0
    conflicts: list[dict[str, str]] = []
    errors: list[dict[str, str]] = []
    for item in reversed(payload["moves"]):
        if item.get("state") not in UNDOABLE_STATES:
            continue
        source = Path(item["source"]).resolve()
        destination = Path(item["destination"]).resolve()
        if not _is_relative_to(source, target) or not _is_relative_to(destination, target):
            item["state"] = "undo_error"
            item["error"] = "历史记录路径超出目标文件夹"
            errors.append({"destination": str(destination), "error": item["error"]})
        elif source.exists():
            item["state"] = "undo_conflict"
            item["error"] = "原位置已有同名文件，未覆盖"
            conflicts.append({"source": str(source), "destination": str(destination)})
        elif not destination.exists():
            item["state"] = "undo_missing"
            item["error"] = "整理后的文件已不存在"
            errors.append({"destination": str(destination), "error": item["error"]})
        elif destination.is_symlink() or not destination.is_file():
            item["state"] = "undo_error"
            item["error"] = "整理后的路径不是普通文件，已停止恢复"
            errors.append({"destination": str(destination), "error": item["error"]})
        else:
            try:
                source.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(destination), str(source))
                item["state"] = "restored"
                item["error"] = None
                restored += 1
            except Exception as exc:
                item["state"] = "undo_error"
                item["error"] = str(exc)
                errors.append({"destination": str(destination), "error": str(exc)})
        payload["updated_at"] = now_iso()
        _atomic_write_json(manifest_path, payload)

    payload["status"] = "undo_completed" if not conflicts and not errors else "undo_partial"
    payload["updated_at"] = now_iso()
    _atomic_write_json(manifest_path, payload)
    return {
        "action": "undo",
        "status": payload["status"],
        "target": str(target),
        "manifest": str(manifest_path),
        "restored_count": restored,
        "conflict_count": len(conflicts),
        "error_count": len(errors),
        "conflicts": conflicts,
        "errors": errors,
    }


def _walk_files(target: Path) -> Iterable[Path]:
    """安全递归枚举普通文件。 / Safely recurse through regular files."""
    for root, dirs, files in os.walk(target, topdown=True, followlinks=False):
        root_path = Path(root)
        dirs[:] = [
            name for name in dirs
            if not name.startswith(".")
            and not (root_path / name).is_symlink()
            and name.lower() not in VCS_MARKERS
        ]
        for name in files:
            path = root_path / name
            if skip_reason(path) is None:
                yield path


def find_large_files(target: Path, min_size_mb: float, limit: int) -> dict[str, Any]:
    """只读查找大文件。 / Find large files without modifying them."""
    validate_target(target)
    if min_size_mb < 0:
        raise OrganizerError("--min-size 不能小于 0。")
    if limit < 1:
        raise OrganizerError("--limit 必须大于 0。")
    threshold = int(min_size_mb * 1024 * 1024)
    files: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for path in _walk_files(target):
        try:
            size_bytes = path.lstat().st_size
        except OSError as exc:
            errors.append({"path": str(path), "error": str(exc)})
            continue
        if size_bytes >= threshold:
            files.append({"path": str(path), "size_bytes": size_bytes})
    files.sort(key=lambda item: (-item["size_bytes"], item["path"].casefold()))
    files = files[:limit]
    return {
        "action": "large",
        "target": str(target),
        "min_size_mb": min_size_mb,
        "limit": limit,
        "total_files": len(files),
        "total_size_bytes": sum(item["size_bytes"] for item in files),
        "files": files,
        "errors": errors,
        "read_only": True,
    }


def _print_categories(categories: dict[str, dict[str, int]]) -> None:
    """打印分类摘要。 / Print a category summary."""
    for category, data in categories.items():
        print(f"  {category}: {data['count']} 个，{format_size(data['size_bytes'])}")


def print_human(result: dict[str, Any]) -> None:
    """打印适合普通用户阅读的结果。 / Print a beginner-friendly result."""
    action = result["action"]
    if action == "preview":
        print(f"目标：{result['target']}")
        print(f"计划移动：{result['total_files']} 个文件，共 {format_size(result['total_size_bytes'])}")
        _print_categories(result["categories"])
        if result["moves"]:
            print("移动示例：")
            for item in result["moves"][:8]:
                print(f"  {Path(item['source']).name} -> {item['category']}/{Path(item['destination']).name}")
        print(f"跳过：{len(result['skipped'])} 个项目")
        print("这是预览，没有创建目录，也没有移动或删除任何文件。")
    elif action == "organize":
        print(f"整理状态：{result['status']}")
        print(f"已移动：{result['moved_count']} 个；失败：{result['failed_count']} 个")
        if result.get("manifest"):
            print(f"撤销记录：{result['manifest']}")
            print(f"撤销命令：{result['undo_command']}")
    elif action == "history":
        print(f"目标：{result['target']}")
        if not result["history"]:
            print("没有整理历史。")
        for item in result["history"]:
            print(f"{item.get('created_at', '未知时间')} | {item['status']} | 可撤销 {item.get('undoable_count', 0)} 个")
            print(f"  {item['manifest']}")
    elif action == "undo":
        print(f"撤销状态：{result['status']}")
        print(
            f"已恢复：{result['restored_count']} 个；"
            f"冲突：{result['conflict_count']} 个；错误：{result['error_count']} 个"
        )
        print(f"历史记录：{result['manifest']}")
    elif action == "large":
        print(f"目标：{result['target']}")
        print(f"找到 {result['total_files']} 个大文件，共 {format_size(result['total_size_bytes'])}")
        for item in result["files"]:
            print(f"  {format_size(item['size_bytes']):>10}  {item['path']}")
        print("这是只读结果，没有移动或删除任何文件。")


def build_parser() -> argparse.ArgumentParser:
    """创建命令行解析器。 / Build the command-line parser."""
    parser = argparse.ArgumentParser(
        description="file-organizer-cn：先预览、再确认、可撤销的跨平台文件整理工具",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    preview_parser = subparsers.add_parser("preview", help="预览分类方案，不写入磁盘")
    preview_parser.add_argument("target", nargs="?", default="downloads", help="目录别名或路径")
    preview_parser.add_argument("--json", action="store_true", help="输出 JSON")

    organize_parser = subparsers.add_parser("organize", help="经明确确认后执行整理")
    organize_parser.add_argument("target", nargs="?", default="downloads", help="目录别名或路径")
    organize_parser.add_argument("--confirm", action="store_true", help="确认已查看预览并执行")
    organize_parser.add_argument("--json", action="store_true", help="输出 JSON")

    history_parser = subparsers.add_parser("history", help="查看整理历史")
    history_parser.add_argument("target", nargs="?", default="downloads", help="目录别名或路径")
    history_parser.add_argument("--limit", type=int, default=10, help="最多显示多少条记录")
    history_parser.add_argument("--json", action="store_true", help="输出 JSON")

    undo_parser = subparsers.add_parser("undo", help="撤销最近一次整理")
    undo_parser.add_argument("target", nargs="?", default="downloads", help="目录别名或路径")
    undo_parser.add_argument("--manifest", help="指定当前目标目录中的历史记录 JSON")
    undo_parser.add_argument("--confirm", action="store_true", help="确认执行撤销")
    undo_parser.add_argument("--json", action="store_true", help="输出 JSON")

    large_parser = subparsers.add_parser("large", help="只读查找大文件")
    large_parser.add_argument("target", nargs="?", default="downloads", help="目录别名或路径")
    large_parser.add_argument("--min-size", type=float, default=100, help="最小文件大小，单位 MB")
    large_parser.add_argument("--limit", type=int, default=30, help="最多显示多少个文件")
    large_parser.add_argument("--json", action="store_true", help="输出 JSON")
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    """命令行入口。 / Command-line entry point."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    args = build_parser().parse_args(argv)
    try:
        target = resolve_target(args.target)
        if args.command == "preview":
            result = build_plan(target)
        elif args.command == "organize":
            result = organize(target, args.confirm)
        elif args.command == "history":
            result = list_history(target, args.limit)
        elif args.command == "undo":
            result = undo(target, args.confirm, args.manifest)
        elif args.command == "large":
            result = find_large_files(target, args.min_size, args.limit)
        else:
            raise OrganizerError(f"未知命令：{args.command}")
    except OrganizerError as exc:
        error = {"status": "error", "message": str(exc)}
        if getattr(args, "json", False):
            print(json.dumps(error, ensure_ascii=False, indent=2))
        else:
            print(f"错误：{exc}", file=sys.stderr)
        return 2

    if getattr(args, "json", False):
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print_human(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
