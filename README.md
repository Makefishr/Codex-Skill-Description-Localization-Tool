# Codex 技能简介本地化工具

将 Codex skill 在界面中显示的英文简介转换为简体中文。工具先扫描并生成计划，经过人工审阅和明确确认后，才会修改本地 skill 文件。

> [!IMPORTANT]
> 本工具只修改 `agents/openai.yaml` 中的 `interface.short_description`。
> 它不会修改 skill 名称、`display_name`、`default_prompt`、`SKILL.md`、命令、正文或技能行为，因此不是完整的 skill 汉化工具。

示例：

```diff
 interface:
-  short_description: "Create or update a Codex skill and its supporting resources"
+  short_description: "创建或更新 Codex 技能，并维护必要的说明与配套资源"
```

Codex skill 负责协助拟定和审阅译文；随附的 Python CLI 负责发现、校验、应用和恢复。它不调用翻译服务，也不会自动接受未经批准的译文。

## 快速开始

### 1. 安装

使用第三方 [`skills` CLI](https://github.com/vercel-labs/skills) 安装：

```bash
npx --yes skills@latest add \
  Makefishr/Codex-Skill-Description-Localization-Tool \
  --skill localize-skill-cards \
  --agent codex \
  --global \
  --yes
```

该安装方式需要 Node.js；核心 Python CLI 没有第三方依赖。若不使用 Node.js 或第三方安装器，请参阅[手动安装](#手动安装)。

> [!NOTE]
> `skills` CLI 不是 OpenAI 官方安装器，`@latest` 也不是固定版本。安装器会访问网络，并有独立的匿名 telemetry 政策；详情和关闭方式见其[说明](https://github.com/vercel-labs/skills#telemetry)。
>
> 安装或升级前，请备份已有的同名 skill 及本地修改。

### 2. 在 Codex 中预览

安装后 Codex 通常会自动发现该 skill。若没有出现，请重新启动 Codex，然后在 Codex 对话框中输入以下内容：

```text
$localize-skill-cards 扫描我的个人 skill 并拟定简体中文卡片简介；逐项展示计划，先不要写入。
```

该 skill 只能显式调用，普通对话不会自动触发它。

### 3. 审阅并应用

审阅计划中的译文和 `warning` 后：

1. 将批准的译文保存到本地批准 catalog。
2. 重新运行 `plan` 和 `validate`，确认没有 `error` 或 `needs-approval`。
3. 明确确认后运行 `apply --confirm`。

只有最后一步会修改目标 skill。需要回退时，先预览恢复记录，再运行 `restore --confirm`。

## 工作流与命令

标准流程：

```text
scan → plan → 人工审阅 → 保存批准 catalog → validate → apply --confirm
                                                               ↓
                                                  restore 预览 → restore --confirm
```

先进入已安装的 skill 目录：

```bash
cd "${CODEX_HOME:-$HOME/.codex}/skills/localize-skill-cards"
```

如果安装在 `$HOME/.agents/skills`，请改为进入 `$HOME/.agents/skills/localize-skill-cards`，并在后续命令中使用 `--codex-home "$HOME/.agents"`。

| 命令 | 作用 | 是否写入 |
| --- | --- | --- |
| `scan` | 发现目标、stable ID 和当前简介 | 否 |
| `plan` | 根据批准 catalog 生成结构化计划 | 否 |
| `validate` | 检查计划中是否仍有 `error` 或 `needs-approval` | 否 |
| `apply --confirm` | 应用完整计划，并生成恢复记录 | 是 |
| `restore RECORD_PATH` | 预览恢复内容 | 否 |
| `restore RECORD_PATH --confirm` | 执行恢复 | 是 |

对应的 CLI 调用：

```bash
python3 scripts/localize_skill_cards.py scan
python3 scripts/localize_skill_cards.py plan
python3 scripts/localize_skill_cards.py validate
python3 scripts/localize_skill_cards.py apply --confirm
python3 scripts/localize_skill_cards.py restore "/absolute/path/to/record.json"
python3 scripts/localize_skill_cards.py restore "/absolute/path/to/record.json" --confirm
```

常用选项：

| 选项 | 适用命令 | 作用 |
| --- | --- | --- |
| `--codex-home DIR` | 所有命令 | 使用另一套 Codex 状态根目录 |
| `--include-managed` | `scan`、`plan`、`validate`、`apply`、`restore` | 将 system skill 和插件缓存加入扫描范围 |
| `--translations FILE` | `plan`、`apply` | 使用指定的批准 catalog |
| `--confirm` | `apply`、`restore` | 确认执行写入 |

命令输出 JSON，便于人工审阅或自动化处理：

- `scan` 输出发现结果。
- `plan` 输出每个目标的操作和校验结果；缺少批准译文时为 `needs-approval`。
- `validate` 输出计划，并在存在 `error` 或 `needs-approval` 时返回非零状态码。
- `apply --confirm` 要求计划完全解决；成功后输出 `status`、`plan` 和 `record`。

`apply --confirm` 是整批操作：计划中只要仍有 `error` 或 `needs-approval`，就不会写入任何目标。

## 扫描范围

工具优先读取 `CODEX_HOME`；未设置时使用用户目录下的 `.codex`。一次运行只处理一套状态根目录。

| 范围 | 默认路径 | 启用方式 |
| --- | --- | --- |
| 个人 skill | `CODEX_HOME/skills`，排除 `.system` | 默认扫描 |
| system skill | `CODEX_HOME/skills/.system` | `--include-managed` |
| 插件缓存 | `CODEX_HOME/plugins/cache` | `--include-managed` |
| 临时插件 | `CODEX_HOME/.tmp/plugins` | 始终排除 |

如果要扫描 OpenAI 文档列出的用户级 `$HOME/.agents/skills`，请单独运行：

```bash
python3 scripts/localize_skill_cards.py scan --codex-home "$HOME/.agents"
```

启用 `--include-managed` 后，请重新审阅完整的 `plan`。受管目录可能包含大量 skill。

## 手动安装

将仓库中的以下目录完整复制到 Codex skill 目录：

```text
skills/localize-skill-cards/
```

目标目录应保留以下内容：

```text
<CODEX_HOME>/skills/localize-skill-cards/
├── SKILL.md
├── agents/openai.yaml
├── references/approved-translations.json
└── scripts/
    ├── localize_skill_cards.py
    └── test_localize_skill_cards.py
```

不要把整个仓库复制成一个 skill。安装后如果 Codex 没有自动发现该 skill，请重新启动 Codex。

关于 skill 的发现和显式调用，请参阅 [OpenAI Codex skill 文档](https://learn.chatgpt.com/docs/build-skills)。

## 批准译文与本地状态

默认批准 catalog 位于：

```text
<CODEX_HOME>/localize-skill-cards/approved-translations.json
```

最小结构如下：

```json
{
  "version": 1,
  "selection_rule": "highest numeric plugin version, then newest mtime, then lexical version name",
  "translations": {
    "personal/example-skill": "创建或更新 Codex 技能，并维护必要的说明与配套资源"
  }
}
```

stable ID 的形式为：

- `personal/name`
- `system/name`
- `plugin/vendor/package/skill`

仓库中的 [`references/approved-translations.json`](skills/localize-skill-cards/references/approved-translations.json) 只是空 schema/template，不会被默认加载，也不包含本机 skill 清单或译文。

成功执行 `apply --confirm` 后，恢复记录保存在：

```text
<CODEX_HOME>/localize-skill-cards/runs/
```

记录包含恢复所需的旧值、新值和本机路径，仅用于本地恢复，不应提交或分享。请使用 `apply --confirm` 成功输出的 `record` 字段作为实际记录路径，不要照抄示例路径。

## 译文要求

`plan` 会为每个目标标记以下操作：

| action | 含义 |
| --- | --- |
| `skip` | 启发式判断简介已经是中文；仍建议人工抽查 |
| `change` | 存在结构有效且已批准的中文译文 |
| `needs-approval` | 没有本地批准译文，不会自动写入 |
| `error` | 文件结构、路径或译文不符合约束 |

新简介必须满足：

- 是单行字符串，并包含至少一个中文字符。
- 长度为 25–64 个字符。
- 保留原文中的 `Codex`、`GitHub`、`PR`、`CI`、`API`，以及全大写或内部大写标识符。
- 不包含换行、反引号、尖括号、反斜杠、美元符号等不安全字符。

可能的 Title Case 产品名会产生 `warning`，需要人工确认是否应保留原文。

## 安全边界

- `scan`、`plan`、`validate` 和不带 `--confirm` 的 `restore` 只读。
- `apply --confirm` 会拒绝仍含 `error` 或 `needs-approval` 的计划。
- 只替换唯一的单行 `interface.short_description`，保留目标文件其他内容。
- 写入使用同目录临时文件、`fsync` 和 `os.replace`；发生可捕获异常时，工具会尝试回滚本次已写入的目标。
- 工具会校验目标范围、stable ID、符号链接、文本漂移和输入大小。
- 运行目录使用仅当前用户可访问的权限；不要使用提升权限运行，也不要使用其他用户可写的 `CODEX_HOME`。

## 已知限制

- YAML 解析器有意保持保守；合法的单引号、无引号、多行 scalar 或行尾注释也可能被拒绝。
- 工具会跳过目标目录或路径组件包含符号链接的目标。
- 批准译文只绑定 stable ID，不绑定原始英文简介的 hash；原文变化后应重新人工审阅。
- `SIGKILL`、进程崩溃或断电期间，不保证整批修改完全恢复；工具不宣称这是 crash-safe 事务。
- 插件 stable ID 依赖当前 Codex 插件缓存目录约定，非标准布局可能被跳过。
- 结构校验不能保证译文风格、语义或商标使用正确，最终质量由人工审批负责。
- 项目以源码形式分发，不是 Python package，也不是原生 Codex plugin。

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

运行测试：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover \
  -s skills/localize-skill-cards/scripts \
  -p 'test_*.py' \
  -v
```

## 许可证

[MIT](LICENSE)
