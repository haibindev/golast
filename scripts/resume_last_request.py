#!/usr/bin/env python3
"""Recover the previous session's actionable request for the current workspace."""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable


IGNORED_EXACT_MESSAGES = {
    "codex",
    "claude",
    "assistant",
}

IGNORED_PREFIXES = (
    "# AGENTS.md instructions for ",
    "<turn_aborted>",
)

LOW_SIGNAL_MESSAGES = {
    "continue",
    "go on",
    "keep going",
    "resume",
    "carry on",
    "继续",
    "继续吧",
    "接着",
    "ji xu",
    "jixu",
    "ji xu ba",
}

AGREEMENT_MESSAGES = {
    "ok",
    "okay",
    "yes",
    "yep",
    "sure",
    "sounds good",
    "agreed",
    "do it",
    "go ahead",
    "好",
    "好的",
    "hao",
    "haode",
    "同意",
    "tongyi",
    "可以",
    "keyi",
    "行",
    "xing",
}

SUPPLEMENT_PREFIXES = (
    "补充",
    "补一下",
    "补充说明",
    "再补充",
    "另外",
    "还有",
    "顺便",
    "ps",
    "p.s",
    "additional",
    "additionally",
    "one more thing",
)

REFERENCE_MARKERS = (
    "do that",
    "do this",
    "that change",
    "this change",
    "same as above",
    "above",
    "that plan",
    "this plan",
    "这样",
    "这个",
    "那个",
    "上面",
    "上述",
    "前面",
    "之前",
    "同上",
    "该方案",
    "这个方案",
    "按这个",
    "按上面",
)

CONCRETE_MARKERS = (
    "/",
    "\\",
    "://",
    ".md",
    ".py",
    ".ts",
    ".js",
    ".cpp",
    ".h",
    "`",
    "fix",
    "update",
    "read",
    "implement",
    "refactor",
    "repair",
    "recover",
    "修复",
    "更新",
    "读取",
    "实现",
    "重构",
    "恢复",
)

AMBIGUOUS_COUNT_TERMS = (
    "两端",
    "三端",
    "两种",
    "三种",
    "两个",
    "三个",
    "这两种",
    "这三种",
    "这两个",
    "这三个",
    "那两种",
    "那三种",
    "那两个",
    "那三个",
)

RTMP_BACKEND_MARKERS = (
    "librtmp",
    "ffmpeg",
    "libavformat",
    "zlmediakit",
    "mediamtx",
    "srs",
)

SELECTION_MARKERS = (
    "选",
    "选择",
    "选一个",
    "选型",
    "择优",
    "compare",
    "comparison",
    "choose",
    "select",
    "pick",
    "融合",
    "整合",
    "对比",
    "比较",
)

UNCERTAINTY_MARKERS = (
    "如果不是",
    "如果我理解错了",
    "我理解为",
    "我先按",
    "不确定",
    "unclear",
    "assuming",
    "i assume",
    "likely",
    "probably",
)

NORMALIZED_LOW_SIGNAL_MESSAGES = {
    "".join(ch for ch in item.strip().lower() if ch.isalnum()) for item in LOW_SIGNAL_MESSAGES
}

NORMALIZED_AGREEMENT_MESSAGES = {
    "".join(ch for ch in item.strip().lower() if ch.isalnum()) for item in AGREEMENT_MESSAGES
}

NORMALIZED_SUPPLEMENT_PREFIXES = {
    "".join(ch for ch in item.strip().lower() if ch.isalnum()) for item in SUPPLEMENT_PREFIXES
}


@dataclass
class ThreadRecord:
    id: str
    cwd: str
    title: str
    first_user_message: str
    updated_at: int
    rollout_path: str


@dataclass
class TimelineEntry:
    role: str
    text: str


