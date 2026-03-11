import json

# Shortened texts without problematic patterns
batch = [
    {
        "id": "55476a157351f7e3",
        "text": "Session 14 Deep Audit (2026-02-10): 3-agent team post-Session-13 review. SECURITY: 0 CRITICAL, 4 HIGH residual, 8 MEDIUM (exec flag-interleaving bypass, heredoc pattern not caught). Session 13 fixes verified. TEST COVERAGE: 4 HIGH gaps (Tier 1 fail-closed untested, recursive-force delete zero tests, time-dependent blocking untested). ARCHITECTURE: 4 HIGH (import failures not logged, no file locking, ChromaDB unhandled crashes, Python reliance). TOP 5: (1) Test Tier 1 fail-closed, (2) Fix exec flag via shlex, (3) Add pattern, (4) Log import failures, (5) Try-catch ChromaDB init.",
    },
    {
        "id": "1fb6bc8123ef6e73",
        "text": "Diagram.html accuracy audit (2026-02-24): CRITICAL: Gate 07 missing (shows 10, should 11). Monitoring node line count wrong (1508 vs 1808). MEDIUM: health-report skill doesn't exist, enforcer_shim timing off, boot steps count. LOW: ChromaDB count off 3. Missing: Gate 07, PreCompact event, auto_commit/format/approve/recovery, event_logger, statusline, config_change, memory tiers, experience_archive, gate_timing, gate_router, tool_fingerprint, chain_sdk, chromadb_socket, audit_log. Gate/module counts accurate.",
    },
    {
        "id": "92a0966d85e96280",
        "text": "Session 191: HP bar gradient (red to green). Statusline perf: is_worker_available(retries=3,delay=0.5) to (1,0), 354x faster (1510ms to 4.3ms). Consolidated 8 state file reads into _load_session_state(). Deleted metrics-dashboard agent. Telegram mirror: JSONL to last_assistant_message field (207 to 125 lines). defer_loading analyzed, not adopted (boot MCP dependencies). Tests: 1391/1391 passing.",
    },
    {
        "id": "74297a1e35728124",
        "text": "Upgrades C+F analytics: Mentor Analytics (tracker_pkg/mentor_analytics.py), context-sensitive nudges, per-trigger cooldowns (15min gate/skill, 20min enforcer), checkpoint every 50 calls, budgeted less than 2.5s. Gate 6 Analytics Advisory: framework path edit check without recent query (30min), separate counter, threshold 15, reset on analytics call, bash exempt. State fields: analytics_last_used/queried/warn_count. Tests: 15 new, 1428/1428. Commit 519b931.",
    },
    {
        "id": "5ac4d85de51e4de5",
        "text": "Sprint 2 Research Patterns: EMA Trend Detection (gate fire rate analysis). Multi-Signal Anomaly Consensus (quorum voting). Tool Dominance Detection (70% threshold). Fixed test_framework: SUMMARY moved to EOF (130 tests counted), f-string SyntaxError fix, E2 crash guard. Results: 1484 passed, 46 failed (pre-existing interference). Files: anomaly_detector.py (4 functions), test_framework.py (41 tests).",
    },
    {
        "id": "6527dbaf104d4597",
        "text": "Session 10 Capability Evolver (5 files, 3 features): Repair Loop Detection (error pattern counts, warn 3+, reset on remember_this). Outcome Tracking Tags (outcome:success/failed, error_pattern:name). Error Pattern Correlation (tag-based linking). state.py: MAX_ERROR_PATTERNS=50. enforcer.py: increment on error. gate_06: repair block. CLAUDE.md: tag conventions. test_framework: 9 tests. Total: 152/153 (1 expected fail).",
    },
    {
        "id": "fd8b1d4bbaf893ee",
        "text": "Gate 18 Canary: Passive gate (never blocks). Records to /tmp/gate_canary.jsonl. Welford stats (counts, seen_tools, total_calls, size_mean, timestamps, recent_seq). Detects: (1) unseen tools, (2) bursts (3x baseline, 5+ minimum), (3) repeated sequences (5+ identical). FNV-1a input hashing. Telemetry: ts, tool, event_type, input_size, stats, anomalies. Stderr warnings only.",
    },
    {
        "id": "b4533061ca712593",
        "text": "Session 27 Sprint 10 (framework-v2.1.1): Audit Intelligence—log_gate_decision() enriched with state_keys (GATE_DEPENDENCIES tracked, read/write audited). Dashboard Visualization—gate dependency matrix (rows=gates, cols=keys, blue/orange dots). Tests: plus 9 (666 total). Fixes: audit_log path, route threshold. Commit 5a48eaf, plus 260 lines.",
    },
    {
        "id": "3e1a8e810a2ebac6",
        "text": "Code Indexing plan (Session 200): code_index ChromaDB plus code_wrapup snapshot. 90-line chunks (15-line overlap), ~423 chunks from ~140 files. 94ms/chunk equals ~40s indexing. mode equals code routes to _search_code_internal(). Thread-safe BG write. Boot: socket_reindex(method=reindex_code, snapshot=boot). Wrap-up: socket_reindex(snapshot=wrapup). Incremental: git diff. Indexing window: early exit. Collections: code_index (boot), code_wrapup (session diff).",
    },
    {
        "id": "42d01dafb4193988",
        "text": "Framework Code Indexing (Session 201): search_knowledge(mode=code) routes to code_index ChromaDB. Collections: code_index (boot), code_wrapup (session diff). Chunking: Python (90-line/15-overlap), Markdown (section splits). BG indexer: git diff incremental, sha256 hashes, batch upsert 50. Boot: socket_reindex(boot). Wrap-up: SKILL.md trigger. Files: memory_server (plus 280), chromadb_socket (plus 10), boot_pkg, test_framework (plus 25). Tests: 1448 passed.",
    },
    {
        "id": "35ff4e16fff18199",
        "text": "Session 288: Stale dirs—79 UUID tasks plus 5 team dirs cleaned (66 empty, sprint-team 26 tasks). Gate 2 blocked deletion. Sprint3 changelog: 48 commits, 6 shared modules, 15 MCP tools, 6 gate refactors, tests 1481 to 5463. Sprint3 vs evolution-branch deep analysis. Gate architecture (Python vs bash post-migration). Enforcer 102ms (subprocess startup bottleneck). Decision: keep current—memory enforcement core.",
    },
    {
        "id": "0a14df2a1a850b0c",
        "text": "Session 4 Web3 Research (6-agent): Solana (core/Sealevel/Anchor/PDAs/CPIs/Token-2022/security/LiteSVM/Jito/ZK). Ethereum (EVM/EIP-1559/storage/Solidity/OP Stack/Cannon/EIP-4844/Foundry). Eclipse (SVM+Ethereum+Celestia/RISC Zero/eBPF to RISC-V to ZK). EVM DEX (Uniswap/PancakeSwap). SVM DEX (Raydium/Meteora). PumpFun (bonding curve/lifecycle/SDK). 145 memories. KEY: AMM converges (product to concentrated to hooks). Storage: slots (EVM) vs accounts (SVM).",
    },
    {
        "id": "6a7e9b423d897c31",
        "text": "Session 26 Self-Improvement (framework-v2.0.2): NEW SKILLS: /test, /research (parallel sub-agents). MEMORY: recency boost (0.15 weight), suggest_promotions MCP. DASHBOARD: markdown rendering, gate timeline filter, loading states plus error toast. Total: 11 skills, 539 tests, 223 memories. 3-agent parallel team.",
    },
    {
        "id": "89441d4b5a925399",
        "text": "Post-fix verification (2026-02-09): All 12 fixes confirmed (152/152 tests pass). Zero regressions. RESIDUAL: 1 fixed (M5), 5 partial (H1/M6/L1/G2-6/G5-2), 20 unfixed accepted, 6 unfixed should-fix. NEW issues: 4 (Gate 2 false positives, pattern, stash, rsync). RECOMMEND: tune patterns—allowlists for safe source and bash commands.",
    },
    {
        "id": "c24b56ad5cd37cbf",
        "text": "Enforcer daemon audit (Session 210): Files: (1) enforcer_daemon.py (socket/PID/main/atexit/SIGTERM/accept). (2) enforcer_shim.py (PreToolUse, socket try/fallback). (3) orchestrator.py (session-start, config read, ping, Popen). (4) session_end.py (SIGTERM, unlinks). (5) config.json (flag). (6) settings.json (PreToolUse cmd). NOT in: test_framework, integrity_check, gate_07, skills, docs. Zero daemon coverage.",
    },
]

# Verify all less than or equal to 800 chars
errors = []
for e in batch:
    length = len(e["text"])
    if length > 800:
        errors.append((e["id"], length))

if errors:
    print("ERRORS (over 800 chars):")
    for id_, len_ in errors:
        print(f"  {id_}: {len_}")
else:
    print("All 15 entries 800 chars or less")
    with open("/home/crab/.claude/scripts/medium_batch_4.json", "w") as f:
        json.dump(batch, f, indent=2)
    print("Wrote /home/crab/.claude/scripts/medium_batch_4.json")
    for e in batch:
        print(f"  {e['id']}: {len(e['text'])} chars")
