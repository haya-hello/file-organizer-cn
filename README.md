# file-organizer-cn

一个给普通人用的中文文件整理 Skill：先预览，再确认，整理后还能撤销。

它基于 [crazynomad/skills](https://github.com/crazynomad/skills) 中 `file-organizer` 的思路改良，保留原项目 MIT 许可与署名，并重点补齐：

- Windows、macOS、Linux 跨平台；
- 默认只扫描目标文件夹第一层，不打散已有子文件夹；
- 预览阶段零写入；
- 正式整理必须显式确认；
- 同名文件自动编号，绝不覆盖；
- 每次整理保留 JSON 清单，可以撤销；
- 不删除任何文件；
- 面向中文普通用户的首次使用引导和失败处理。

## 一句话安装

```bash
npx skills add haya-hello/file-organizer-cn --skill file-organizer-cn -g -y
```

安装后对支持 Agent Skills 的工具说：

```text
使用 file-organizer-cn，先预览我的下载文件夹怎么整理，不要移动文件。
```

看过方案后再说：

```text
按刚才的方案执行整理。
```

需要反悔时说：

```text
使用 file-organizer-cn，撤销下载文件夹最近一次整理。
```

## 直接运行

只需要 Python 3.9 或更高版本，不需要安装任何 Python 包。

```powershell
# 只预览，不改变文件 / Preview only, no file changes
python ".\file-organizer-cn\scripts\file_organizer.py" preview "downloads"

# 看过预览后正式整理 / Organize after reviewing the preview
python ".\file-organizer-cn\scripts\file_organizer.py" organize "downloads" --confirm

# 查看历史 / List organization history
python ".\file-organizer-cn\scripts\file_organizer.py" history "downloads"

# 撤销最近一次 / Undo the latest run
python ".\file-organizer-cn\scripts\file_organizer.py" undo "downloads" --confirm

# 只读查找大文件 / Find large files without modifying them
python ".\file-organizer-cn\scripts\file_organizer.py" large "downloads" --min-size 100
```

`downloads` 也可以换成 `desktop`、`documents`、`pictures`、中文别名或绝对路径。

## 整理结果

文件默认移动到目标文件夹内：

```text
目标文件夹/
├─ 已整理/
│  ├─ 文档/
│  ├─ 表格/
│  ├─ 图片/
│  ├─ 视频/
│  └─ 其他/
└─ .file-organizer-cn/
   └─ history/
      └─ 一次整理对应一个 JSON 撤销记录
```

工具不会进入原有子文件夹，也不会自动删除、去重或覆盖文件。

## 为什么改良这个项目

上游版本为 macOS 下载目录设计，支持智能文件夹和自动归类。这个版本保留“先看方案再整理”的实用核心，把它改造成跨平台、可恢复、默认更保守的中文 Skill，让第一次接触 Agent 的用户也敢在自己的真实文件夹里使用。

上游快照：`crazynomad/skills@2bc470fc08b47b63af8c1721058672ad0678ab78`

## 开发验证

```bash
python -m unittest discover -s tests -v
python tests/validate_skill.py
```

## 许可与署名

本项目使用 MIT License。原始思路与部分分类设计来自 `crazynomad/skills` 的 `file-organizer`，原作者为 Burn Wang，详见 [LICENSE](LICENSE) 与 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