@dataclass
class ResolvedRequest:
    literal_last_user_message: str
    resolved_request: str
    resolved_source: str
    assistant_message_before_last_user: str
    previous_context_message: str
    decision_basis_message: str
    resolved_index: int
    context_anchor_index: int
    needs_more_context: bool
    ambiguity_hints: tuple[str, ...]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Recover the previous session's actionable request for the current workspace"
    )
    parser.add_argument("--cwd", default=os.getcwd(), help="Current workspace path")
    parser.add_argument(
        "--scope",
        choices=("auto", "exact", "repo", "tree"),
        default="auto",
        help="exact=current cwd, repo=git root, tree=child workspaces, auto=exact then repo then tree",
    )
    parser.add_argument(
        "--skip-current",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Skip the current thread and inspect the previous one",
    )
    parser.add_argument("--recent", type=int, default=3, help="How many recent user messages to include")
    parser.add_argument(
        "--lookback",
        type=int,
        default=6,
        help="How many timeline entries to include when extra context is needed",
    )
    parser.add_argument("--format", choices=("text", "json"), default="text", help="Output format")
    parser.add_argument(
        "--codex-home",
        default=os.environ.get("CODEX_HOME", str(Path.home() / ".codex")),
        help="Codex data directory",
    )
    return parser.parse_args()


def normalize_path(path_str: str) -> str:
    if path_str.startswith("\\\\?\\UNC\\"):
        path_str = "\\\\" + path_str[len("\\\\?\\UNC\\") :]
    elif path_str.startswith("\\\\?\\"):
        path_str = path_str[4:]
    expanded = os.path.expanduser(path_str)
    normalized = os.path.normpath(expanded)
    return os.path.normcase(normalized)


def compact_phrase(text: str) -> str:
    lowered = text.strip().lower()
    stripped = []
    for ch in lowered:
        if ch.isalnum():
            stripped.append(ch)
    return "".join(stripped)


def git_root_for(cwd: str) -> str | None:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=cwd,
            capture_output=True,
            check=True,
            text=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None

    root = completed.stdout.strip()
    return root or None


def search_targets(cwd: str, scope: str) -> list[tuple[str, str]]:
    targets: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()

    def add_target(label: str, candidate: str | None) -> None:
        if not candidate:
            return
        key = (label, normalize_path(candidate))
        if key in seen:
            return
        seen.add(key)
        targets.append((label, candidate))

    repo_root = git_root_for(cwd)
    if scope == "auto":
        add_target("exact", cwd)
        add_target("repo", repo_root)
        add_target("tree", cwd)
        return targets

    if scope == "exact":
        add_target("exact", cwd)
    elif scope == "repo":
        add_target("repo", repo_root)
    elif scope == "tree":
        add_target("tree", cwd)
    return targets


def rows_to_threads(rows: Iterable[tuple[object, ...]]) -> list[ThreadRecord]:
    return [
        ThreadRecord(
            id=str(row[0]),
            cwd=str(row[1]),
            title=str(row[2] or ""),
            first_user_message=str(row[3] or ""),
            updated_at=int(row[4]),
            rollout_path=str(row[5] or ""),
        )
        for row in rows
    ]


def load_recent_threads(conn: sqlite3.Connection, limit: int = 2000) -> list[ThreadRecord]:
    query = """
        SELECT id, cwd, title, first_user_message, updated_at, rollout_path
        FROM threads
        WHERE rollout_path IS NOT NULL AND rollout_path != ''
        ORDER BY updated_at DESC
        LIMIT ?
    """
    rows = conn.execute(query, (limit,)).fetchall()
    return rows_to_threads(rows)


def load_threads_for_cwd(conn: sqlite3.Connection, cwd: str) -> list[ThreadRecord]:
    normalized = normalize_path(cwd)
    return [thread for thread in load_recent_threads(conn) if normalize_path(thread.cwd) == normalized]


def load_threads_for_tree(conn: sqlite3.Connection, cwd: str) -> list[ThreadRecord]:
    normalized = normalize_path(cwd)
    prefix = normalized.rstrip("\\/") + os.sep
    return [
        thread
        for thread in load_recent_threads(conn)
        if normalize_path(thread.cwd).startswith(prefix)
    ]


def clean_message(message: str) -> str:
    normalized = message.replace("\r\n", "\n").strip()
    if not normalized:
        return ""

    lowered = normalized.lower()
    if lowered in IGNORED_EXACT_MESSAGES:
        return ""

    for prefix in IGNORED_PREFIXES:
        if normalized.startswith(prefix):
            return ""

    return normalized


