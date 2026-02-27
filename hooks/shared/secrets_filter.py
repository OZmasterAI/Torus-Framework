"""Secrets scrubber for auto-capture observations.

Applies compiled regex patterns to redact sensitive data (API keys, tokens,
connection strings, etc.) from text before it gets stored as observations.

All patterns are compiled at module load time for performance (~0ms per call
after initial compilation).
"""

import re

# Compiled patterns: (regex, replacement)
# ORDER MATTERS: Specific token patterns first, generic patterns last.
# This prevents generic patterns (env var, long-string) from masking
# specific ones (JWT, GitHub, AWS).
_PATTERNS = [
    # 1. Private key blocks (most distinctive, multi-line)
    (re.compile(
        r'-----BEGIN[A-Z \-]*PRIVATE KEY-----[\s\S]*?-----END[A-Z \-]*PRIVATE KEY-----'
    ), '<PRIVATE_KEY_REDACTED>'),

    # 2. JWT tokens (eyJ... — must come before env var pattern)
    (re.compile(r'eyJ[A-Za-z0-9\-_]+\.eyJ[A-Za-z0-9\-_]+\.[A-Za-z0-9\-_]+'), '<JWT_REDACTED>'),

    # 3. Bearer tokens
    (re.compile(r'Bearer\s+[A-Za-z0-9\-._~+/]+=*', re.IGNORECASE), 'Bearer <REDACTED>'),

    # 4. AWS access keys (AKIA...)
    (re.compile(r'AKIA[0-9A-Z]{16}'), '<AWS_KEY_REDACTED>'),

    # 5. GitHub tokens (ghp_, gho_, ghs_, github_pat_)
    (re.compile(r'(?:ghp_|gho_|ghs_|github_pat_)[A-Za-z0-9_]+'), '<GH_TOKEN_REDACTED>'),

    # 6. SSH public keys (ssh-rsa, ssh-ed25519, ssh-ecdsa)
    (re.compile(r'ssh-(rsa|ed25519|ecdsa)\s+AAAA[A-Za-z0-9+/=]+'), '<SSH_KEY_REDACTED>'),

    # 7. Slack tokens (xoxb-, xoxp-, xoxa-, xoxr-, xoxs-)
    (re.compile(r'xox[bpars]-[A-Za-z0-9-]+'), '<SLACK_TOKEN_REDACTED>'),

    # 8. Anthropic API keys (sk-ant-...)
    (re.compile(r'sk-ant-[A-Za-z0-9-_]+'), '<ANTHROPIC_KEY_REDACTED>'),

    # 9. Generic sk- prefix keys (OpenAI, Stripe, etc., 40+ chars)
    (re.compile(r'sk-[A-Za-z0-9]{40,}'), '<SK_KEY_REDACTED>'),

    # 10. Connection strings (mongodb://, postgresql://, redis://, mysql://, amqp://)
    (re.compile(
        r'((?:mongodb|postgresql|postgres|mysql|redis|amqp|amqps)://)([^\s,\'"]+)'
    ), r'\1<REDACTED>'),

    # 11. Env var assignments with sensitive names (generic — after specific tokens)
    (re.compile(
        r'((?:API_KEY|SECRET|TOKEN|PASSWORD|PASSWD|MONGODB_URI|DATABASE_URL|'
        r'AUTH|PRIVATE_KEY|ACCESS_KEY|SECRET_KEY|CREDENTIALS|DB_PASS|'
        r'SMTP_PASS|REDIS_URL|SESSION_SECRET|JWT_SECRET|ENCRYPTION_KEY)'
        r'\s*[=:]\s*)(\S+)',
        re.IGNORECASE
    ), r'\1<REDACTED>'),

    # 12. Long hex/base64 strings after = or : (40+ chars, catch-all)
    (re.compile(r'([=:]\s*)[A-Za-z0-9+/\-_]{40,}=*'), r'\1<POSSIBLE_SECRET_REDACTED>'),
]


class SecretsScrubber:
    """Stateless secrets scrubber with pre-compiled patterns."""

    @staticmethod
    def scrub(text: str) -> str:
        """Remove sensitive data from text. Returns scrubbed copy."""
        if not text:
            return text
        result = text
        for pattern, replacement in _PATTERNS:
            result = pattern.sub(replacement, result)
        return result


# Module-level convenience instance
_scrubber = SecretsScrubber()
scrub = _scrubber.scrub
