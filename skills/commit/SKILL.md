# /commit — Quick Git Commit with Auto-Generated Message

## When to use
When the user says "commit", "save changes", "checkpoint", or wants to commit current work.

## Steps
1. **SURVEY CHANGES**:
   - Run `git status` to see staged and unstaged changes
   - Run `git diff --stat` to see the scope of changes
   - Run `git diff` (staged + unstaged) to understand what changed
   - Run `git log --oneline -5` to see recent commit message style
2. **STAGE FILES**:
   - Add relevant changed files by name (prefer explicit `git add <file>` over `git add -A`)
   - NEVER stage files that look like secrets: `.env`, `credentials.json`, `*.key`, `*.pem`
   - If unsure about a file, ask the user
3. **GENERATE MESSAGE**:
   - Analyze the staged diff to understand the "why" not just the "what"
   - Draft a concise commit message (1-2 sentences) matching the repo's style
   - Use conventional format if the repo uses it (feat:, fix:, chore:, etc.)
   - End with: `Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>`
4. **COMMIT**:
   - Use a HEREDOC for the message to preserve formatting
   - Do NOT use `--no-verify` — let pre-commit hooks run
   - If hooks fail, fix the issue and create a NEW commit (never amend)
5. **VERIFY**:
   - Run `git status` to confirm clean state
   - Run `git log --oneline -1` to confirm the commit
6. **DO NOT PUSH** unless the user explicitly says "push", "push it", or "commit and push"
