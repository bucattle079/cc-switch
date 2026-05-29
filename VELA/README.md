# VELA Workspace

这个文件夹是 VELA 的长期升级与优化中心。

## 放置原则

- `CC-WECHAT\VELA`：存放 VELA 的长期资料，包括人格契约、素材吸收、成长记录、简报样式、质检记录、头像资源、Codex 快照和迭代归档。
- `C:\Users\Admin\.cc-connect`：只放微信桥接运行配置和会话状态。它是运行层，不是 VELA 的知识库。
- `C:\Users\Admin\Desktop\AGENTS.md`：保留为当前桌面 Codex 工作目录的活入口。不要移动它。
- `C:\Users\Admin\.codex\skills\vela-*`：保留为 Codex 实际加载的技能入口。VELA 文件夹保存源资料和归档，技能文件负责运行。

## 当前结构

- `voice-contract.json`：VELA 当前人格、语气和质量门槛的主契约。
- `source-material.md`：人物台词、三观分析、旁白和语气素材的蒸馏记录。
- `growth-notes.md`：交互中沉淀出的成长规则。
- `codex-snapshots\`：`/CODEX` 最近任务结论和截图快照。
- `iteration-archive\`：脚本同步、配置迭代和桌面备份的归档区。
- `VELA*.png` / `VELA*.jpg`：头像和视觉资源。

## 后续约定

之后所有 VELA 升级优化优先从这里读写。只有真正需要被 cc-connect 或 Codex 运行时读取的内容，才同步到 `.cc-connect` 或 `.codex\skills`。
