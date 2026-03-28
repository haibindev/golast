---
name: "golast"
description: "Recover the previous session's last actionable request for the current workspace. Use when the user wants to continue the previous session, recover after compaction/crash, resume unfinished Codex work, or sends only `golast` or the skill link as shorthand for immediate recovery and continuation."
---

# Resume Last

Use this skill when the user wants to continue the previous session for the current workspace.
Invoke it as [$golast](C:/Users/hbstr/.codex/skills/golast/SKILL.md).

If the user's message is only `golast` or only the skill link, treat it as an execution request:
"recover the previous session for the current workspace and continue from it now".

## Quick start

1. Run the bundled script:
   - Path: `scripts/resume_last_request.py`
   - Recommended args: `--cwd <current-workspace> --format json`
   - Default `--scope auto`: search the exact `cwd`, then the git root, then the most recent child-workspace thread under the current workspace.

2. Read these output fields:
   - `resolved_request`: the best request to continue from now
   - `literal_last_user_message`: the literal last user message in the previous thread
   - `last_conversation_role`: the role of the last meaningful conversation item near the end of the thread
   - `last_conversation_content`: the last meaningful conversation item near the end of the thread
   - `resolved_source`: whether the request came from the previous user message or the previous assistant suggestion
   - `needs_more_context`: whether the last exchange still looks context-dependent
   - `ambiguity_hints`: why the script thinks the recovered request may still be ambiguous
   - `context_expanded_upward`: whether the script had to keep walking upward to find an explanation
   - `supporting_context`: nearby earlier entries, automatically expanded upward when terms such as `三端` / `三种` / `这个方案` still look under-specified
   - `assistant_message_before_last_user`: the previous assistant message when the last user message was an agreement such as `ok` or `agreed`
   - `previous_context_message`: the previous main context message when the last user message is only a supplement such as `补充：...`
   - `decision_basis_message`: the earlier user requirement that defines a candidate set or selection criteria, for example comparing `ZLMediaKit / MediaMTX / SRS` before choosing or fusing a third backend

3. Continue in the current session:
   - If the user wants execution, briefly state the recovered request and continue immediately.
   - Do not confuse "last user request" with "last conversation content". When the user asks what the previous session ended with, prefer `last_conversation_content`.
   - If the literal last user message is only a continuation cue such as `continue`, use `resolved_request` instead.
   - If the literal last user message is an agreement such as `ok`, `agreed`, `hao`, or `tongyi`, prefer the previous assistant action suggestion.
   - If the literal last user message starts with a supplement cue such as `补充`, `另外`, `还有`, `PS`, or `one more thing`, merge the previous main assistant or user context into `resolved_request`.
   - If `needs_more_context` is `true`, read `supporting_context` before deciding how to continue.
   - If `ambiguity_hints` is non-empty, treat `supporting_context` as required reading even when the main request already looks actionable.
   - If `decision_basis_message` is non-empty, prefer it over any narrower assistant shorthand when reconstructing the true user requirement.
   - If `context_expanded_upward` is `true`, trust the expanded `supporting_context` over your first guess about shorthand terms. This specifically covers cases where the recovered text says things like `三端`, `三种后端`, `这个方案`, or `按上面那样`, but the concrete explanation lives further up in the previous session.
   - If the user wants only the recovered text, return only `resolved_request`.

## Rules

- Ignore boilerplate such as `# AGENTS.md instructions ...`, `<turn_aborted>`, or a lone `codex`.
- Do not fabricate a previous request if nothing is found.
- Unless the user explicitly asks for text only, resume the work instead of stopping after recovery.
