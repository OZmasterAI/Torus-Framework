---
name: market
description: Market analysis, portfolio review, backtesting, and performance reporting
user_invocable: true
argument: symbol or command (e.g. "BTC/USDT", "portfolio", "backtest ma_crossover", "compare")
---

# /market — Market Analysis (Read-Only)

Analyze markets, review portfolio, run backtests, compare strategies. Never executes trades.

## Workflow

Parse the user's argument to determine the action:

### Symbol Analysis (default)
1. `search_knowledge("market analysis <symbol>")` for prior analysis
2. Fetch data:
   ```
   ~/projects/trading-claude/.venv/bin/python3 ~/projects/trading-claude/scripts/fetch_data.py --symbol <SYMBOL> --limit 30
   ```
3. Analyze: trend, support/resistance, volume, patterns, key levels
4. `remember_this()` significant findings with tags: `type:learning,area:trading,ticker:<SYMBOL>`

### Portfolio Review ("portfolio")
1. Run both in parallel:
   ```
   ~/projects/trading-claude/.venv/bin/python3 ~/projects/trading-claude/scripts/portfolio.py --format text
   ~/projects/trading-claude/.venv/bin/python3 ~/projects/trading-claude/scripts/performance.py
   ```
2. Summarize portfolio health, risk exposure, P&L

### Backtest ("backtest <strategy>")
1. Run backtest:
   ```
   ~/projects/trading-claude/.venv/bin/python3 ~/projects/trading-claude/scripts/backtest.py --strategy <STRATEGY> --symbol <SYMBOL> --limit 365
   ```
2. Analyze results: win rate, P&L, drawdown, trade distribution

### Strategy Comparison ("compare")
1. Run comparison:
   ```
   ~/projects/trading-claude/.venv/bin/python3 ~/projects/trading-claude/scripts/performance.py --compare
   ```
2. Rank strategies, identify best/worst performers

## Rules

- **READ-ONLY** — this skill never executes trades
- Use `/trade` if the user wants to act on analysis
- Save significant findings to memory
