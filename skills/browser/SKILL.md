# /browser — Visual Verification via agent-browser

## When to use
When user says "browser", "screenshot", "visual verify", "check the UI",
or when implementing UI features that need visual proof of correctness.

## Commands
- `/browser open <url>` — Open a URL in headless browser
- `/browser snapshot` — Get page structure (interactive elements with @refs)
- `/browser screenshot <path>` — Capture screenshot to file
- `/browser click <ref>` — Click an element by @ref (from snapshot)
- `/browser fill <ref> <value>` — Fill a form field by @ref
- `/browser verify <url>` — Combined: open + snapshot + screenshot

## Verify Flow (most common)
1. `agent-browser open <url>`
2. `agent-browser snapshot -i -c` (interactive elements with @refs)
3. `agent-browser screenshot screenshots/<feature-name>.png`
4. Analyze screenshot — if issues found, fix and re-verify
5. Save final screenshot path in memory with feature context

## Interactive Testing Flow
1. Open URL
2. Snapshot to discover interactive elements (@e1, @e2, etc.)
3. Click/fill elements to test interactions
4. Screenshot after each interaction to verify state changes
5. Report results

## Integration with /ralph
During /ralph Phase 2 (EXECUTE), after implementing a UI sub-task:
1. Start the dev server if not running
2. `/browser verify http://localhost:<port>/<page>`
3. Only mark sub-task complete if screenshot confirms correctness
4. Save screenshot path in iteration memory save

## Rules
- ALWAYS use `screenshots/` directory (create if needed)
- ALWAYS include descriptive filenames: `screenshots/health-score-endpoint.png`
- NEVER mark UI work as "done" without a screenshot when /browser is available
- If agent-browser is not installed, report error and fall back to manual verification
- Screenshots are proof — reference them in memory saves and reports