def assistant_text_from_payload(payload: dict[str, object]) -> str:
    parts: list[str] = []
    for item in payload.get("content") or []:
        if isinstance(item, dict) and item.get("type") == "output_text":
            parts.append(str(item.get("text", "")))
    return "\n".join(part for part in parts if part).strip()


def user_text_from_payload(payload: dict[str, object]) -> str:
    parts: list[str] = []
    for item in payload.get("content") or []:
        if isinstance(item, dict) and item.get("type") == "input_text":
            parts.append(str(item.get("text", "")))
    return "\n".join(part for part in parts if part).strip()


def parse_timeline(rollout_path: Path) -> list[TimelineEntry]:
    timeline: list[TimelineEntry] = []
    fallback_users: list[str] = []

    with rollout_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            record = json.loads(line)
            payload = record.get("payload") or {}

            if record.get("type") == "event_msg" and payload.get("type") == "user_message":
                cleaned = clean_message(str(payload.get("message", "")))
                if cleaned:
                    timeline.append(TimelineEntry(role="user", text=cleaned))
                continue

            if record.get("type") != "response_item":
                continue

            if payload.get("type") != "message":
                continue

            role = payload.get("role")
            if role == "assistant":
                text = assistant_text_from_payload(payload)
                if text.strip():
                    timeline.append(TimelineEntry(role="assistant", text=text.strip()))
            elif role == "user":
                text = clean_message(user_text_from_payload(payload))
                if text:
                    fallback_users.append(text)

    if any(entry.role == "user" for entry in timeline):
        return dedupe_timeline(timeline)

    for text in fallback_users:
        timeline.append(TimelineEntry(role="user", text=text))
    return dedupe_timeline(timeline)


def dedupe_timeline(entries: Iterable[TimelineEntry]) -> list[TimelineEntry]:
    result: list[TimelineEntry] = []
    last_key: tuple[str, str] | None = None
    for entry in entries:
        key = (entry.role, entry.text)
        if key == last_key:
            continue
        result.append(entry)
        last_key = key
    return result


def is_low_signal_message(message: str) -> bool:
    compact = compact_phrase(message)
    if not compact:
        return True
    if compact in NORMALIZED_LOW_SIGNAL_MESSAGES:
        return True
    return len(compact) <= 4


def is_agreement_message(message: str) -> bool:
    compact = compact_phrase(message)
    if not compact:
        return False
    return compact in NORMALIZED_AGREEMENT_MESSAGES


def is_supplement_message(message: str) -> bool:
    compact = compact_phrase(message)
    if not compact:
        return False
    return any(compact.startswith(prefix) for prefix in NORMALIZED_SUPPLEMENT_PREFIXES)


def recent_user_messages(timeline: list[TimelineEntry], count: int) -> list[str]:
    users = [entry.text for entry in timeline if entry.role == "user"]
    if count <= 0:
        return []
    return users[-count:]


def last_meaningful_conversation(timeline: list[TimelineEntry]) -> TimelineEntry:
    for entry in reversed(timeline):
        text = entry.text.strip()
        if text:
            return entry
    return TimelineEntry(role="unknown", text="")


def find_previous_context_entry(
    timeline: list[TimelineEntry], before_index: int
) -> tuple[int, TimelineEntry] | None:
    for index in range(before_index - 1, -1, -1):
        entry = timeline[index]
        text = entry.text.strip()
        if not text:
            continue
        if entry.role == "assistant":
            return index, entry
        if entry.role == "user":
            if is_low_signal_message(text) or is_agreement_message(text) or is_supplement_message(text):
                continue
            return index, entry
    return None


def find_previous_user_decision_entry(
    timeline: list[TimelineEntry], before_index: int, max_scan: int = 32
) -> tuple[int, TimelineEntry] | None:
    floor = max(0, before_index - max_scan)
    for index in range(before_index - 1, floor - 1, -1):
        entry = timeline[index]
        if entry.role != "user":
            continue
        text = entry.text.strip()
        if not text:
            continue
        if is_backend_decision_input(text):
            return index, entry
    return None


