import json

entries = [
    {
        "id": "26955767d66ae56e",
        "text": "ProjectDawn Testnet Readiness (2026-02-09): NOT READY. CRITICAL ISSUES (4): PERMANENTLY_LOCKED not enforced in split/merge/move_stake/move_lamports; deactivate_delinquent bypasses PERMANENTLY_LOCKED; no feature gate (hardcoded true); treasury pubkey is placeholder 0xDA...01 with no CLI override. HIGH ISSUES (4): unchecked u64 multiplication in fee split; unchecked arithmetic in fee interpolation; config not serialized to snapshots (consensus divergence risk); zero testnet launch scripts. TEST COVERAGE: permanent_lock has ZERO tests. CODE COMPLETENESS: ~90% (13 files).",
    },
    {
        "id": "36ae16469587c7f0",
        "text": '[chainovi/eclipse-agave #18] Production readiness items 6-8, 10 implemented. Item 6: getTreasuryBalance RPC endpoint added (RpcTreasuryBalance struct, solana-treasury-program dep, trait in rpc.rs). Item 7: CU consumption metric added via datapoint_info!("projectdawn-cu-consumed") in record_transaction_compute(). Item 8: Validator setup docs created (docs/projectdawn-validator-setup.md). Item 10: --projectdawn-treasury-pubkey CLI flag added (ValidatorConfig, args.rs, execute.rs, override_treasury_pubkey() in Bank, wired in load_blockstore()). VERIFICATION: All 28 tests pass (11 projectdawn_fees + 17 projectdawn_integration). Clean compile.',
    },
    {
        "id": "a43799f601e0c4ad",
        "text": "Session 5 Summary (2026-02-09): P2 Integration Tests + P3 Testnet Readiness completed. P2: 12 new integration tests (permanent:4, passive:4, fees:4); fixed permanent_lock() builder (missing CLOCK_ID at idx 1); fixed BankFieldsToSerialize missing projectdawn_config. P3: Fixed 120% reward multiplier panic (was consensus-crash); moved multiplier from distribution to calculation, tracked as permanent_lock_bonus_lamports; 6 new tests; fixed 2 pre-existing broken unit tests; created projectdawn-testnet.sh. TOTAL: 18 tests + 2 bug fixes + 2 pre-existing fixes + 1 script. CUMULATIVE: P0 (7 tests, 5 guards, gate, CLI) + P1 (14 tests, 4 fixes) + P2 (12 integration, 1 fix) + P3 (6 tests, 120% fix, script). ALL PASS.",
    },
    {
        "id": "8e0f3bb0f81d9f32",
        "text": "[chainovi/eclipse-agave #10] Emergency unlock dispatch wiring complete. stake_instruction.rs changes: Deactivate has optional marker at idx 3; EarlyUnlock has optional marker_index at 4; GovernanceUnlock full impl (accounts: stake, marker PDA, clock, staker signer; if locked → deactivate with marker; if passive → early_unlock zero penalty). instruction.rs: updated docs for all 3; added governance_unlock() builder. consume_emergency_marker changed to pub(crate).",
    },
    {
        "id": "348e928c1e0d0e7e",
        "text": "[chainovi/eclipse-agave #14] One-Time-Use Emergency Unlock Markers COMPLETE. governance/processor.rs: write_execution_side_effects calls set_owner(stake_program_id). stake/stake_state.rs: replaced UNLOCK_MARKER_DISCRIMINATOR with EMERGENCY_UNLOCK_SEED; rewrote validate_emergency_marker (owner==stake_program + lamports>0 + PDA check); added consume_emergency_marker (transfer lamports, close). stake_instruction.rs: added consume_emergency_marker calls after unlock in Deactivate/GovernanceUnlock/EarlyUnlock. bank/fee_distribution.rs: is_emergency_unlocked checks owner + lamports instead of discriminator. MARKER LIFECYCLE: Governance creates PDA (zero data) → set_owner to stake → Stake validates/consumes. All tests pass.",
    },
    {
        "id": "62be88107b5548d3",
        "text": "[chainovi/eclipse-agave #10] Emergency Unlock Wiring Complete. 7 files modified: (1) stake/Cargo.toml added solana-governance-program; (2) stake_state.rs added GOVERNANCE_PROGRAM_ID, UNLOCK_MARKER_DISCRIMINATOR, validate_emergency_marker, updated deactivate/early_unlock for optional marker; (3) stake_instruction.rs wired all 3 dispatches; (4) instruction.rs docs + governance_unlock() builder; (5) parse_stake.rs updated GovernanceUnlock parser (2→4 accounts); (6) projectdawn_permanent.rs test rename; (7) projectdawn_integration.rs 5 new tests. KEY: Markers NOT consumed by stake (ExternalAccountDataModified constraint). State change prevents re-use. 127 unit + 11 permanent + 17 integration + 13 transaction-status all pass.",
    },
    {
        "id": "bd6a7c2a7b6d2041",
        "text": '[chainovi/eclipse-agave #9] Emergency Unlock Marker System Complete Technical Spec. GOVERNANCE PROGRAM ID: Governance1111111111111111111111111111111111. PDA DERIVATION: seeds [b"emergency_unlock", stake_pubkey.as_ref()], program Governance, Pubkey::find_program_address(). MARKER FORMAT: discriminator 0x55 (1 byte) + target pubkey (32 bytes) + epoch (8 bytes LE u64) = 41 bytes total. GOVERNANCE: write_execution_side_effects writes marker to account[2]. BANK: is_emergency_unlocked derives PDA, reads marker, returns true if exists and first byte==0x55. CRITICAL: requires find_program_address to derive bump seed.',
    },
    {
        "id": "71220b4f596b4c14",
        "text": "[chainovi/eclipse-agave #10] Emergency unlock wiring Phase 2. (1) parse_stake.rs: GovernanceUnlock parser 2→4 accounts. (2) projectdawn_permanent.rs: test rename (no longer stub). (3) projectdawn_integration.rs: 5 new tests: governance_unlock_permanently_locked (deactivate+consume), governance_unlock_passive_stake (zero penalty), deactivate_with_marker (bypass PERMANENTLY_LOCKED), invalid_marker_rejected, marker_consumed_one_time_use.",
    },
    {
        "id": "b39bc0d2f5116b51",
        "text": "[chainovi/eclipse-agave #10] Emergency unlock marker wiring Phase 1. (1) stake/Cargo.toml added solana-governance-program. (2) stake_state.rs: added GOVERNANCE_PROGRAM_ID, UNLOCK_MARKER_DISCRIMINATOR; validate_emergency_marker(marker, stake_pubkey) helper; consume_emergency_marker(tx_ctx, ix_ctx, marker_index); updated deactivate(marker: Option<&BorrowedAccount>); updated early_unlock(marker_index: Option<IndexOfAccount>).",
    },
    {
        "id": "1d12c21bc0f3ddbd",
        "text": "ProjectDawn Group C integration tests (2026-02-09): 4 tests in projectdawn_fees.rs. (1) test_fee_split_4way_at_launch: 10% burn, 0% validator, 45% treasury, 45% dev (dev falls to treasury for system transfers). (2) test_fee_split_4way_at_maturity: warp to epoch 1460, verify 25/25/25/25. (3) test_feature_gate_disabled: without PROJECTDAWN_FEATURE_ID, verify projectdawn_enabled=false. (4) test_snapshot_round_trip: parent→child inheritance. KEY: Feature accounts need activated_at:Some(0); collector_fee_details private; dev share → treasury when no program_fee_attribution; Bank::warp_from_parent freezes, use child for transactions.",
    },
    {
        "id": "ad137e9f57fbe754",
        "text": "ProjectDawn testnet launch script: /home/crab/agave/scripts/projectdawn-testnet.sh. SETUP: generates treasury keypair (config/treasury.json), calls multinode-demo/setup.sh with --treasury-pubkey. ACTIVATE (post-genesis): verifies cluster running, checks feature keypair at config/projectdawn-feature.json, validates pubkey matches FfysvyBPqGve3oDPu14LB1UqR8B2v7CeJ6EajWdx8P8D, runs solana feature activate. STATUS: checks feature gate, treasury balance, cluster version. Constants: PROJECTDAWN_FEATURE_PUBKEY=FfysvyBPqGve3oDPu14LB1UqR8B2v7CeJ6EajWdx8P8D; DEFAULT_TREASURY_PUBKEY=FfysvyBPqGve3oDPu14LB1UqR8B2v7CeJ6EajWdx8P8C. Verified.",
    },
    {
        "id": "f0c0d28f934aa497",
        "text": "[trading-framework #?] Trading bot Phase 1 COMPLETE. 41 files, 58 tests passing. 7 waves: (1) 5 data models (Order, Position, Candle, Signal); (2) Gate infrastructure (TradingGate ABC, GateResult, GateRunner), Journal (SQLite); (3) BaseConnector ABC, Notifier ABC, ConsoleNotifier; (4) 6 concrete gates (risk_check, daily_loss, balance_check, market_hours, cooldown, max_positions); (5) PaperConnector, Portfolio; (6) Strategy ABC, MACrossoverStrategy, CronScheduler, Executor, Engine; (7) Backtester, main.py, test fixtures. Design: Gates check(order, portfolio, market_data). T1 fail-closed, T2 fail-open. All Decimal. Sync Phase 1. Long-only.",
    },
    {
        "id": "1df22a51a4467f1f",
        "text": "[trading-framework] Phase 5 COMPLETE. 192 tests passing (+35 new). 4 waves: (1) fixed close_trade() bug, added equity_curve to BacktestResult. (2) RSIStrategy and BollingerBandsStrategy (Decimal arithmetic, added to config). (3) engine/preflight.py: run_preflight checks (balance, price, market hours); --dry-run and --backtest flags. Auto-preflight for live connectors. (4) analysis/dashboard.py: build_dashboard, format_dashboard, export_dashboard; --dashboard and --export-pnl flags. NEW: strategies/rsi.py, strategies/bollinger.py, engine/preflight.py, analysis/dashboard.py + 4 test files. MODIFIED: executor.py, backtest.py, main.py, settings.json.",
    },
    {
        "id": "d89d7563ad9d7cfa",
        "text": "Session 345: All HANDOFF.md references removed from torus-framework. 18 files changed: hooks/session_end.py (removed shutil, HANDOFF_FILE, archive fn), gate_01 (removed from EXEMPT_PATTERNS), gate_14/15 (docstring updates), skills/report/SKILL.md (LIVE_STATE.json), status/scripts/gather.py (LIVE_STATE.json), telegram bot hooks/on_session_end.py (rewrote), test updates (4 files), benchmarks (LIVE_STATE.json), ARCHITECTURE.md, USAGE_GUIDE.md, README.md, .gitignore, deleted HANDOFF.md. Result: 5407 tests passed.",
    },
    {
        "id": "62279a45ebd2c156",
        "text": "[voice-web TTS] iOS Safari speechSynthesis limitations: (1) single short ~100 chars WORKS; (2) single long ~600 chars silently dropped; (3) multiple chained utterances only first plays; (4) timer-based polling only first plays; (5) queue upfront nothing plays; (6) server-side edge-tts generates MP3 but Audio.play() blocked by autoplay policy. ONLY approach working: single short utterance with persistent reference (prevents GC). iOS limit ~100-200 chars/utterance, won't chain multiple. Server-side /tts endpoint works but blocked by autoplay policy.",
    },
]

# Verify all are ≤800 chars and write output
output = []
for e in entries:
    text_len = len(e["text"])
    if text_len > 800:
        print(f"ERROR: Entry {e['id']} is {text_len} chars (max 800)")
    else:
        output.append({"id": e["id"], "new_text": e["text"]})
        print(f"✓ {e['id']}: {text_len} chars")

print(f"\nTotal entries: {len(output)}/15")

# Write to output file
with open("/home/crab/.claude/scripts/medium_batch_15.json", "w") as f:
    json.dump(output, f, indent=2)

print(f"\nWrote to /home/crab/.claude/scripts/medium_batch_15.json")
