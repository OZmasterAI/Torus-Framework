# /mode — Switch Behavioral Modes

## When to use
When the user says "/mode on coding", "/mode off", "/mode list", or wants to switch behavioral modes.

## Arguments
- `/mode on <name>` — Activate a mode (e.g., `coding`)
- `/mode off` — Deactivate the current mode
- `/mode list` — Show available modes and which is active

## Steps

### If `on <name>`:
1. Check that `~/.claude/modes/<name>.md` exists
   - If not, list available modes from `~/.claude/modes/*.md` and tell the user
2. Copy `~/.claude/modes/<name>.md` to `~/.claude/rules/_active_mode.md`
3. Write the mode name to `~/.claude/modes/.active` (plain text, just the name)
4. Confirm: "Mode **<name>** activated. Behavioral overlay is now in effect."
5. Read `~/.claude/rules/_active_mode.md` and follow it immediately

### If `off`:
1. Delete `~/.claude/rules/_active_mode.md` if it exists
2. Delete `~/.claude/modes/.active` if it exists
3. Confirm: "Mode deactivated. Back to default behavior."

### If `list`:
1. List all `*.md` files in `~/.claude/modes/` (excluding dotfiles and subdirs)
2. Check if `~/.claude/modes/.active` exists — if so, read the active mode name
3. Display available modes with the active one marked:
   ```
   Available modes:
     coding  [active]
   ```

## Notes
- Modes are additive — they layer on top of CLAUDE.md, rules, and gates
- Only one mode can be active at a time
- The `_active_mode.md` file in rules/ is auto-loaded by Claude Code's rules system
- This skill is dormant until moved to `~/.claude/skills/mode/SKILL.md`
