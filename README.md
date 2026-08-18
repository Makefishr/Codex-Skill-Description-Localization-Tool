# Codex Localize Skill Cards

安全地为 Codex skill card 的 `interface.short_description` 生成并应用简体中文译文。
项目默认只扫描个人 skill；受管目录和插件缓存必须显式使用 `--include-managed` 才会纳入。

> **English summary:** A small, approval-gated tool for localizing Codex skill-card
> descriptions. It plans changes before writing, preserves unrelated bytes, rejects
> unsafe structures and symlinks, and keeps machine-specific approvals outside the repository.

## 特性

- `scan`、`plan`、`validate` 和不带 `--confirm` 的 `restore` 只读；`apply --confirm` 与 `restore --confirm` 才会写入简介。
- 写入使用临时文件、fsync 和原子替换，并在失败时回滚本次已写入项目。
- 只修改单行 `interface.short_description`，拒绝重复字段、异常 YAML 结构、多行文本和不安全符号链接。
- 默认个人范围排除 `.system`，并始终排除临时插件目录。
- 通过 `CODEX_HOME` 或 `--codex-home` 使用不同的 Codex 状态根目录；未设置时由 Python 使用 `Path.home() / ".codex"`。
- 公开仓库不包含任何本机批准译文、个人技能清单、插件清单或运行记录。
- 运行目录创建为 `0700`，记录创建和原子更新为 `0600`；持久化记录只包含 restore 必需的路径、stable ID、old/new 描述及固定 schema 元数据，不保存完整 `openai.yaml`。

## 安全模型

工具把翻译分为“已有清晰中文”“已有本地批准译文”“需要审批”和“错误”几类。首次出现的英文简介不会自动应用：先查看 `plan` 输出，审阅后把批准内容保存到本地批准文件，再明确运行 `apply --confirm`。

默认批准文件位于：

```text
${CODEX_HOME}/localize-skill-cards/approved-translations.json
```

如果没有设置 `CODEX_HOME`，实际位置是 `Path.home() / ".codex" / "localize-skill-cards" / "approved-translations.json"`。运行记录默认保存到同目录下的 `runs/`。这些文件是本机状态，不属于公开仓库；请不要提交或分享它们。`references/approved-translations.json` 只保留空 schema/template，作为格式参考，不会被默认加载。
批准 catalog 使用固定 JSON schema：顶层必须包含 `version: 1`、`selection_rule` 和 `translations` 对象；不接受 bare map、未知顶层字段、非字符串译文或无效 stable ID。stable ID 形如 `personal/name`、`system/name` 或 `plugin/vendor/package/skill`；name segment 只允许 ASCII 字母、数字、点、下划线和连字符，但不能恰好是 `.` 或 `..`。`scan` 输出 discovery JSON；`plan` 输出包含 `error`/`needs-approval` 的结构化计划；`validate` 输出计划并在未解决时返回非零；`apply --confirm` 采用 all-or-nothing 规则，任何 error 或 needs-approval 都会拒绝且不写入。

恢复操作先预览，再使用 `restore --confirm`。只接受当前 `CODEX_HOME` 规范运行目录内、本工具生成、schema/type/status/路径一致且权限私有的真实记录文件；外部记录、symlink、未知或异常字段和非 completed 记录会被拒绝。恢复前还会检查 stable ID、目标范围和文本漂移。恢复个人 skill 时默认拒绝 system 和插件目标；恢复 managed 记录必须显式使用 `--include-managed`。

为避免异常输入耗尽内存，工具采用显式上限并在超限时失败：单个输入及生成后的 `openai.yaml` 256 KiB、翻译 catalog 2 MiB、一次发现 10,000 个候选且累计 128 MiB、restore record 8 MiB 且最多 4,096 个 change。读取采用 `limit + 1` 的 bounded read，不会静默截断。

## 仓库布局