def merge_with_supplement(previous_text: str, supplement_text: str) -> str:
    if not previous_text:
        return supplement_text
    return f"{previous_text}\n\n补充要求：\n{supplement_text}"


def contains_numbered_list(text: str) -> bool:
    return re.search(r"(^|\n)\s*(?:[1-9][\.\)、]|[-*])\s+", text) is not None


def count_backend_markers(text: str) -> int:
    lower = text.lower()
    return sum(1 for marker in RTMP_BACKEND_MARKERS if marker in lower)


def has_backend_candidate_list(text: str) -> bool:
    return count_backend_markers(text) >= 2


def is_backend_decision_input(text: str) -> bool:
    lower = text.lower()
    if not has_backend_candidate_list(text):
        return False
    has_selection_marker = any(marker in lower for marker in SELECTION_MARKERS if marker.isascii()) or any(
        marker in text for marker in SELECTION_MARKERS if not marker.isascii()
    )
    return has_selection_marker


def message_has_concrete_anchor(message: str) -> bool:
    text = message.strip()
    lower = text.lower()
    if contains_numbered_list(text):
        return True
    if has_backend_candidate_list(text):
        return True
    return any(marker in lower for marker in CONCRETE_MARKERS if marker.isascii()) or any(
        marker in text for marker in CONCRETE_MARKERS if not marker.isascii()
    )


def extract_ambiguity_hints(message: str) -> tuple[str, ...]:
    compact = compact_phrase(message)
    if not compact:
        return ("empty",)

    text = message.strip()
    lower = text.lower()
    hints: list[str] = []

    if is_low_signal_message(message):
        hints.append("low_signal")
    if is_agreement_message(message):
        hints.append("agreement")

    has_reference_marker = any(marker in lower for marker in REFERENCE_MARKERS if marker.isascii()) or any(
        marker in text for marker in REFERENCE_MARKERS if not marker.isascii()
    )
    if has_reference_marker:
        hints.append("reference")

    if any(marker in text for marker in AMBIGUOUS_COUNT_TERMS):
        hints.append("count_shorthand")

    if "后端" in text and count_backend_markers(text) < 2:
        hints.append("backend_choice")

    if "方案" in text or "路线" in text:
        hints.append("plan_reference")

    has_uncertainty_marker = any(marker in lower for marker in UNCERTAINTY_MARKERS if marker.isascii()) or any(
        marker in text for marker in UNCERTAINTY_MARKERS if not marker.isascii()
    )
    if has_uncertainty_marker:
        hints.append("uncertainty")

    deduped: list[str] = []
    for hint in hints:
        if hint not in deduped:
            deduped.append(hint)
    return tuple(deduped)


def combine_ambiguity_hints(*messages: str) -> tuple[str, ...]:
    combined: list[str] = []
    for message in messages:
        for hint in extract_ambiguity_hints(message):
            if hint not in combined:
                combined.append(hint)
    return tuple(combined)


def merge_with_decision_basis(decision_basis_text: str, assistant_text: str) -> str:
    if not decision_basis_text:
        return assistant_text
    if not assistant_text:
        return decision_basis_text
    return f"{decision_basis_text}\n\n当前执行切口：\n{assistant_text}"


def message_needs_more_context(message: str) -> bool:
    ambiguity_hints = extract_ambiguity_hints(message)
    if "empty" in ambiguity_hints:
        return True
    if "low_signal" in ambiguity_hints or "agreement" in ambiguity_hints or "uncertainty" in ambiguity_hints:
        return True

    text = message.strip()
    has_explanatory_list = contains_numbered_list(text) or count_backend_markers(text) >= 2
    if "count_shorthand" in ambiguity_hints and not has_explanatory_list:
        return True
    if "backend_choice" in ambiguity_hints and not has_explanatory_list:
        return True

    has_concrete_anchor = message_has_concrete_anchor(message)
    if "reference" in ambiguity_hints or "plan_reference" in ambiguity_hints:
        return not has_concrete_anchor
    return False


