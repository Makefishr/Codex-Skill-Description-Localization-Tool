# Codex 技能卡片简介本地化工具

让 Codex 协助拟定简体中文技能卡片简介，在人工审阅后安全写入本地 skill。

> [!IMPORTANT]
> 本工具只修改 `agents/openai.yaml` 中的单行
> `interface.short_description`，也就是 Codex 界面显示的技能卡片简介。
>
> 它不会修改 skill 名称、`display_name`、`default_prompt`、
> `SKILL.md`（包括决定隐式匹配的 frontmatter `description`）、命令、正文或
> 技能行为，因此不是“完整汉化 skill”。

效果示意：

```diff
 interface:
-  short_description: "Create or update a Codex skill and its supporting resources"
+  short_description: "创建或更新 Codex 技能，并维护必要的说明与配套资源"
```

Codex skill 负责协助拟定和审阅译文；随附的 Python 脚本只负责发现、校验、
应用和恢复，不会调用翻译服务，也不会自动接受未经批准的译文。

## 快速开始

### 1. 安装

推荐使用开源的第三方 [`skills` CLI](https://github.com/vercel-labs/skills)
安装到它定义的 Codex 用户级目录（当前为 `~/.codex/skills`）：

```bash
npx --yes skills@latest add \
  Makefishr/Codex-Skill-Description-Localization-Tool \
  --skill localize-skill-cards \
  --agent codex \
  --global \
  --yes
```

一键安装需要 Node.js，具体版本以 `skills@latest` 的 `engines` 为准；截至
2026-08-20，1.5.23 要求 Node.js 22.20.0 或更高版本。这个要求只来自安装器，
运行核心脚本不需要 Node.js。Python 脚本没有第三方依赖；仓库当前在 Python
3.14.7 上完成了本地验证，但尚未声明最低 Python 版本。

> [!NOTE]
> `skills` CLI 不是 OpenAI 官方安装器，`@latest` 也不是固定版本。
> 它会访问网络，并有独立的匿名 telemetry 政策；详情和关闭方式请查看
> [上游说明](https://github.com/vercel-labs/skills#telemetry)。
> 上面的命令还会通过最后一个 `--yes` 跳过安装确认；需要交互式确认时可移除它。
> 该 CLI 当前把 Codex global skill 安装到 `~/.codex/skills`；OpenAI 官方文档
> 当前列出的通用用户级位置是 `$HOME/.agents/skills`。两者的扫描区别见下文。
> 安装或升级前，请先备份已有的同名 skill 及本地修改。

### 2. 在 Codex 中预览

安装后 Codex 通常会自动发现该 skill；如果没有出现，再重新启动 Codex。
然后在 Codex 对话框中输入下面的内容（不是在终端中执行）：

```text
$localize-skill-cards 扫描我的个人 skill 并拟定简体中文卡片简介；逐项展示计划，先不要写入。
```

该 skill 被配置为只能显式调用。Codex 不会仅凭普通对话自动运行它。

### 3. 审阅并应用

检查每条拟议译文和警告（`warning`）。Codex 会先把逐项批准的译文保存到本地
批准 catalog，再重新运行 `plan` 和 `validate`。只有你明确确认 `apply` 后，
Python CLI 才会修改目标 skill 的 `agents/openai.yaml`。

需要回退时，先让 Codex 预览对应的恢复记录（restore record），再确认恢复。

## 它如何工作

| 参与者 | 职责 |
| --- | --- |
| Codex skill | 扫描现有简介、协助拟定译文、展示计划并等待确认 |
| Python CLI | 校验结构和译文、限定写入范围、逐个原子替换目标文件，并为整批操作生成恢复记录 |
| 用户 | 审阅产品名、语义和措辞，并明确批准写入或恢复 |

标准流程：

```text
scan → plan → 人工审阅 → 保存批准 catalog → validate → apply --confirm
                                                       ↓
                                          restore 预览 → restore --confirm
```

`plan` 会给每个目标标记一种 action：

| action | 含义 |
| --- | --- |
| `skip` | 启发式识别为已有中文；仍建议人工抽查 |
| `change` | 找到结构有效且已批准的中文译文 |
| `needs-approval` | 尚无本地批准译文，不会自动写入 |
| `error` | 文件结构、路径或译文不符合约束 |

## 扫描范围

未设置 `CODEX_HOME` 时，工具使用 `~/.codex`。`--codex-home DIR` 和
`CODEX_HOME=DIR` 都把 `DIR` 视为状态根目录，个人 skill 位于其下的 `skills/`。

| 范围 | 路径 | 启用方式 |
| --- | --- | --- |
| 个人 skill | `CODEX_HOME/skills`，但排除 `.system` | 默认 |
| 系统 skill | `CODEX_HOME/skills/.system` | `--include-managed` |
| 插件缓存 | `CODEX_HOME/plugins/cache` | `--include-managed` |
| 临时插件 | `CODEX_HOME/.tmp/plugins` | 始终排除 |

受管目录可能包含大量文件；启用 `--include-managed` 后，应重新检查完整 `plan`。
一次运行只处理一个 `CODEX_HOME` 布局，不会同时合并多个根目录。

OpenAI 官方文档还列出了用户级 `$HOME/.agents/skills` 和仓库级
`.agents/skills`；这些位置不会被默认的 `~/.codex` 扫描自动发现。若要单独扫描
用户级 `$HOME/.agents/skills`，可在后文 CLI 命令中加入
`--codex-home "$HOME/.agents"`。此时批准 catalog 和 restore record 也会改存到
`$HOME/.agents/` 下。

## 手动安装

把仓库中的 `skills/localize-skill-cards/` 作为完整目录复制到：

```text
<CODEX_HOME>/skills/localize-skill-cards/
```

不要把整个仓库复制成一个 skill。目标目录必须保留 `SKILL.md`、
`agents/openai.yaml`、`references/` 和 `scripts/`。默认布局的完整路径是
`~/.codex/skills/localize-skill-cards/`；若安装到 `$HOME/.agents/skills`，扫描时
也应使用 `--codex-home "$HOME/.agents"`。安装后如果 Codex 没有自动发现该 skill，
再重新启动 Codex。

关于 Codex 如何发现和显式调用 skill，请参阅
[OpenAI 官方 Codex skill 文档](https://learn.chatgpt.com/docs/build-skills)。

## CLI 参考

通常直接在 Codex 中调用 `$localize-skill-cards` 即可。下面的命令用于调试、
自动化或手工维护。

先进入已安装的 skill 目录：

```bash
cd "${CODEX_HOME:-$HOME/.codex}/skills/localize-skill-cards"
```

若安装在 `$HOME/.agents/skills`，则改为进入
`$HOME/.agents/skills/localize-skill-cards`，并在后续命令中使用对应的
`--codex-home "$HOME/.agents"`。

| 命令 | 用途 | 写入目标简介 |
| --- | --- | --- |
| `scan` | 发现目标、stable ID 和当前值 | 否 |
| `plan` | 根据本地批准 catalog 生成结构化计划 | 否 |
| `validate` | 检查是否仍有 `error` 或 `needs-approval` | 否 |
| `apply --confirm` | 应用完全解决的计划并创建 restore record | 是 |
| `restore RECORD_PATH` | 预览恢复 | 否 |
| `restore RECORD_PATH --confirm` | 执行恢复 | 是 |

```bash
python3 scripts/localize_skill_cards.py scan
python3 scripts/localize_skill_cards.py plan
python3 scripts/localize_skill_cards.py validate
python3 scripts/localize_skill_cards.py apply --confirm
python3 scripts/localize_skill_cards.py restore "$HOME/.codex/localize-skill-cards/runs/20260820T123456789012Z-a1b2c3d4.json"
python3 scripts/localize_skill_cards.py restore "$HOME/.codex/localize-skill-cards/runs/20260820T123456789012Z-a1b2c3d4.json" --confirm
```

restore 示例中的文件名只是格式示意。实际使用时，请复制成功执行
`apply --confirm` 后 stdout 中 `record` 字段给出的绝对路径。

常用参数：

```bash
# 扫描 system skill 和插件缓存
python3 scripts/localize_skill_cards.py plan --include-managed

# 使用另一套 CODEX_HOME 布局
python3 scripts/localize_skill_cards.py scan --codex-home /path/to/codex-home

# 单独扫描 OpenAI 文档列出的用户级 $HOME/.agents/skills
python3 scripts/localize_skill_cards.py scan --codex-home "$HOME/.agents"

# 显式使用另一份已批准译文文件
python3 scripts/localize_skill_cards.py plan --translations /path/to/approved-translations.json
python3 scripts/localize_skill_cards.py apply --confirm --translations /path/to/approved-translations.json
```

`--translations` 只适用于 `plan` 和 `apply`；两次命令应传入同一个文件。
`validate` 只读取默认本地 catalog。`plan` 只有遇到 `error` 才返回非零，
而 `validate` 遇到 `error` 或 `needs-approval` 都会返回非零。
`scan` 中的 `valid: false` 条目本身不会让命令返回非零；自动化检查应使用
`validate`。只有计划至少包含一项 `change` 时才应运行 `apply --confirm`，
否则命令会以 `no changes to apply` 退出。

## 批准译文与本地状态

默认批准文件位于：

```text
<CODEX_HOME>/localize-skill-cards/approved-translations.json
```

最小示例：

```json
{
  "version": 1,
  "selection_rule": "highest numeric plugin version, then newest mtime, then lexical version name",
  "translations": {
    "personal/example-skill": "创建或更新 Codex 技能，并维护必要的说明与配套资源"
  }
}
```

stable ID 的形式为 `personal/name`、`system/name` 或
`plugin/vendor/package/skill`。仓库中的
[`references/approved-translations.json`](skills/localize-skill-cards/references/approved-translations.json)
只是空 schema/template，不会被默认加载，也不包含任何本机技能清单或译文。

成功执行 `apply --confirm` 后，运行记录保存在：

```text
<CODEX_HOME>/localize-skill-cards/runs/
```

记录包含本机路径和恢复所需的旧值、新值。它只适合本地恢复，不应提交或分享。
恢复 managed 目标时，同样必须显式加入 `--include-managed`。

## 安全边界

- `scan`、`plan`、`validate` 和不带 `--confirm` 的 `restore` 只读。
- `apply --confirm` 会拒绝任何仍含 `error` 或 `needs-approval` 的计划。
- 只重写唯一的单行 `interface.short_description`，保留文件其他内容。
- 每个文件通过同目录临时文件、`fsync` 和 `os.replace` 替换；可捕获异常发生时，
  工具会尝试回滚本次已经写入的文件。
- 工具会检查目标范围、stable ID、symlink、文本漂移和输入大小；运行目录和记录
  使用仅当前用户可访问的权限。
- 请勿以提升权限运行，也不要使用其他用户可写的 `CODEX_HOME`。

<details>
<summary>资源与结构限制</summary>

- `agents/openai.yaml` 必须包含唯一的顶层 `interface:`，以及恰好两空格缩进、
  双引号、单行的 `short_description`。
- 新简介必须包含中文，长度为 25–64 个字符。原文中的 Codex、GitHub、PR、CI、
  API 及全大写或内部大写 identifier 必须保留；可能的 Title Case 产品名只会生成
  warning，仍需人工复核。
- 单个 `openai.yaml` 和生成结果上限为 256 KiB；批准 catalog 上限为 2 MiB；
  一次发现最多 10,000 个候选且累计不超过 128 MiB。
- restore record 上限为 8 MiB、4,096 个 change；恢复前会校验记录位置、
  schema、状态、stable ID、目标范围和文本漂移。

</details>

## 已知限制

- YAML 解析器有意保守。合法的单引号、无引号、多行 scalar 或行尾注释也可能被拒绝。
- 工具会跳过目标 skill 目录或其内部路径组件为 symlink 的目标；这比 Codex
  本身支持的 skill 布局更严格。
- 批准译文当前只绑定 stable ID，没有绑定原始英文简介的 hash；原文变化后应人工
  重新审阅，避免复用旧译文。
- 普通可捕获异常会尝试回滚，但 `SIGKILL`、进程崩溃或断电期间不保证整批修改
  完全恢复，也不能把它视为 crash-safe 事务。
- 插件 stable ID 依赖当前 Codex 插件缓存目录约定；非标准布局会被跳过。
- 结构校验不能保证译文风格、语义或商标使用正确，最终质量仍由人工审批负责。
- 这是源码分发的早期工具，不是 Python package，也尚未打包为原生 Codex plugin。

## 开发与测试

仓库布局：

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

运行本地测试：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover \
  -s skills/localize-skill-cards/scripts \
  -p 'test_*.py' \
  -v
```

仓库目前没有版本化 Release 或 CI，因此测试结果以本地运行输出为准。

## 许可证

[MIT](LICENSE)