```text
.
├── README.md
├── LICENSE
└── skills/
    └── localize-skill-cards/
        ├── SKILL.md
        ├── agents/openai.yaml
        ├── references/approved-translations.json
        └── scripts/
            ├── localize_skill_cards.py
            └── test_localize_skill_cards.py
```

## 安装

将 `skills/localize-skill-cards/` 作为一个 skill 子目录安装到你的 Codex skill 根目录，例如：

```text
<CODEX_HOME>/skills/localize-skill-cards/
```

不要把整个仓库误复制成 skill；需要保留 `SKILL.md`、`agents/openai.yaml`、`references/` 和 `scripts/` 这组子目录。安装或升级前请备份现有 skill，因为覆盖可能替换本地版本。

## 使用

从 `skills/localize-skill-cards/` 目录执行：

```bash
python3 scripts/localize_skill_cards.py scan
python3 scripts/localize_skill_cards.py plan
python3 scripts/localize_skill_cards.py validate
python3 scripts/localize_skill_cards.py apply --confirm
python3 scripts/localize_skill_cards.py restore RUN.json
python3 scripts/localize_skill_cards.py restore RUN.json --confirm [--codex-home DIR] [--include-managed]
```

可以用环境变量或 CLI 参数覆盖 Codex 根目录：

```bash
CODEX_HOME=/path/to/codex-home python3 scripts/localize_skill_cards.py scan
python3 scripts/localize_skill_cards.py scan --codex-home /path/to/codex-home
```

需要扫描 `.system` 和插件缓存时，显式添加 `--include-managed`：

```bash
python3 scripts/localize_skill_cards.py scan --include-managed
python3 scripts/localize_skill_cards.py plan --include-managed
```

翻译批准文件默认从本地 `CODEX_HOME/localize-skill-cards/approved-translations.json` 读取；也可以显式传入一个文件：

```bash
python3 scripts/localize_skill_cards.py plan --translations /path/to/approved-translations.json
```

建议的人工流程是 `scan` → `plan` → 逐项审阅和批准 → `validate` → `apply --confirm`。没有本地批准文件时，英文项会保持 `needs-approval`，不会因为仓库内的空模板而自动改变。`plan` 会对 Codex、GitHub、PR、CI、API 及旧文中的全大写或内部大写标识执行保留检查，并对可能的 Title Case 产品名输出 warning；看到 warning 时应逐条复核。
成功的 `apply --confirm` stdout 是单一 JSON 对象，包含 `status`、`plan` 和 `record` 字段；预期输入、记录和权限错误会以简洁 stderr 返回非零退出码，不输出半截 JSON。

## 测试

项目只使用 Python 标准库。运行：

```bash
cd skills/localize-skill-cards/scripts
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest -v test_localize_skill_cards
```

测试覆盖默认和 managed 范围、版本选择、元数据合同、空公开 catalog、审批状态、私有且最小化的唯一记录、可信 restore schema、资源上限、原子写入、事务回滚、恢复漂移和路径越界保护。

## 已知限制

- 插件 stable ID 仍依赖 Codex 插件缓存的约定目录层级；非标准缓存布局会被跳过。
- 运行记录包含本机路径，因此只适合本地恢复，不应提交到公开仓库。
- 这是一个 skill 源码目录，不是 Python 包，也没有自动安装器或发布到 skill registry 的流程。
- `--include-managed` 可能扫描大量系统和插件文件；使用前应确认范围，并检查 `plan` 输出。
- 工具不会验证译文的语言风格或产品商标，只执行结构、安全和长度约束；人工审批仍是必要步骤。
- 升级安装可能覆盖已安装 skill 的本地修改。请先备份，保留运行记录，并在升级后重新执行 `scan`、`plan` 和测试。
- 目标目录被其他进程并发替换不在支持范围内；路径与写入边界检查会缩小竞态窗口，但不宣称完全消除 TOCTOU。
- 不要以提升权限运行本工具，也不要使用其他用户可写的 `CODEX_HOME`；这些部署方式会破坏本地状态和目标目录的信任边界。

## 许可证

MIT，详见 [LICENSE](LICENSE)。
