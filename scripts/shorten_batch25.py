import json

entries = [
    {
        "id": "bab214321e4e9890",
        "text": "Tests passed: python -m pytest test_gates_tier1.py test_safety_destroy.py test_safety_critical_files.py -q 2>&1 | tail -20. Files modified this session: /home/crab/projects/zerobrain/test_safety_critical_files.py, /home/crab/projects/zerobrain/zerobrain/gates/ops_rate_limit.py, /home/crab/projects/zerobrain/zerobrain/gates/ops_workspace_isolation.py, /home/crab/projects/zerobrain/zerobrain/gates/ops_model_guard.py, /home/crab/projects/zerobrain/zerobrain/gates/ops_canary.py, /home/crab/projects/zerobrain/zerobrain/gates/ops_token_budget.py, /home/crab/projects/zerobrain/zerobrain/gates/security_injection.py, /home/crab/projects/zerobrain/zerobrain/gates/quality_code.py, /home/crab/projects/zerobrain/zerobrain/gates/safety_loop_escape.py, /home/crab/projects/zerobrain/zerobrain/gates/safety_depth_limit.py",
    },
    {
        "id": "47221da9800ea852",
        "text": "Pi-agent extension API capabilities: (1) promptGuidelines—per-tool behavioral rules injected each turn. (2) promptSnippet—one-liner in tools section. (3) resources_discover→promptPaths—inject context files at session start. (4) before_provider_request (v0.57.0)—intercept API calls, auto-inject memory context as RAG layer. Most powerful for automatic memory augmentation. Current setup: ~/.pi/agent/AGENTS.md (Torus rules). Next steps: add promptGuidelines to tools.ts, implement resources_discover, explore before_provider_request for automatic RAG.",
    },
    {
        "id": "15037377c3bb4a15",
        "text": "[zerobrain] Extension integration layer (2026-03-09): tool_gate.py—tool_execute_before hook with Enforcer (12 gates, tier order). On block: returns Response(BLOCKED). On warning: calls tool.add_progress(). loop_monitor.py—message_loop_start hook, initializes loop_start_time/iteration_count. monologue_reset.py—resets per-message. Install targets: agent-zero/python/extensions/. All import cleanly in Python 3.12. Response deferred in blocked_execute closure to only run at block-time.",
    },
    {
        "id": "19c07cde3e9fb2cf",
        "text": "[zerobrain] Installer/config created (2026-03-09): config/default.json (12 gates: 3 Tier1, 8 Tier2, 1 Tier3), config/__init__.py (load_config, get_gate_config, USER_CONFIG_PATH=~/.zerobrain/config.json), install.py (validate_agent_zero, create_symlinks for 5 extensions, setup_state_dir, setup_config, add_to_pythonpath via .pth), setup.py (setuptools, zerobrain-install entry_point), pyproject.toml (build-system, pytest). All verified: JSON valid, Python AST-clean, TOML valid. EXTENSION_MAP maps 5 sources to Agent Zero hooks.",
    },
    {
        "id": "5386973e2ccd80a5",
        "text": "Extension Pack System (Session 299): (1) Wrapped 3 imports in enforcer.py with try/except. (2) Added extension loading to _ensure_gates_loaded()—load_extensions, merge into GATE_MODULES/GATE_TOOL_MAP. (3) Fixed path resolution in enforcer.py/_get_gate_file_path() and hot_reload.py/_module_to_filepath()—check hooks/ first, fallback sys.path. (4) Git mv'd 11 non-core gates into 5 extension packs. (5) Created pack.json for security-pack, quality-pack. TODO: cost-ops-pack, team-pack, telemetry-pack pack.json, sys.path updates, registry slim, extension_loader.py, setup_extension.py.",
    },
    {
        "id": "e7037403fb9beec7",
        "text": "Infrastructure Audit (2026-02-09): 20 findings. HIGH: Boot state race (boot.py:136), no tests Gates 5-8, Gate 2 bypass via bash -c/eval/heredoc. MEDIUM: time string comparison (memory_server.py), stale .memory_last_queried, mcp.json untracked, Gate 1 no NotebookEdit, files_read cap=200 bypass, missing requirements.txt. LOW: .tmp files, SHA256 dedup, test cleanup race, PostToolUse timeout, Gate 6 mismatch, Gate 3 coverage, memory_stats dead code. INFO: no auth OK, empty matcher OK, 5 skills valid. 88 tests pass. Functional but Gate 2 bypass + boot race gaps.",
    },
    {
        "id": "4d854cedfb6139d0",
        "text": "Session 8 (2026-02-09): Audit V2 found 50 findings (0 critical, 6 high, 12 medium, 17 low, 15 info). All 5 critical Session 7 fixes held. 7 fixes: (H4) removed hooks/ from EXEMPT_DIRS Gates 5&8, (M1) MAX_VERIFIED_FIXES=100, (M2) MAX_PENDING_VERIFICATION=50, (H6) memory server input validation, (M8) removed curl/systemctl from verify_keywords, (M9) pinned chromadb/mcp versions, (M11) tightened assertions. Verified: 132/132 tests pass. Modified: gate_05, gate_08, requirements.txt, memory_server.py, state.py, enforcer.py, test_framework.py. Remaining: race condition, one-liner bypasses, symlink risk, extension gaps, deploy gaps, crit file gaps.",
    },
    {
        "id": "8c0da2ef26d06f99",
        "text": "Session 376: MCP optimization. (1) Added self_improve(action) routing to skill_server.py (17 actions, ~110 tokens). (2) Created 8 SKILL.md: code-hotspots, test-stubs, replay-events, tool-recommendations, gate-health, causal-chain, gate-timing, session-metrics. (3) Removed 6 dead functions from analytics_server.py. (4) Disabled gate_timing/session_metrics (16→14 tools). (5) Cleaned dist/node_modules. (6) Analytics has 14 active MCP tools (30 commented, zero cost). Total: 12 memory + 14 analytics + 2 search + 4 skills = 32 active tools, ~3,520 tokens/prompt.",
    },
    {
        "id": "dd4fc80af342a1a7",
        "text": "session_analytics.py (Session 163) extended API: _load_gate_effectiveness() (→{gate: {blocks, overrides, prevented}}), _load_capture_queue(max_entries) (→observation list), _load_all_state_files() (→{session_id: state}), _state_session_metrics(session_id, state) (→metrics), get_session_summary(session_id=None) (→snapshot), compare_sessions(a, b) (→deltas/gate_delta/summary). Backward compat: original analyse_session(), compare_sessions_metrics() preserved.",
    },
    {
        "id": "508923d1e5e76400",
        "text": "[torus-voice-ios] Security audit: CRITICAL: VPS IP 95.111.231.121 hardcoded (PROMPT.md:451,454,gen_cert.sh:5), auth token 'torus-voice-2026' plaintext (PROMPT.md:455,206, config.json:2), internal tmux names (claude, torus-voice-ios, chainovi, torus-website). MEDIUM: config.json, PROMPT.md not in .gitignore. Fixes: add to .gitignore, replace token with placeholder, replace IP with placeholder, rotate token.",
    },
    {
        "id": "4e8876cbb40fd5c2",
        "text": "Session 362: Token optimization. Dormanted 20 skills (39→18 active): trade, market, specialty (browser, document, prp, refactor, report, security-scan, teach, writing-plans), self-improve (analyze-errors, audit, benchmark, diagnose, introspect, sprint, super-*). Renamed /loop→/prp-run, /wave→/prp-wave. Trimmed /learn 255→72 chars. Created .claudeignore: dormant/, __pycache__/, *.pyc, *.jsonl, hooks/audit/, integrations/telegram-bot/, integrations/voice-web/. Kept 18 active. Savings: ~1,700 tokens/msg from skills, ~2,926 files excluded.",
    },
    {
        "id": "7d3fbea01afa38b0",
        "text": "CLAUDE CODE TOKEN FOOTPRINT (Session 228): Per-prompt (159 lines, 6,876 chars, 1,720 tokens): CLAUDE.md (587), hooks.md (245), memory.md (240), domains.md (303), framework.md (345). Session start (314 lines, 9,900 chars, 2,475 tokens): settings.json (2,050), HANDOFF.md (275), LIVE_STATE.json (150). GRAND TOTAL: 4,195 tokens at session start. Per-prompt: 1,720 tokens (rules + CLAUDE.md). Session boot adds 2,475. MEMORY.md not injected by default. Critical: CLAUDE.md 587 tokens within budget; full per-prompt load 1,720 should monitor.",
    },
    {
        "id": "2273982fede41394",
        "text": "Git secrets audit (2026-02-26): CRITICAL: Telegram bot token ***TELEGRAM_BOT_TOKEN*** in integrations/telegram-bot/config.json (3 commits: 6f09bc9, 46c62b9, a35ea7e). Listed in .gitignore:63 but committed before rule applied—git tracks it. MUST remove from history (BFG/filter-branch) + revoke token. Also tracked: allowed_users:[***TG_USER_ID***], 5 .pyc files, hooks/.capture_queue.jsonl, hooks/.prompt_last_hash, LIVE_STATE.json. Empty chroma.sqlite3 OK. No Groq key hardcoded. Feb 13-14/16 backups audit—no token.",
    },
    {
        "id": "042f9a1c280854f3",
        "text": "Karpathy/autoresearch (2026-03-09): Autonomous ML loop—edits train.py (single-GPU GPT), runs 5-min expts, checks val_bpb (lower=better), commits if improved/resets if not, loops forever. Files: prepare.py (read-only), train.py (editable), program.md (human instructions). Structure: Setup (branch, read, init), Expt (constraints, simplicity), Output (val_bpb, training_seconds, peak_vram_mb, mfu_percent, total_tokens_M, num_params_M, depth), Log (5-col TSV), Loop (FOREVER). Key: (1) NEVER STOP, (2) commit BEFORE run, (3) 5-col TSV with memory_gb, (4) crash handling, (5) no stops, (6) 10min timeout, (7) simplicity weighted, (8) run.log redirect, (9) git reset. Stats: 8414 stars, March 6 2026, MIT.",
    },
    {
        "id": "626edf58d2c354dc",
        "text": "Circuit breaker module (/home/crab/.claude/hooks/shared/circuit_breaker.py): States—CLOSED (normal), OPEN (reject), HALF_OPEN (probe). Defaults: threshold=5, timeout=60s, success_threshold=2. Persist: /dev/shm/claude-hooks/circuit_breaker.json (ramdisk), fallback ~/.claude/hooks/.circuit_breaker.json. Thread-safe: threading.Lock + atomic rename. API: record_success(), record_failure(), is_open(), get_state(), get_all_states(), reset(). Fail-open. Transitions: CLOSED→OPEN (failures>=threshold), OPEN→HALF_OPEN (timeout), HALF_OPEN→CLOSED (success>=2), HALF_OPEN→OPEN (fail). Test: 16/16 pass. Framework: 1124 pass (76 pre-existing fail, no regressions).",
    },
]

# Verify all are <=800 and convert text to new_text
for item in entries:
    item["new_text"] = item.pop("text")  # Rename text to new_text
    if len(item["new_text"]) > 800:
        # Truncate at word boundary
        new_text = item["new_text"][:800].rsplit(" ", 1)[0] + "..."
        item["new_text"] = new_text
    print(f"{item['id']}: {len(item['new_text'])} chars")

# Write output
with open("/home/crab/.claude/scripts/medium_batch_25.json", "w") as f:
    json.dump(entries, f, indent=2)

print(f"\nWrote {len(entries)} entries")
