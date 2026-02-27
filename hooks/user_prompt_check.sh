#!/usr/bin/env bash
# UserPromptSubmit hook: Detect corrections and feature requests in user prompts.
# Outputs XML tags to stdout that get added to Claude's context.
# Must be fast (<200ms) since it fires on every prompt.

# Read JSON from stdin, extract prompt field
PROMPT=$(python3 -c "import sys,json; print(json.load(sys.stdin).get('prompt',''))" 2>/dev/null)

# Exit silently if no prompt
[ -z "$PROMPT" ] && exit 0

# Convert to lowercase for matching
LOWER=$(echo "$PROMPT" | tr '[:upper:]' '[:lower:]')

# Check for correction patterns
if echo "$LOWER" | grep -qE '(^no,|wrong|actually,|that'\''s not right|that'\''s incorrect|try again)'; then
    echo "<correction_detected>User appears to be correcting a previous response. Pay close attention to what they say is wrong and save the correction to memory with type:correction tag.</correction_detected>"
fi

# Check for feature request patterns
if echo "$LOWER" | grep -qE '(can you|i wish|is there a way|would it be possible)'; then
    echo "<feature_request_detected>User may be requesting a new feature or capability. Consider saving to memory with type:feature-request tag if it represents a recurring need.</feature_request_detected>"
fi

exit 0
