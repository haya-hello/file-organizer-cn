# 分类与安全规则

## 默认分类

| 分类 | 常见扩展名 |
|---|---|
| 文档 | doc、docx、txt、md、rtf、odt |
| 表格 | xls、xlsx、csv、numbers、ods |
| 演示文稿 | ppt、pptx、key、odp |
| PDF | pdf |
| 图片 | jpg、png、gif、webp、heic、svg、psd |
| 视频 | mp4、mov、avi、mkv、webm、m4v |
| 音频 | mp3、wav、flac、aac、m4a、ogg |
| 压缩包 | zip、rar、7z、tar、gz、bz2、xz |
| 安装包 | exe、msi、dmg、pkg、deb、rpm、apk |
| 电子书 | epub、mobi、azw3、djvu |
| 字体 | ttf、otf、woff、woff2 |
| 代码与数据 | py、js、ts、html、css、json、yaml、sql、ipynb 等 |
| 其他 | 未命中上述规则的普通文件 |

扩展名匹配不区分大小写。工具只按文件类型归类，不判断文件内容，也不自动删除重复文件。

## 默认跳过

- 文件夹：默认不进入任何子文件夹。
- 隐藏或系统文件：名称以 `.` 开头，或带 Windows 隐藏/系统属性。
- 未完成下载：以 `.part`、`.partial`、`.crdownload`、`.download` 等结尾。
- 临时和锁文件：例如 `~$报告.docx`、`.~lock.*`、`.tmp`。
- 符号链接：避免把链接指向的外部内容带入整理范围。

## 拒绝的目标

- 磁盘根目录，例如 `C:\` 或 `/`；
- 用户主目录本身；
- Windows、Program Files、ProgramData 等系统目录及其子目录；
- `/System`、`/Library`、`/usr`、`/etc`、`/var` 等系统位置；
- 含 `.git`、`.hg`、`.svn`，或明显项目标记组合的代码仓库根目录。

## 冲突策略

整理时若目标位置已有同名文件，使用编号生成新文件名，不覆盖任何文件。撤销时若原位置已有同名文件，则保留两边现状并报告冲突。

## 状态记录

每次正式整理会生成一个 JSON 清单：

```text
<目标文件夹>/.file-organizer-cn/history/YYYYMMDD-HHMMSS-ffffff.json
```

清单记录原路径、新路径、文件大小和每一步状态。执行过程中也会持续更新，因此即使部分文件移动失败，已成功的部分仍能尝试撤销。
