---
name: file-organizer-cn
description: 跨平台的中文文件整理助手，先预览并锁定分类方案，再经用户明确确认后移动文件，支持隐私友好的 HTML 报告和可撤销记录。用户提到整理下载文件夹、桌面太乱、文件自动归类、生成整理报告、查找大文件、恢复刚才的整理，或希望安全清理文件但不想误删时使用。适用于 Windows、macOS 和 Linux；不用于删除文件。
---

# 文件整理助手

把“整理文件夹”拆成可检查、可确认、可撤销的流程。默认只查看目标文件夹第一层，不进入子文件夹，不删除文件，也不覆盖同名文件。默认跳过“代码与数据”和“其他”两类高不确定文件。

## 必须遵守的安全顺序

1. 确认目标文件夹。用户未指定时，优先使用 `downloads`，但要在回复中写出解析后的绝对路径。
2. 先运行 `preview`。即使用户说“帮我整理”，第一次也只能预览，不得直接移动。
3. 记住预览返回的 `plan_id`，用普通话概括将移动多少文件、主要分类、跳过了什么，并给出少量示例。
4. 等用户看过预览并明确同意后，才能使用同一个 `plan_id` 运行 `organize`。
5. 整理完成后，告诉用户撤销方式和历史记录位置。

不要把用户对“想整理”的泛化表达当成看过方案后的确认。不要删除文件，不要用系统删除命令代替本脚本，不要添加覆盖同名文件的逻辑。

## 定位脚本

脚本位于本 Skill 的 `scripts/file_organizer.py`。执行前先把 `<SKILL_DIR>` 替换为当前 Skill 的绝对目录；路径始终加引号。

Windows：

```powershell
python "<SKILL_DIR>\scripts\file_organizer.py" preview "downloads"
```

macOS / Linux：

```bash
python3 "<SKILL_DIR>/scripts/file_organizer.py" preview "downloads"
```

支持 `downloads`、`desktop`、`documents`、`pictures` 及对应中文别名，也支持绝对路径。若 `python` 不可用，Windows 尝试 `py -3`，macOS / Linux 尝试 `python3`。

## 工作流

### 1. 预览整理方案

```bash
python "<SKILL_DIR>/scripts/file_organizer.py" preview "<目标文件夹>" --json
```

读取 JSON 中的 `plan_id`、`total_files`、`total_size_bytes`、`categories`、`moves` 和 `skipped`。向用户展示：

- 目标文件夹的绝对路径；
- 计划移动的文件总数和大小；
- 各分类数量；
- 最多 8 个“原位置 → 新位置”示例；
- 被跳过的隐藏文件、临时下载文件、符号链接等。
- 默认跳过的“代码与数据”和“其他”分类。

预览命令不得创建目录或状态文件。

### 2. 获得明确确认

使用一句简短问题，例如：“预览显示会移动 36 个文件到该目录下的‘已整理’文件夹，代码和未知文件已跳过，不会删除或覆盖文件。现在执行吗？”

如果用户改变范围或分类要求，重新预览。不能沿用旧预览直接执行。

### 3. 执行整理

用户明确同意后运行：

```bash
python "<SKILL_DIR>/scripts/file_organizer.py" organize "<目标文件夹>" --confirm --plan-id "<预览编号>" --json
```

整理结果默认进入 `<目标文件夹>/已整理/<分类>/`。同名文件自动改为 `文件名 (1).扩展名`，绝不覆盖。每次操作会在 `<目标文件夹>/.file-organizer-cn/history/` 保存清单。

如果目标文件夹在预览后新增、删除或修改了待移动文件，计划编号会变化，脚本必须拒绝执行并重新预览。

只有用户明确要求整理代码或未知类型文件时，才在预览和执行阶段同时加 `--include-risky`。用户要求跳过图片、视频等分类时，在两个阶段同时使用 `--exclude-category "图片"`。

### 4. 生成可视化预览报告

用户希望更直观地确认方案或需要截图展示时运行：

```bash
python "<SKILL_DIR>/scripts/file_organizer.py" report "<目标文件夹>" --output "<报告路径>.html" --json
```

报告完全离线，默认隐藏完整路径和文件名，仅显示扩展名、分类、数量和大小。只有用户明确需要看到文件名时才加 `--reveal-names`。报告必须保存到待整理文件夹之外；它不移动源文件，也不覆盖已有报告。

### 5. 撤销最近一次整理

仍需先说明将撤销哪一次操作，并获得用户明确确认：

```bash
python "<SKILL_DIR>/scripts/file_organizer.py" history "<目标文件夹>" --json
python "<SKILL_DIR>/scripts/file_organizer.py" undo "<目标文件夹>" --confirm --json
```

如果原位置已出现同名文件，撤销会跳过该项，不覆盖新文件。向用户明确列出未恢复项目。

### 6. 查找大文件

这是只读操作，可以直接运行：

```bash
python "<SKILL_DIR>/scripts/file_organizer.py" large "<目标文件夹>" --min-size 100 --limit 30 --json
```

该命令会递归查找大文件，但不移动或删除任何内容。

## 边界与失败处理

- 脚本拒绝磁盘根目录、用户主目录、系统目录和可识别的代码仓库根目录。
- 默认只整理目标文件夹第一层；子文件夹保持原样。
- 默认不移动代码、数据文件和无法识别类型的文件；需要时单独确认。
- 隐藏文件、系统文件、未下载完成的文件、锁文件和符号链接会被跳过。
- 任何失败都先保留现状，报告具体文件，不用更激进的命令补救。
- 用户要求删除、去重或清理空间时，本 Skill 只能先盘点；删除属于另一个需单独确认的任务。

首次安装、命令找不到和 Python 环境问题，读取 [references/quickstart-cn.md](references/quickstart-cn.md)。完整分类和安全规则，读取 [references/rules-cn.md](references/rules-cn.md)。
