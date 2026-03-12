---
name: trade
description: Analyze market and execute trades through the trading-claude framework
user_invocable: true
argument: symbol (e.g. "BTC/USDT")
---

# /trade — Trading Workflow

You are the trading brain. Analyze data, form a thesis, run gates, and execute trades with user confirmation.

## Workflow

1. **Memory check**: `search_knowledge("trading <symbol>")` for prior trades and insights on this symbol.

2. **Gather state**: Run these in parallel:
   ```
   ~/projects/trading-claude/.venv/bin/python3 ~/projects/trading-claude/scripts/fetch_data.py --symbol <SYMBOL> --limit 30
   ~/projects/trading-claude/.venv/bin/python3 ~/projects/trading-claude/scripts/portfolio.py --format json
   ```

3. **Analyze**: You ARE the analyst. Review candle data, identify:
   - Trend direction and strength
   - Support/resistance levels
   - Volume patterns
   - Key technical signals
   - Risk/reward ratio

4. **Decision**: If recommending a trade, state your thesis clearly, then run gates:
   ```
   ~/projects/trading-claude/.venv/bin/python3 ~/projects/trading-claude/scripts/check_gates.py --symbol <SYMBOL> --side <BUY|SELL> --quantity <QTY> --thesis "<your thesis>"
   ```

5. **Present to user**: Show gate results and your thesis. Ask for explicit confirmation before executing.

6. **Execute** (only after user confirms):
   ```
   ~/projects/trading-claude/.venv/bin/python3 ~/projects/trading-claude/scripts/execute_order.py --symbol <SYMBOL> --side <BUY|SELL> --quantity <QTY> --thesis "<thesis>" --skip-gates
   ```
   Use `--skip-gates` because gates were already checked in step 4.

7. **Show result**: Run `portfolio.py --format text` to show updated portfolio state.

8. **Save to memory**: `remember_this()` with trade details, thesis, outcome. Tags: `type:trade,area:trading,ticker:<SYMBOL>`

## Rules

- **NEVER** execute a trade without explicit user confirmation
- **ALWAYS** run gates before proposing a trade
- **ALWAYS** provide a thesis with your recommendation
- **ALWAYS** show gate results to the user
- Paper mode by default — warn if connector is not "paper"
- If all gates fail, explain why and suggest adjustments