def entry_resolves_ambiguity(entry_text: str, ambiguity_hints: tuple[str, ...]) -> bool:
    if not ambiguity_hints:
        return False

    text = entry_text.strip()
    lower = text.lower()
    backend_count = count_backend_markers(text)
    has_backend_enumeration = backend_count >= 2 or (contains_numbered_list(text) and "后端" in text)

    if "count_shorthand" in ambiguity_hints and (contains_numbered_list(text) or has_backend_enumeration):
        return True

    if "backend_choice" in ambiguity_hints:
        if is_backend_decision_input(text):
            return True
        if has_backend_enumeration:
            return True
        if backend_count >= 2 and ("rtmp" in lower or "推流" in text or "拉流" in text):
            return True

    if "reference" in ambiguity_hints or "plan_reference" in ambiguity_hints:
        if message_has_concrete_anchor(text):
            return True

    if "uncertainty" in ambiguity_hints and message_has_concrete_anchor(text):
        return True

    return False


def find_explanatory_context_index(
    timeline: list[TimelineEntry], anchor_index: int, ambiguity_hints: tuple[str, ...], max_scan: int
) -> int | None:
    if anchor_index < 0 or not ambiguity_hints:
        return None

    floor = max(0, anchor_index - max_scan)
    best_index: int | None = None
    for index in range(anchor_index, floor - 1, -1):
        entry = timeline[index]
        if not entry.text.strip():
            continue
        if entry_resolves_ambiguity(entry.text, ambiguity_hints):
            if "backend_choice" in ambiguity_hints and entry.role == "user" and is_backend_decision_input(entry.text):
                return index
            best_index = index
            if "backend_choice" not in ambiguity_hints and (
                contains_numbered_list(entry.text) or count_backend_markers(entry.text) >= 2
            ):
                break
    return best_index


def collect_supporting_context(
    timeline: list[TimelineEntry],
    resolved_index: int,
    lookback: int,
    needs_more_context: bool,
    context_anchor_index: int | None,
    ambiguity_hints: tuple[str, ...],
) -> tuple[list[dict[str, str]], bool]:
    if resolved_index < 0 or not timeline:
        return [], False

    anchor_index = resolved_index if context_anchor_index is None or context_anchor_index < 0 else context_anchor_index
    base_lookback = 2
    effective_lookback = lookback if needs_more_context else min(base_lookback, lookback)
    start = max(0, anchor_index - effective_lookback)
    context_expanded_upward = False

    if needs_more_context:
        explanatory_index = find_explanatory_context_index(
            timeline,
            anchor_index,
            ambiguity_hints,
            max(max(effective_lookback * 4, 12), effective_lookback),
        )
        if explanatory_index is not None and explanatory_index < start:
            start = explanatory_index
            context_expanded_upward = True

    supporting_context = [{"role": entry.role, "text": entry.text} for entry in timeline[start : resolved_index + 1]]
    return supporting_context, context_expanded_upward


