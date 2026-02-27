"""Error normalizer for causal fix tracking.

Strips variable parts from error messages (paths, UUIDs, timestamps, numbers)
to produce stable fingerprints. Two errors that differ only in paths/line numbers
get the same hash, enabling cross-session fix tracking.
"""

import re

# Strip patterns (applied in order)
_STRIP_PATTERNS = [
    (re.compile(r'(?:[A-Za-z]:)?[/\\][\w./\\-]+'), '<path>'),       # Unix/Windows paths
    (re.compile(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', re.I), '<uuid>'),  # UUIDs
    (re.compile(r'0x[0-9a-fA-F]+'), '<hex>'),                        # Hex addresses
    (re.compile(r'\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}[\w.:+-]*'), '<ts>'),  # ISO timestamps
    (re.compile(r'\b[0-9a-f]{40}\b'), '<git-hash>'),                 # Git commit hashes
    (re.compile(r'\b[0-9a-f]{7}\b'), '<git-short>'),                 # Git short hashes
    (re.compile(r'tmp[a-zA-Z0-9_]{6,10}'), '<tmp>'),                 # Temp directory suffixes
    (re.compile(r'<\w+ object at (?:0x[0-9a-fA-F]+|<hex>)>'), '<obj-repr>'),   # Python object repr
    # Port numbers in connection errors
    (re.compile(r':\d{2,5}(?=/|\s|$)'), ':<port>'),                              # :8080, :3000, :443
    # Memory/size values
    (re.compile(r'\b\d+\s*(?:bytes?|[KMG]B)\b', re.I), '<mem-size>'),           # 1024 bytes, 50MB
    # Python traceback line references
    (re.compile(r',\s*line\s+\d+'), ', line <n>'),                               # , line 42
    (re.compile(r'\d{2,}'), '<n>'),                                   # Multi-digit numbers
]


def normalize_error(raw: str) -> str:
    """Strip variable parts from an error message, producing a stable fingerprint."""
    text = raw
    for pattern, replacement in _STRIP_PATTERNS:
        text = pattern.sub(replacement, text)
    # Collapse whitespace and lowercase
    text = re.sub(r'\s+', ' ', text).strip().lower()
    return text


def fnv1a_hash(text: str) -> str:
    """FNV-1a 64-bit hash, truncated to 8 hex chars."""
    h = 14695981039346656037  # FNV offset basis
    for byte in text.encode('utf-8'):
        h ^= byte
        h = (h * 1099511628211) & 0xFFFFFFFFFFFFFFFF  # FNV prime, mask to 64 bits
    return format(h, '016x')[:8]


def error_signature(raw: str) -> tuple:
    """Return (normalized_text, hash) for an error message."""
    normalized = normalize_error(raw)
    return (normalized, fnv1a_hash(normalized))
