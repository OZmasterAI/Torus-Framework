import tiktoken, json

enc = tiktoken.encoding_for_model("gpt-4")  # cl100k_base, close to Claude

def tok(text):
    return len(enc.encode(text))

# Read all files
files = {
    "CLAUDE.md": open("/home/crab/.claude/CLAUDE.md").read(),
    "HANDOFF.md": open("/home/crab/.claude/HANDOFF.md").read(),
    "LIVE_STATE.json": open("/home/crab/.claude/LIVE_STATE.json").read(),
    "rules/hooks.md": open("/home/crab/.claude/rules/hooks.md").read(),
    "rules/memory.md": open("/home/crab/.claude/rules/memory.md").read(),
    "rules/framework.md": open("/home/crab/.claude/rules/framework.md").read(),
}

print("=" * 60)
print("TOKEN COUNTS PER FILE")
print("=" * 60)
total = 0
for name, text in files.items():
    t = tok(text)
    total += t
    print(f"  {name:25s}  {t:5d} tokens")
print(f"  {'SUBTOTAL':25s}  {total:5d} tokens")

protocol_text = "PROTOCOL: Present session number, brief summary, completed list (what was done last session), and remaining list (what's next) in ONE message. IMPORTANT -- Always display the current toggle states table to the user in your greeting. Current toggles: Terminal L2 always-on: OFF -- Always run terminal FTS5 search (OFF = only when L1 < 0.3) | Terminal L2 enrichment: ON -- Attach +/-30min terminal history to ChromaDB results | TG L3 always-on: OFF -- Always run Telegram FTS5 search (OFF = only when L1 < 0.3) | TG L3 enrichment: OFF -- Attach +/-30min Telegram messages to ChromaDB results | Telegram bot: OFF -- Start/stop Telegram bot in dedicated tmux session | Gate auto-tune: OFF -- Auto-adjust gate thresholds based on effectiveness data | Chain memory: OFF -- Remember and reuse successful skill chain sequences | Session notify: ON -- Send session summary to Telegram on end | Mirror messages: OFF -- Send all Claude responses to Telegram | Budget degradation: OFF -- Auto-degrade models when approaching token budget | Session token budget: 0 -- Max tokens per session (0 = unlimited). Telegram bot config: configured (token: ...0mGYVU, users: [***TG_USER_ID***]). Ask: Continue or New task? If user says continue, ask which item to tackle -- do NOT auto-start work. If user changes any toggle, update the corresponding LIVE_STATE.json field. SPECIAL -- Telegram bot toggle (tg_bot_tmux): When user turns ON: (1) Check config at integrations/telegram-bot/config.json. (2) Update config.json with any changes. (3) Start the bot: create tmux session claude-bot and run python3 integrations/telegram-bot/bot.py in it. (4) Update LIVE_STATE.json tg_bot_tmux=true. When user turns OFF: (1) Kill the bot process in tmux session claude-bot. (2) Update LIVE_STATE.json tg_bot_tmux=false."

pt = tok(protocol_text)
print(f"  {'boot.py protocol block':25s}  {pt:5d} tokens")
print(f"  {'GRAND TOTAL':25s}  {total + pt:5d} tokens")

print()
print("=" * 60)
print("LIVE_STATE.json BREAKDOWN")
print("=" * 60)
ls = json.loads(files["LIVE_STATE.json"])
sections = [
    ("improvements_shipped (21)", json.dumps(ls["improvements_shipped"], indent=2)),
    ("files_modified (16)", json.dumps(ls["files_modified"], indent=2)),
    ("known_issues (8)", json.dumps(ls["known_issues"], indent=2)),
    ("next_steps (5)", json.dumps(ls["next_steps"], indent=2)),
    ("dormant_agent_teams (2)", json.dumps(ls["dormant_agent_teams"], indent=2)),
    ("toggles + metadata", json.dumps({k:v for k,v in ls.items() if k not in ("improvements_shipped","files_modified","known_issues","next_steps","dormant_agent_teams","last_session_metrics")}, indent=2)),
    ("last_session_metrics", json.dumps(ls["last_session_metrics"], indent=2)),
]
for name, text in sections:
    print(f"  {name:30s}  {tok(text):4d} tokens")

print()
print("=" * 60)
print("DUPLICATION ANALYSIS")
print("=" * 60)
ki_tokens_live = tok(json.dumps(ls["known_issues"], indent=2))
ns_tokens_live = tok(json.dumps(ls["next_steps"], indent=2))
print(f"  known_issues   in LIVE_STATE: {ki_tokens_live} tok (also in HANDOFF.md)")
print(f"  next_steps     in LIVE_STATE: {ns_tokens_live} tok (also in HANDOFF.md)")
waste = ki_tokens_live + ns_tokens_live
print(f"  WASTED on duplication:  ~{waste} tokens")

print()
print("=" * 60)
print("SAVINGS IF WE TRIM LIVE_STATE.json")
print("=" * 60)
trim_improvements = tok(json.dumps(ls["improvements_shipped"], indent=2))
trim_files = tok(json.dumps(ls["files_modified"], indent=2))
trim_ki_dup = ki_tokens_live
trim_dormant = tok(json.dumps(ls["dormant_agent_teams"], indent=2))
trim_metrics = tok(json.dumps(ls["last_session_metrics"], indent=2))

print(f"  Remove improvements_shipped:  -{trim_improvements} tokens")
print(f"  Remove files_modified:        -{trim_files} tokens")
print(f"  Remove known_issues (dup):    -{trim_ki_dup} tokens")
print(f"  Remove dormant_agent_teams:   -{trim_dormant} tokens")
print(f"  Remove last_session_metrics:  -{trim_metrics} tokens")
savings = trim_improvements + trim_files + trim_ki_dup + trim_dormant + trim_metrics
print(f"  TOTAL SAVINGS:                -{savings} tokens")
print(f"  Current LIVE_STATE:            {tok(files['LIVE_STATE.json'])} tokens")
print(f"  After trim:                   ~{tok(files['LIVE_STATE.json']) - savings} tokens")
