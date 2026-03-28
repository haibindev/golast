<div align="center">

# golast

**Recover your Codex session after compaction crashes.**

[![Python](https://img.shields.io/badge/Python-3.10+-3776AB?logo=python&logoColor=white)](scripts/resume_last_request.py)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![GitHub stars](https://img.shields.io/github/stars/haibindev/golast?style=social)](https://github.com/haibindev/golast)

**If this tool saved your session, please give it a star!**

[![Star this repo](https://img.shields.io/badge/%E2%AD%90_Star_this_repo-yellow?style=for-the-badge&logo=github)](https://github.com/haibindev/golast)

[中文说明](#中文说明)

</div>

---

Codex periodically runs background compaction ("auto-compacting background context"). When it fails, you get:

```
Error running remote compact task: stream disconnected before completion:
error sending request for url (https://chatgpt.com/backend-api/codex/responses/compact)
```

**golast** is a Codex global skill that recovers the last actionable request from a crashed or compacted session, so you can pick up exactly where you left off.

> No more copy-pasting from memory. No more re-explaining the task.
> Just type `golast` and keep going.

---

## The Problem

1. You're deep into a multi-step task with Codex
2. Codex starts "auto-compacting background context"
3. The compaction request fails mid-stream — network timeout, API hiccup, server error
4. Session is wiped. Codex has no memory of what you were doing
5. You stare at a blank prompt, trying to reconstruct the last 30 minutes

This happens frequently enough to be a real productivity killer. `golast` fixes it.

## How It Works

```
You type: golast
            │
            ▼
  ┌──────────────────────────────────────┐
  │  resume_last_request.py              │
  │                                      │
  │  1. Find Codex state DB (~/.codex/)  │
  │  2. Locate previous session thread   │
  │  3. Parse conversation timeline      │
  │  4. Resolve the last real request    │
  │     (skip "ok", "continue", etc.)    │
  │  5. Expand context if ambiguous      │
  └──────────────────────────────────────┘
            │
            ▼
  Codex resumes the recovered request
```

The script reads Codex's local SQLite state database, walks the conversation timeline, and intelligently resolves what you actually asked — even if your last message was just "ok", "sure", or a brief supplement.

## Features

- **Smart request resolution** — Skips low-signal messages ("continue", "go on", "keep going") and traces back to the real request
- **Agreement detection** — If you said "ok" or "agreed", recovers the assistant's suggestion you agreed to
- **Supplement merging** — If your last message was a supplement (e.g., "additionally…"), merges it with the previous context
- **Ambiguity expansion** — When the recovered request contains vague references ("do that", "same as above", "that plan"), automatically walks upward to find the concrete explanation
- **Decision basis tracking** — Recovers earlier user requirements that define selection criteria (e.g., comparing backends before choosing one)
- **Bilingual** — Handles both English and Chinese conversation patterns

## Install

```bash
git clone https://github.com/haibindev/golast.git ~/.codex/skills/golast
```

That's it. Codex auto-detects the skill on next launch.

## Usage

After a compaction crash:

1. **Stay in the same workspace** where the crashed session was running
2. **Start a new Codex session** (the crashed one can no longer continue)
3. **Type `golast`** to invoke the skill

```
golast
```

Codex will automatically recover the previous session's last actionable request and **continue from it immediately** — no manual copy-paste, no re-explaining, no context reconstruction.

### CLI Options

```
--cwd <path>        Workspace path (default: current directory)
--scope <mode>      Search scope: auto | exact | repo | tree (default: auto)
--skip-current      Skip the current thread (default: true)
--recent <n>        Number of recent user messages to include (default: 3)
--lookback <n>      Timeline entries for context expansion (default: 6)
--format <fmt>      Output format: text | json (default: text)
--codex-home <path> Codex data directory (default: ~/.codex)
```

### Output Fields (JSON)

| Field | Description |
|-------|-------------|
| `resolved_request` | The best request to continue from |
| `literal_last_user_message` | The exact last user message |
| `resolved_source` | Where the request came from (user / assistant suggestion / supplement) |
| `needs_more_context` | Whether the recovered request is still ambiguous |
| `ambiguity_hints` | Why the request may be ambiguous |
| `supporting_context` | Nearby earlier entries for context |
| `decision_basis_message` | Earlier user requirement that defines selection criteria |
| `context_expanded_upward` | Whether the script had to walk upward for explanation |

## Requirements

- Python 3.10+
- Codex CLI installed (with `~/.codex/state_5.sqlite` present)
- No external dependencies — stdlib only

## Contributing

- [Report a bug](https://github.com/haibindev/golast/issues) or suggest a feature
- PRs welcome
- Star the repo if it saved your session

## License

[MIT](LICENSE)

## Author

**haibindev** — [https://haibindev.github.io/](https://haibindev.github.io/)

---

<div id="中文说明"></div>

## 中文说明

**golast 帮你在 Codex 压缩崩溃后恢复上一次会话。**

### 问题

Codex 会定期执行"自动压缩背景信息"。当压缩请求中途断开时，会报错：

```
Error running remote compact task: stream disconnected before completion:
error sending request for url (https://chatgpt.com/backend-api/codex/responses/compact)
```

### 解决方案

压缩崩溃后：

1. **留在原工作区**（崩溃的会话已无法继续）
2. **新开一个 Codex 会话**
3. **输入 `golast`** 触发技能

```
golast
```

自动恢复上一次会话的最后一个可执行请求，**立即继续工作** — 无需手动回忆、无需重新描述任务、无需重建上下文。

### 工作原理

1. 读取 Codex 本地 SQLite 状态数据库
2. 定位当前工作区的上一次会话线程
3. 解析对话时间线，智能识别最后的真实请求
4. 跳过"ok"、"继续"等低信号消息，追溯到实际任务
5. 对模糊引用（"三端"、"这个方案"等）自动向上扩展上下文

### 安装

```bash
git clone https://github.com/haibindev/golast.git ~/.codex/skills/golast
```

Codex 下次启动时自动识别。

### 特性

- **智能请求解析** — 跳过"继续"、"好的"等低信号消息，追溯真实请求
- **同意识别** — 如果最后一条消息是"ok"或"同意"，恢复你同意的 assistant 建议
- **补充合并** — 如果最后一条消息是"补充：…"，自动合并前文上下文
- **歧义扩展** — 遇到"三端"、"这个方案"等模糊引用，自动向上查找具体说明
- **决策基础追踪** — 恢复定义候选集或选择标准的早期用户需求
- **中英双语** — 同时处理中文和英文对话模式
- **零依赖** — 纯 Python 标准库，无需安装额外包

---

<div align="center">

个人主页：**[haibindev.github.io](https://haibindev.github.io/)**

</div>
