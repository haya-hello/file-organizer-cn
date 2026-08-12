# 首次使用指南

## 最省事的安装方式

项目公开后，在终端运行：

```bash
npx skills add haya-hello/file-organizer-cn --skill file-organizer-cn -g -y
```

安装完成后重启或刷新当前 Agent 会话，然后直接说：

```text
使用 file-organizer-cn，先预览我的下载文件夹怎么整理，不要移动文件。
```

看到预览后，如果方案正确，再说：

```text
按刚才的方案执行整理。
```

需要反悔时说：

```text
使用 file-organizer-cn，撤销下载文件夹最近一次整理。
```

## 不安装也能直接运行

进入仓库根目录后：

```powershell
python ".\file-organizer-cn\scripts\file_organizer.py" preview "downloads"
```

macOS / Linux 将 `python` 换成 `python3` 即可。

## 常见问题

### 找不到 Python

- Windows：尝试 `py -3 --version`。
- macOS / Linux：尝试 `python3 --version`。
- 需要 Python 3.9 或更高版本，不需要安装第三方 Python 包。

### 找不到下载文件夹

别名会尝试常见的 `Downloads`、`下载` 和 OneDrive 路径。仍找不到时，传入绝对路径：

```powershell
python ".\file-organizer-cn\scripts\file_organizer.py" preview "D:\Downloads"
```

### 为什么只预览，没有直接整理

这是强制安全设计。用户必须先看到将移动什么，再明确确认。正式命令还必须包含 `--confirm`。

### 为什么没有整理子文件夹

默认只整理当前目录第一层，避免打散已有项目、课程文件夹或软件目录。若需要整理某个子文件夹，应单独把它作为目标再预览。

### 撤销时有文件没有恢复

通常是原位置出现了同名新文件，或目标文件被手动移动。工具不会覆盖现有文件；先查看报告，再由用户决定如何处理冲突。
