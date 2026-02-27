#!/usr/bin/env python3
"""Save three research entries to memory."""

import sys
import os
sys.path.insert(0, os.path.expanduser("~/.claude/hooks"))

from memory_server import remember_this

# Entry 1: New hook event types
result1 = remember_this(
    content="Claude Code Feb 2026: 6 NEW hook event types beyond our current set. NEW: TeammateIdle (agent team validation, can block with exit 2), TaskCompleted (task quality gates, can block), WorktreeCreate (worktree creation, can block), WorktreeRemove (worktree removal), PostToolUseFailure (async failure recovery). PreCompact was already in list. Total: 17 hook event types. Full list: SessionStart, UserPromptSubmit, PreToolUse, PermissionRequest, PostToolUse, PostToolUseFailure, Notification, SubagentStart, SubagentStop, Stop, TeammateIdle, TaskCompleted, ConfigChange, WorktreeCreate, WorktreeRemove, PreCompact, SessionEnd. Source: code.claude.com/docs/en/hooks",
    context="Anthropic official documentation research for Torus framework gap analysis, session evolution-swarm-268, 2026-02-27",
    tags="type:learning,area:framework,research,session268,anthropic-docs,hooks"
)
print(f"Entry 1 saved: {result1}")

# Entry 2: Breaking change in PreToolUse format
result2 = remember_this(
    content="BREAKING CHANGE Feb 2026: PreToolUse hook output format changed. OLD (deprecated): {decision: 'deny', reason: '...'}. NEW REQUIRED: {hookSpecificOutput: {hookEventName: 'PreToolUse', permissionDecision: 'deny|allow|ask', permissionDecisionReason: '...'}}. Torus gates 2 and 5 PreToolUse hooks need migration to new format. Also: 3 handler types now exist - command (shell, exit 0/2), prompt (single-turn LLM Haiku, returns {ok: true/false, reason}), agent (multi-turn LLM with tools). Async hooks: add async: true field for background execution without blocking main loop.",
    context="Critical breaking change from Anthropic docs research, session evolution-swarm-268, 2026-02-27",
    tags="type:learning,area:framework,research,session268,anthropic-docs,hooks,breaking-change"
)
print(f"Entry 2 saved: {result2}")

# Entry 3: Agent Teams capabilities
result3 = remember_this(
    content="Claude Code Agent Teams (experimental Feb 2026): Enable with env CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1. Team config at ~/.claude/teams/{name}/config.json. Tasks at ~/.claude/tasks/{name}/. Two new hooks for team coordination: TeammateIdle (fires when teammate goes idle, exit 2 sends feedback and keeps working) and TaskCompleted (fires when task marked complete, exit 2 prevents completion). Display modes: in-process (default, Shift+Down to cycle) or split-panes (tmux/iTerm2). Limitations: no nested teams, no session resumption with in-process teammates, one team per session, no leadership transfer, no VS Code split panes.",
    context="Anthropic docs research for agent team capabilities, session evolution-swarm-268, 2026-02-27",
    tags="type:learning,area:framework,research,session268,anthropic-docs,agent-teams"
)
print(f"Entry 3 saved: {result3}")

# Extract memory IDs if successful
if isinstance(result1, dict) and 'memory_id' in result1:
    print(f"\nMemory ID 1: {result1['memory_id']}")
if isinstance(result2, dict) and 'memory_id' in result2:
    print(f"Memory ID 2: {result2['memory_id']}")
if isinstance(result3, dict) and 'memory_id' in result3:
    print(f"Memory ID 3: {result3['memory_id']}")