def resolve_request(
    timeline: list[TimelineEntry], first_user_message: str
) -> ResolvedRequest:
    users = [entry for entry in timeline if entry.role == "user"]
    if not users:
        fallback = clean_message(first_user_message)
        return ResolvedRequest(
            literal_last_user_message=fallback,
            resolved_request=fallback,
            resolved_source="first_user_message",
            assistant_message_before_last_user="",
            previous_context_message="",
            decision_basis_message="",
            resolved_index=-1,
            context_anchor_index=-1,
            needs_more_context=message_needs_more_context(fallback),
            ambiguity_hints=extract_ambiguity_hints(fallback),
        )

    last_user = users[-1].text
    last_user_index = len(timeline) - 1
    for index in range(len(timeline) - 1, -1, -1):
        entry = timeline[index]
        if entry.role == "user" and entry.text == last_user:
            last_user_index = index
            break

    if is_agreement_message(last_user):
        for previous in range(last_user_index - 1, -1, -1):
            assistant_entry = timeline[previous]
            if assistant_entry.role == "assistant":
                return ResolvedRequest(
                    literal_last_user_message=last_user,
                    resolved_request=assistant_entry.text,
                    resolved_source="assistant_suggestion",
                    assistant_message_before_last_user=assistant_entry.text,
                    previous_context_message=assistant_entry.text,
                    decision_basis_message="",
                    resolved_index=previous,
                    context_anchor_index=previous,
                    needs_more_context=message_needs_more_context(assistant_entry.text),
                    ambiguity_hints=extract_ambiguity_hints(assistant_entry.text),
                )

    if is_supplement_message(last_user):
        previous_context = find_previous_context_entry(timeline, last_user_index)
        if previous_context is not None:
            previous_index, previous_entry = previous_context
            assistant_message = previous_entry.text if previous_entry.role == "assistant" else ""
            decision_basis_message = ""
            merged_context = previous_entry.text
            context_anchor_index = previous_index

            if previous_entry.role == "assistant":
                decision_basis = find_previous_user_decision_entry(timeline, previous_index)
                if decision_basis is not None:
                    decision_index, decision_entry = decision_basis
                    decision_basis_message = decision_entry.text
                    merged_context = merge_with_decision_basis(decision_entry.text, previous_entry.text)
                    context_anchor_index = decision_index

            merged = merge_with_supplement(merged_context, last_user)
            return ResolvedRequest(
                literal_last_user_message=last_user,
                resolved_request=merged,
                resolved_source=(
                    f"supplement_plus_decision_basis_and_previous_{previous_entry.role}"
                    if decision_basis_message
                    else f"supplement_plus_previous_{previous_entry.role}"
                ),
                assistant_message_before_last_user=assistant_message,
                previous_context_message=merged_context,
                decision_basis_message=decision_basis_message,
                resolved_index=last_user_index,
                context_anchor_index=context_anchor_index,
                needs_more_context=(
                    message_needs_more_context(merged_context)
                    or message_needs_more_context(last_user)
                ),
                ambiguity_hints=combine_ambiguity_hints(merged_context, last_user),
            )

    resolved = last_user
    resolved_index = last_user_index
    if is_low_signal_message(last_user):
        for candidate in reversed(users[:-1]):
            if not is_low_signal_message(candidate.text) and not is_agreement_message(candidate.text):
                resolved = candidate.text
                for index in range(len(timeline) - 1, -1, -1):
                    entry = timeline[index]
                    if entry.role == "user" and entry.text == candidate.text:
                        resolved_index = index
                        break
                break
    else:
        for index in range(len(timeline) - 1, -1, -1):
            entry = timeline[index]
            if entry.role == "user" and entry.text == last_user:
                resolved_index = index
                break

    return ResolvedRequest(
        literal_last_user_message=last_user,
        resolved_request=resolved,
        resolved_source="user_message",
        assistant_message_before_last_user="",
        previous_context_message="",
        decision_basis_message="",
        resolved_index=resolved_index,
        context_anchor_index=resolved_index,
        needs_more_context=message_needs_more_context(resolved),
        ambiguity_hints=extract_ambiguity_hints(resolved),
    )


def find_previous_thread(
    codex_home: Path, cwd: str, scope: str, skip_current: bool
) -> tuple[str, str, ThreadRecord] | None:
    state_db = codex_home / "state_5.sqlite"
    if not state_db.exists():
        raise FileNotFoundError(f"state db not found: {state_db}")

    normalized_cwd = normalize_path(cwd)
    with sqlite3.connect(state_db) as conn:
        for label, target in search_targets(cwd, scope):
            threads = load_threads_for_tree(conn, target) if label == "tree" else load_threads_for_cwd(conn, target)
            valid_threads = [
                thread for thread in threads if thread.rollout_path and Path(thread.rollout_path).exists()
            ]
            should_skip_first = (
                skip_current
                and label != "tree"
                and normalize_path(target) == normalized_cwd
            )
            if should_skip_first and valid_threads:
                valid_threads = valid_threads[1:]
            if valid_threads:
                return label, target, valid_threads[0]
    return None


def format_local_time(timestamp: int) -> str:
    return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")


