# Wisland · ChatGPT 与 Codex 消息扩展

为 Windows 版 Wisland 增加 ChatGPT 和 Codex 消息卡片，沿用原消息页的提醒动画、未读数、历史、颜色标记和「全部已读」。适配 [Wisland v1.2.2](https://github.com/AsamiAkito/wisland/releases/tag/v1.2.2)，v1.2.1 的五个覆盖文件与其一致。使用 Wisland 原有的 Python 3.10+ 和 PySide6 环境。

## 安装或更新

1. 从本仓库 Releases 下载 `wisland-openai-notifications-v1.0.0.zip`。
2. 在灵动岛右键菜单选择「退出 wisland」。
3. 将 ZIP 的内容解压到含有 `wisland.vbs` 的目录，允许合并 `wisland` 文件夹并覆盖同名文件。双击 `wisland.vbs` 重新启动。
4. 展开灵动岛进入「消息」。第一行为 QQ、微信、邮件，第二行为 ChatGPT、Codex。点击卡片切到客户端并清除该项未读。

ZIP 包含五个替换文件、一个新增消息识别模块以及 `openai-notifications` 安装说明目录。个人配置、模型、已有历史目录与隔空投送控制页独立于这些文件。

### 有本地代码改动时

将 ZIP 解压到**单独的临时目录**，从该目录运行可选安装器。以下命令中的路径替换为自己的安装路径。

```powershell
py -3 .\openai-notifications\install.py --target "D:\Apps\wisland"
```

安装器先检查全部目标文件的 SHA-256（统一换行后计算）。遇到未知修改会列出冲突文件并退出，核对通过后逐文件替换。初始文件按原字节备份于目标的 `data/extension-backups/openai-notifications/<备份编号>`。同一版本重复运行会显示 Already installed。退出 Wisland 后可恢复指定备份，例：

```powershell
py -3 .\openai-notifications\install.py --target "D:\Apps\wisland" --rollback "<备份编号>"
```

直接解压的方式会覆盖五个同名文件。需要保留覆盖前的版本时，请先备份，或使用上述安装器。从源码运行时，安装器从同级项目的 `overlay` 读取文件。

## 能收到哪些通知

- Windows 设置 → 系统 → 通知中，打开桌面客户端的通知。客户端自身也需要允许相关通知。Wisland 启动后监听新增的 Windows Toast 与该客户端的任务栏闪烁。
- 本机统一桌面客户端的注册标识是 `OpenAI.Codex_2p2nqsd0c76g0!App`。有明确聊天会话激活地址的通知可计入 ChatGPT，有明确 Codex 任务地址的可计入 Codex。对通用点击通知，后台只在动作模板、唯一投递记录、时间及已登记的本地任务来源相互吻合时分流。
- 客户端只提供共用来源、日志轮转、任务未登记、匹配存在歧义时，显示「ChatGPT / Codex」。有共用未读时，消息页显示一行可点击的共用提醒。点击该行仅清除这项计数。
- 仅闪烁的窗口等待约八秒，给系统通知留出合并时间。同一轮收到的不同 Windows 通知独立计数。「全部已读」保留当次运行的消息历史。
- 实测 Codex 后台任务和 ChatGPT「工作 → 在你的计算机上」各产生了一条系统通知，可以分别归入对应卡片。本机 ChatGPT 普通聊天的前台、后台回复，以及「工作 → 在云端」的短任务完成时均未产生 Windows 通知，这些回复没有触发灵动岛。详见 [验收记录](VALIDATION.md)。

扩展在本地运行。Windows 通知内容中的可见文本不用于 ChatGPT/Codex 分流。辅助匹配只分析近期桌面通知投递元数据，并按任务 ID 查询来源。历史记录保留应用名、提醒类型、时间，不保存任务 ID、正文或会话标题。两个卡片都唤起当前安装的统一客户端。

## 源码与构建

`overlay/` 是可覆盖的运行文件，`openai-notifications/manifest.json` 记录上游及发布文件摘要。在项目根目录执行 `py -3 build.py` 生成 `dist/` 下的 ZIP。测试入口与验收方式见 [VALIDATION.md](VALIDATION.md)。

本扩展基于 AsamiAkito/wisland，使用 MIT 许可。见 [LICENSE](LICENSE)。
