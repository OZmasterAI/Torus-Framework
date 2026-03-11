import json

# All 15 entries with their shortened versions
shortened_batch = [
    {
        "id": "cc9938754cba9d3f",
        "new_text": "Research findings from Claude Code docs and self-improving agent papers (Session 163 Sprint-2): 1) Hook JSON decisions enable graduated escalation (warn→ask→block) instead of binary exit codes—low effort. 2) Async PostToolUseFailure hooks chain diagnosis→recovery→recording—medium effort. 3) MCP tool search/lazy loading scales to 100+ tools via on-demand loading (85% reduction). 4) Agent-based hooks spawn mini-agent (50 tools, 120s timeout) for deep semantic verification—high effort, critical for gates 3,5. 5) Preference-based reward modeling collects user feedback, trains reward model, enables agent self-modification—high effort. Top 3 priorities: Hook JSON (low), async failure hooks (medium), agent-based hooks for gate 5 (high).",
    },
    {
        "id": "b73fda1279a91910",
        "new_text": "Sprint-2 Research Swarm (15 agents, Session 163): 1) Hooks—3-tier composition, hookSpecificOutput JSON, async, deterministic enforcement. 2) Self-healing—multi-agent optimization, autonomous retraining, RepairAgent ($0.14/bug), lifelong systems. 3) Agent orchestration—hierarchical supervisor (17%), affinity (23-28%), group consensus, event-driven (90% reduction). 4) Quality gates—progressive enforcement, multi-layer (syntax→security→coverage). 5) ChromaDB—batch 50-250 docs, client-server, N=RAM_GB*0.245M, HNSW (3-5x faster). Actionable: (a) Agent contracts, (b) Async PostToolUse, (c) ChromaDB client-server, (d) GEPA evolution, (e) Maker-checker.",
    },
    {
        "id": "b0fcec9bb825fb4e",
        "new_text": "Multi-Instance Agent Architecture (Gastown-inspired): Persistent Claude Code role-agents (researcher-alpha, builder, planner) coordinated via file IPC at ~/.claude/channels/. Design: 1) Role-named (not model-named); role is identity. 2) Shared memory MCP with agent provenance. 3) File-based: task_{role}.json (inbox), result_{role}.json (outbox), log.jsonl (broadcast). 4) Shell watcher→tmux send-keys. 5) Worktrees for code-editing, normal for read-only. 6) Gate 13: co-claim for collaboration. 7) Persistent over on-demand (no billing). 8) Main compacts/clears workers. 9) Torus agents smarter via cognitive memory vs git-backed.",
    },
    {
        "id": "58dfefbb02d7e27d",
        "new_text": "Trading framework final design (Session 343): Separate Python project at ~/projects/trading-framework/ built on torus, runs independently. Architecture: Connector pattern (multi-asset), scheduler abstraction (multi-timeframe), embedded Python gates (<1ms), graduated autonomy (paper→real). Decisions: All asset classes via connectors (crypto/Binance/CCXT first); all timeframes via schedulers (daily/swing first); paper+full-auto start, 5 autonomy levels; Claude A/B/C (dev/analysis/decisions), coded strategies first; 12 gates/3 tiers (only 4 phase 1); custom backtester (no Backtrader/Zipline). Libraries: CCXT, alpaca-py, pandas-ta, pandas, numpy, Anthropic SDK, python-telegram-bot. Build: Engine core, gate system, strategy framework, backtester, journal. Phases: (1) Foundation+Paper+4 gates+1 strategy, (2) Binance+real, (3) Second asset, (4) Claude analysis/strategy, (5) Real money.",
    },
    {
        "id": "ca88300ec73d4d09",
        "new_text": "Trading framework 4-phase build plan: Phase 1 (Foundation): Connector interface, data models (Order, Position, Price, Candle), PaperConnector (simulated), engine core, 2-3 initial gates (risk, position limit, daily loss). Phase 2 (Real connector): BinanceConnector via CCXT for crypto, test paper vs real. Phase 3 (Asset diversity): OandaConnector (forex) or AlpacaConnector (stocks), validate same strategy across assets. Phase 4 (Intelligence): Claude-in-loop research, memory for trade learning, more gates (correlation, cooldown, backtest proof), analytics. Key: Design all-asset interface upfront (~1.5h) vs retrofit later (8-14h). Start with PaperConnector, then Binance (24/7, no PDT, testable $10), then stocks/forex. Architecture: Strategy/gates/journal asset-agnostic (percentages); connector layer handles specific brokers; engine never imports broker libraries.",
    },
    {
        "id": "5d2be51ebd46fea0",
        "new_text": "Chainovi deep comparison (Session 333, 2026-03-02): 5 blockchain projects in /home/crab/projects/chainovi/: 1) TRv1 (sjxcrypto/TRv1)—Full Agave fork, custom BFT, 4 programs (governance, treasury, dev-rewards, passive-stake), EIP-1559 complete. 2) TRv1-clean—Copy of TRv1 to hybrid repo, no EVM. 3) agave—Eclipse fork, TRv1 tokenomics patched, upstream Eclipse-Laboratories-Inc/agave. 4) eclipse-agave—ProjectDawn L2, DAWN token, feature-gated, safest (vanilla deploy). 5) trv1-chain—Greenfield L1, 14 Rust crates, 10.6K LOC, MIT license. KEY GAPS eclipse-agave vs TRv1: EIP-1559 dead code, no CU tracking, Governance zero, dev-rewards auto-deposit (no claiming), Treasury one-way (no withdrawal), Passive better (auto). All share 5% APY, 6 tiers, 120%=6% APY permanent lock, EIP-1559 fee split.",
    },
    {
        "id": "d679dc86e53fe558",
        "new_text": 'Created /home/crab/.claude/hooks/shared/consensus_validator.py (2026-02-20): Pure-Python consensus validation for critical ops. Four functions: check_memory_consensus(content, memories)→verdict/confidence/reason/top_match; check_edit_consensus(path, old, new)→safe/confidence/risks/is_critical; compute_confidence(signals)→float; recommend_action(confidence)→"allow"/"ask"/"block" (thresholds: ≥0.6 allow, 0.3-0.59 ask, <0.3 block). Uses difflib.SequenceMatcher, regex for imports/APIs/secrets/prints. CRITICAL_FILES: enforcer.py, gate_result.py, boot.py, memory_server.py, etc. Duplicates ≥0.85, near-match ≥0.55. Verified: ast.parse OK, all smoke-test assertions pass.',
    },
    {
        "id": "c6424ce9d98f3f75",
        "new_text": "Trading gate system: 12 gates, 3 tiers. TIER 1 (hard block, fail-closed): Gate 1—Position size ≤5% portfolio, Gate 2—Daily loss ≤-3%, Gate 3—Insufficient balance, Gate 4—Market closed (crypto always open). TIER 2 (block+override, fail-open): Gate 5—Thesis required, Gate 6—Cooldown (3 losses→30min), Gate 7—Max 5 open positions, Gate 8—Correlation >0.7 guard, Gate 9—Backtest proof. TIER 3 (advisory, logs only): Gate 10—Unusual size >2x avg, Gate 11—Off-hours, Gate 12—Win rate <40% last 20. Runner: sorted by tier, T1/T2 block, T3 log. Fail-closed block on crash, fail-open log+continue. All configurable. Phase 1: gates 1,2,3,4,6,7 (capital+discipline); later: 5,8,9; then 10,11,12.",
    },
    {
        "id": "028e13d813ff7420",
        "new_text": 'Session 11 (2026-02-09): GitHub release v0.1.0-eclipse for project-dawn-l2-chain/agave-dawn: 4 Linux x86-64 binaries (agave-validator 73MB, solana 35MB, solana-genesis 28MB, solana-keygen 2.7MB), version 2.2.0. README.md written covering overview, features, build, testnet, tests, structure, config, limits. Linux binaries rebuilt (3m 51s, incremental). Repo renamed agave-empty→agave-dawn; remote "dawn" updated. Multi-validator tests: 3/3 passed (single-validator 13.45s, 2-validator equal 41.61s, 2-validator 100:1 71.13s)—proves ProjectDawn mods don\'t break consensus. Warnings: GitHub auth shows invalid tokens but APIs work (may need gh auth login); rate limiting on large API calls (wait a few seconds). Teams used: release-team, rename-and-test (both cleaned up).',
    },
    {
        "id": "1e280fd189244cd9",
        "new_text": "ProjectDawn FEATURE_ID updated from placeholder to real keypair (2026-02-09): New pubkey 2cXMYQHQJeooKZv3q4F45mNLh5y5HMKvTfs5Rp3qtc8i, byte array [0x17, 0xF5...0xA3]. Files: runtime/src/projectdawn_config.rs line 33, scripts/projectdawn-testnet.sh line 33. Keypair: /home/crab/eclipse-agave/config/projectdawn-feature.json. All 20 integration tests pass (5 fee, 4 passive, 11 permanent). Release binaries rebuilt 7m 41s. Old placeholder FfysvyBPqGve3oDPu14LB1UqR8B2v7CeJ6EajWdx8P8D retired.",
    },
    {
        "id": "6e3a53264a6e19d5",
        "new_text": "Session 10 (2026-02-09) Eclipse L2 rebase complete: Phase 3 gaps—flat 5% APY override in inflation rewards (uses projectdawn_config), program fee attribution with fee-per-program tracking. Bug fixes: use parameter (not self.capitalization()), enumerate()+get() for fee accumulation with empty txs. Phase 4: Treasury seeding with --treasury-pubkey, DAWN token branding, 4 StakeInstruction arms. Phase 5: 20 integration tests all passing. Phase 6: L2 sequencer comments. Commit 92a6caa971 on projectdawn-eclipse (38 files, +8647/-52). Release binaries: agave-validator 73MB, solana 35MB, solana-genesis 28MB, solana-keygen 2.7MB. Pushed projectdawn-l2 orphan branch to GitHub (avoids 64MB Eclipse history block). Warnings: GitHub auth switched OZmasterAI; repo named agave-empty (manual rename needed).",
    },
    {
        "id": "826889999569c51f",
        "new_text": "Eclipse Agave L2 rebase Phase 0-1 (2026-02-09): Phase 0—Clone Eclipse-Laboratories-Inc/agave to /home/crab/eclipse-agave, branch projectdawn-eclipse (ef8aaa8e30), 3341 commits ahead of anza-xyz/agave, clean compile, tests baseline: stake 114/114 pass, runtime 548/548 pass; PKG_CONFIG_PATH=/usr/lib/x86_64-linux-gnu/pkgconfig required. Phase 1—Copy solana-stake-interface from ProjectDawn, add to workspace, patch.crates-io, 4 stub match arms (PermanentLock, PassiveLock, EarlyUnlock, GovernanceUnlock), copy projectdawn_config.rs. Tests: stake-interface 17/17, projectdawn_config 11/11 pass. Modified: Cargo.toml, runtime/src/lib.rs, programs/stake/src/stake_instruction.rs. Added: solana-stake-interface/.",
    },
    {
        "id": "00161da2d40e327b",
        "new_text": "Public repo OZmasterAI/Torus-Framework audit (2026-03-09): memory_server.py 4811 lines, LanceDB (5 tables: knowledge, observations, fix_outcomes, web_pages, quarantine). Active MCP: search_knowledge, fuzzy_search, remember_this, get_memory, record_attempt, record_outcome, query_fix_history, health_check. Dormant: deduplicate_sweep, delete_memory, maintenance, timeline. memory_decay: exponential (45d half-life), 3-tier base, access+recency+tag bonuses. MISSING: LTP tracker, knowledge graph, entity extraction, memory replay, adaptive weights, retroactive interference. Gates: 01-07,09-11,13-19 (18 total, missing 08,12). Local mem2x-task1 adds: ltp_tracker.py, knowledge_graph.py, entity_extraction.py, memory_replay.py; hybrid decay (15d half-life), potentiated mode; memory_server wires LTP, graph, adaptive, replay, Hebbian, retroactive, entity extraction.",
    },
    {
        "id": "e02d10c98b5afc1b",
        "new_text": "Eclipse L2 Phase 3 gaps filled (2026-02-09): 1) Flat 5% APY in calculate_previous_epoch_inflation_rewards()—if projectdawn_enabled, use projectdawn_config.epoch_staking_reward(total_staked) vs Solana's curve; total_staked from stakes_cache.staked_nodes().values().sum(); parameter renamed _prev_epoch_capitalization. Else fallback to Solana: self.capitalization()*validator_rate*duration. 2) Program fee attribution in filter_program_errors_and_collect_fee_details()—added sanitized_txs parameter, changed loop to iterate both results+transactions with zip(), added conditional: when projectdawn_enabled AND tx success, extract unique programs via program_instructions_iter(), divide fee equally, track in program_fee_attribution. Updated commit_transactions call site. Both compile clean.",
    },
    {
        "id": "7d2678265db3be5e",
        "new_text": 'Wave orchestration upgrades: 1) Auto-restart+heartbeat (torus-wave.py)—replaced communicate() blocking with poll() every 5s loop; on non-zero exit with retries≤2, respawn with same prompt; timeout kills processes exceeding task_timeout+30s grace; results dict includes "retries" count, activity log shows retry notes. 2) Pre-execution plan verification (skills/wave/SKILL.md step 3.5)—before wave loop, runs task_manager.py plan-check validating requirement coverage (uncovered reqs, orphan tasks), verifies parent directories exist, shows gaps to user, asks proceed/abort, gracefully skips if PRP .md doesn\'t exist (tasks-only valid).',
    },
]

# Verify all entries are ≤800 chars
all_valid = True
for entry in shortened_batch:
    text_len = len(entry["new_text"])
    if text_len > 800:
        print(f"ERROR: ID {entry['id']} is {text_len} chars (limit 800)")
        all_valid = False
    else:
        print(f"OK: ID {entry['id']} is {text_len} chars")

# Write to output file
output_file = "/home/crab/.claude/scripts/medium_batch_36.json"
with open(output_file, "w") as f:
    json.dump(shortened_batch, f, indent=2)

if all_valid:
    print(f"\nWrote {len(shortened_batch)} entries to {output_file}")
else:
    print("\nERROR: Some entries exceed 800 chars")
