---
name: domain
description: Manage domain mastery overlays — knowledge-area bundles (framework, web-dev, solana) that carry synthesized expertise, behavioral rules, and gate tuning. Supports listing, activating, creating, graduating, and refreshing domains.
user_invocable: true
---

# /domain — Domain Mastery Management

## When to use
When the user wants to manage domain-specific knowledge overlays: list domains, activate/deactivate a domain, create a new domain, graduate (synthesize) accumulated memories into a knowledge base, refresh an existing knowledge base with new memories, or check domain status.

## Invocation Examples
- `/domain list` — show all domains with status
- `/domain activate framework` — switch active domain
- `/domain deactivate` — clear active domain
- `/domain create solana` — scaffold a new domain (interactive)
- `/domain graduate framework` — full graduation: distill L1 memories + L2 gap-fill into mastery.md
- `/domain refresh framework` — incremental update (new memories since last graduation/refresh)
- `/domain status` or `/domain status framework` — detailed domain info

## Subcommands

### list
Show all domains under `~/.claude/domains/` with columns:
- Name | Description | Active? | Graduated? | Has Knowledge?

Format as a markdown table. If no domains exist, say so and suggest `/domain create <name>`.

### activate <name>
1. Verify domain exists under `~/.claude/domains/<name>/`
2. Write domain name to `~/.claude/domains/.active`
3. Update session state: `active_domain = name`
4. Print confirmation: "Domain **<name>** activated. Knowledge will be injected at next boot."

### deactivate
1. Remove `~/.claude/domains/.active` (or write empty)
2. Update session state: `active_domain = ""`
3. Print confirmation: "Domain deactivated."

### create <name>
Interactive domain scaffolding:
1. Create directory `~/.claude/domains/<name>/`
2. Ask user for:
   - Description (1-line)
   - Memory tags (comma-separated, e.g. "solana, web3-research, area:backend")
   - L2 keywords (comma-separated, e.g. "solana, anchor, dex, raydium")
   - Auto-detect project patterns (optional, comma-separated)
   - Auto-detect feature patterns (optional, comma-separated)
3. Create `profile.json` from template with user's answers
4. Create empty `behavior.md` with a header comment
5. Create empty `mastery.md`
6. Print confirmation with next steps: "Run `/domain graduate <name>` when you have 20+ relevant memories."

### graduate <name>
Full graduation process — synthesize L1 memories + L2 terminal history into mastery.md:

1. Load domain profile to get `memory_tags` and `l2_keywords`
2. **L1 scan**: Query ChromaDB via `search_knowledge` for each memory tag (top_k=50 per tag). Deduplicate results by ID. Also query `search_knowledge` in "tags" mode for the domain's tags.
3. **Fix outcomes**: Query `query_fix_history` with domain-relevant error patterns if any
4. **Categorize L1 memories** into sections:
   - **Core Patterns** (from type:learning, type:decision)
   - **Key Decisions** (from type:decision — include rationale)
   - **Anti-Patterns** (from type:fix where outcome:failed, type:correction)
   - **Common Errors & Fixes** (from type:fix, type:error)
   - **Tools & Preferences** (from type:preference)
5. **L2 scan**: Query `terminal_history_search` with each L2 keyword (limit=20 per keyword). Deduplicate.
6. **L2 quality filter**: For each L2 result, INCLUDE only if:
   - Recurring pattern across multiple sessions
   - Root cause discovery (not just the fix)
   - Architecture decision with rationale missing from L1
   - Proven anti-pattern (failed repeatedly)
   - Key tool/API knowledge that keeps coming up
   REJECT if: one-off error, routine workflow, conversation noise, already in L1, stale/outdated
7. **Merge**: Add qualifying L2 findings to appropriate mastery.md sections
8. **Write mastery.md** respecting `token_budget` (~4 chars per token)
9. **Update profile.json**: `graduated=true, graduated_at=<ISO timestamp>, memory_count_at_graduation=<count>, l2_scanned_until=<ISO timestamp>`
10. Print summary: "Graduated **<name>**: <N> L1 memories + <M> L2 entries → mastery.md (<size> chars, ~<tokens> tokens)"

### refresh <name>
Incremental update — only scan new content since last graduation/refresh:

1. Load profile, get `last_refreshed` and `l2_scanned_until` timestamps
2. Query L1 memories with tags WHERE newer than `last_refreshed` (use timestamp filtering in search)
3. Query L2 terminal history WHERE newer than `l2_scanned_until`
4. Compare new findings against existing mastery.md
5. Add only genuinely new and important content
6. Update profile.json: `last_refreshed=<now>, l2_scanned_until=<now>`
7. Print summary of what was added

### status [name]
Show detailed domain status. If no name given, show active domain (or all if none active).

Display:
- Domain name, description
- Active: yes/no
- Graduated: yes/no (with timestamp if yes)
- Memory count: query `search_knowledge` by domain tags, count results
- Last refreshed: timestamp or "never"
- Token budget: N tokens
- Gate overrides: list any non-default gate modes
- Memory tags: list
- L2 keywords: list
- Auto-detect patterns: list

If memory count >= 20 and not graduated, print advisory: "This domain has <N> memories. Consider running `/domain graduate <name>` to synthesize into expertise."

## Rules
- NEVER delete or modify raw memories (L1) — mastery.md is a derivative artifact
- ALWAYS respect token_budget when writing mastery.md
- If graduation finds < 5 relevant memories, warn user: "Not enough memories for meaningful graduation. Continue working in this domain to accumulate more."
- Tag all memory operations with the domain name for traceability
- During graduation, show progress: "Scanning L1...", "Scanning L2...", "Synthesizing..."
- The `graduate` command overwrites mastery.md entirely; `refresh` appends/updates
- Graduation uses sub-agents for heavy scanning when memory count > 100