def build_result(args: argparse.Namespace) -> dict[str, object]:
    codex_home = Path(args.codex_home)
    cwd = os.path.abspath(args.cwd)
    located = find_previous_thread(codex_home, cwd, args.scope, args.skip_current)
    if located is None:
        raise LookupError(
            f"No previous thread found for cwd={cwd}; scope={args.scope}; skip_current={args.skip_current}"
        )

    scope_used, matched_cwd, thread = located
    rollout_path = Path(thread.rollout_path)
    timeline = parse_timeline(rollout_path)
    resolved = resolve_request(timeline, thread.first_user_message)
    tail_entry = last_meaningful_conversation(timeline)
    supporting_context, context_expanded_upward = collect_supporting_context(
        timeline,
        resolved.resolved_index,
        args.lookback,
        resolved.needs_more_context,
        resolved.context_anchor_index,
        resolved.ambiguity_hints,
    )

    return {
        "status": "ok",
        "current_cwd": cwd,
        "scope_used": scope_used,
        "matched_cwd": matched_cwd,
        "thread_id": thread.id,
        "thread_title": thread.title,
        "updated_at_local": format_local_time(thread.updated_at),
        "rollout_path": thread.rollout_path,
        "literal_last_user_message": resolved.literal_last_user_message,
        "last_conversation_role": tail_entry.role,
        "last_conversation_content": tail_entry.text,
        "resolved_request": resolved.resolved_request,
        "resolved_source": resolved.resolved_source,
        "assistant_message_before_last_user": resolved.assistant_message_before_last_user,
        "previous_context_message": resolved.previous_context_message,
        "decision_basis_message": resolved.decision_basis_message,
        "needs_more_context": resolved.needs_more_context,
        "ambiguity_hints": list(resolved.ambiguity_hints),
        "context_expanded_upward": context_expanded_upward,
        "supporting_context": supporting_context,
        "recent_user_messages": recent_user_messages(timeline, args.recent),
    }


def render_text(result: dict[str, object]) -> str:
    recent = result.get("recent_user_messages") or []
    lines = [
        "Recovered previous session request",
        f"- matched workspace: {result['matched_cwd']}",
        f"- thread: {result['thread_title']} ({result['thread_id']})",
        f"- updated: {result['updated_at_local']}",
        f"- rollout: {result['rollout_path']}",
        f"- resolved source: {result['resolved_source']}",
        f"- needs more context: {result['needs_more_context']}",
        f"- context expanded upward: {result.get('context_expanded_upward', False)}",
        "",
        "Last conversation content:",
        f"[{result['last_conversation_role']}] {result['last_conversation_content'] or '(empty)'}",
        "",
        "Literal last user message:",
        str(result["literal_last_user_message"] or "(empty)"),
        "",
        "Resolved request:",
        str(result["resolved_request"] or "(empty)"),
    ]

    assistant_message = str(result.get("assistant_message_before_last_user") or "")
    if assistant_message:
        lines.extend(["", "Assistant message before the last user reply:", assistant_message])

    previous_context_message = str(result.get("previous_context_message") or "")
    if previous_context_message and previous_context_message != assistant_message:
        lines.extend(["", "Previous context message:", previous_context_message])

    decision_basis_message = str(result.get("decision_basis_message") or "")
    if decision_basis_message:
        lines.extend(["", "Decision basis message:", decision_basis_message])

    ambiguity_hints = result.get("ambiguity_hints") or []
    if ambiguity_hints:
        lines.extend(["", "Ambiguity hints:", ", ".join(str(item) for item in ambiguity_hints)])

    supporting_context = result.get("supporting_context") or []
    if supporting_context:
        lines.extend(["", "Supporting context:"])
        for index, entry in enumerate(supporting_context, start=1):
            role = str(entry.get("role", "unknown"))
            text = str(entry.get("text", ""))
            lines.append(f"{index}. [{role}] {text}")

    if recent:
        lines.extend(["", "Recent user messages:"])
        for index, message in enumerate(recent, start=1):
            lines.append(f"{index}. {message}")

    return "\n".join(lines)


def main() -> int:
    args = parse_args()
    try:
        result = build_result(args)
    except Exception as exc:  # noqa: BLE001
        if args.format == "json":
            print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False, indent=2))
        else:
            print(f"Recover failed: {exc}", file=sys.stderr)
        return 1

    if args.format == "json":
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(render_text(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
