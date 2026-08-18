---
name: localize-skill-cards
description: 汉化个人或经确认的受管 Codex 技能卡片简介。使用时扫描、生成计划、预览或应用 agents/openai.yaml 中 interface.short_description 的简体中文译文；只在用户确认后写入。
---

# 汉化技能简介

只处理 `agents/openai.yaml` 的 `interface.short_description`。默认范围是
`CODEX_HOME/skills` 中的个人技能，并排除 `.system`；始终排除
`CODEX_HOME/.tmp/plugins`。工具优先读取 `CODEX_HOME` 环境变量；未设置时使用
Python 的 `Path.home() / ".codex"`。只有用户明确要求并使用
`--include-managed` 时才扫描 `.system` 和插件缓存。

## Workflow

1. 先运行 `scan`，确认范围、稳定 ID 和现有字段。
2. 运行 `plan`，只输出候选改动；清晰自然的中文简介直接跳过。没有本地 runtime catalog 时，英文项保持 `needs-approval`。
3. 逐条审阅新译文。首次出现的英文简介需要审批；将批准的译文放入
   `CODEX_HOME/localize-skill-cards/approved-translations.json`（未设置时为
   `Path.home() / ".codex" / "localize-skill-cards" / "approved-translations.json"），
   再向用户展示计划并取得明确确认。这个本地状态文件不会上传到仓库。
4. 仅在确认后运行 `apply --confirm`。工具原子写入，并在 `CODEX_HOME/localize-skill-cards/runs/` 保存记录；失败时回滚本次已写入项目。
5. 用 `validate` 检查结构。恢复时先 `restore` 预览，再用 `restore --confirm` 写入；只接受当前规范运行目录内、本工具生成、顶层字段严格匹配且结构有效的 completed record，恢复 system 或插件记录必须显式使用 `--include-managed`。

翻译要简洁自然，不扩张原义；保留 Codex、GitHub、PR、CI、API 和产品名。只修改单行
`interface.short_description`，保留文件其他字节。工具会拒绝多行、重复字段、异常结构、越界值和不安全符号链接。

## Commands

从本 skill 目录执行以下命令（脚本会根据自身位置解析内置翻译目录）：

```text
python3 scripts/localize_skill_cards.py scan [--codex-home DIR] [--include-managed]
python3 scripts/localize_skill_cards.py plan [--codex-home DIR] [--include-managed] [--translations FILE]
python3 scripts/localize_skill_cards.py apply --confirm [--codex-home DIR] [--include-managed] [--translations FILE]
python3 scripts/localize_skill_cards.py validate [--codex-home DIR] [--include-managed]
python3 scripts/localize_skill_cards.py restore RUN.json [--confirm] [--codex-home DIR] [--include-managed]
```

`--codex-home` 和 `CODEX_HOME` 都只改变扫描根目录及本地批准目录；默认从
`CODEX_HOME/localize-skill-cards/approved-translations.json` 读取 runtime catalog，文件缺失时为空。
`--translations FILE` 可以显式提供其他批准文件。公开仓库中的
`references/approved-translations.json` 只是空 schema/template，不包含任何本机技能清单，也不会被默认加载。
批准 catalog 必须包含 `version: 1`、`selection_rule` 和 `translations` 对象；不接受 bare map、未知顶层字段、非字符串译文或无效 stable ID。stable ID 形如 `personal/name`、`system/name` 或 `plugin/vendor/package/skill`；name segment 只允许 ASCII 字母、数字、点、下划线和连字符，但不能恰好是 `.` 或 `..`。命令默认均为只读或预览；`apply --confirm` 和 `restore --confirm` 是写入操作。`scan` 输出 discovery JSON，`plan` 输出包含 `error`/`needs-approval` 的结构化计划，`validate` 输出计划并在未解决时返回非零。`apply --confirm` 是 all-or-nothing：任何 error 或 needs-approval 都会拒绝且不写入；成功时 stdout 是一个包含 `status`、`plan` 和 `record` 的 JSON 对象。`plan` 会严格检查 Codex、GitHub、PR、CI、API 及旧文中的全大写或内部大写标识，并对可能的 Title Case 产品名输出 warning，需逐条复核。

安全上限：单个输入及生成后的 `openai.yaml` 256 KiB、catalog 2 MiB、候选 10,000 个且累计 128 MiB、record 8 MiB 且最多 4,096 个 change；超限明确失败。运行目录和记录分别使用 `0700`/`0600`，记录仅保存 restore 必需字段。不要提升权限运行，不要使用其他用户可写的 `CODEX_HOME`；不支持目标目录被其他进程并发替换，也不宣称完全消除 TOCTOU。
