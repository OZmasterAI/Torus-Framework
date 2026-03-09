"""Rule-based entity extraction for the Torus Memory System.

Extracts entities (technologies, concepts, file paths, identifiers) from text
using heuristics — no LLM calls, no external NLP dependencies.

Public API:
    from shared.entity_extraction import extract_entities, extract_cooccurrences
"""

import re
from itertools import combinations
from typing import Dict, List, Tuple

# --- Stop words (common English + programming filler) ---
_STOP_WORDS = frozenset(
    "a about above after again against all am an and any are aren't as at be because been "
    "before being below between both but by can can't cannot could couldn't did didn't do does "
    "doesn't doing don't down during each few for from further get got had hadn't has hasn't "
    "have haven't having he he'd he'll he's her here here's hers herself him himself his how "
    "how's i i'd i'll i'm i've if in into is isn't it it's its itself just let's me more most "
    "mustn't my myself no nor not of off on once only or other ought our ours ourselves out "
    "over own same shan't she she'd she'll she's should shouldn't so some such than that "
    "that's the their theirs them themselves then there there's these they they'd they'll "
    "they're they've this those through to too under until up upon very was wasn't we we'd "
    "we'll we're we've were weren't what what's when when's where where's which while who "
    "who's whom why why's will with won't would wouldn't you you'd you'll you're you've your "
    "yours yourself yourselves also still already using used use uses just like will now also "
    "new old try tried make made get got set way need needs thing things work works working "
    "worked going gone done doing see seen look looking found find run running added adding "
    "add update updated check checked fixed fix bug error issue".split()
)

# --- Compound nouns (tech-specific bigrams) ---
_COMPOUND_NOUNS = frozenset([
    "knowledge graph", "spreading activation", "machine learning", "deep learning",
    "neural network", "natural language", "language model", "vector search",
    "vector database", "memory server", "memory system", "memory decay",
    "entity extraction", "circuit breaker", "rate limit", "rate limiting",
    "access token", "api key", "pull request", "merge conflict",
    "test suite", "test runner", "test framework", "unit test",
    "git branch", "git commit", "git worktree", "git hook",
    "pre commit", "post commit", "gate result", "gate check",
    "audit log", "error handler", "error pattern", "health check",
    "health monitor", "domain registry", "security profile",
    "long term", "short term", "half life", "power law",
    "decay curve", "decay factor", "decay rate",
    "hebbian learning", "co retrieval", "ltp status",
])

# --- File/path pattern ---
_FILE_PATTERN = re.compile(r'[\w/.-]+\.\w{1,10}')

# --- CamelCase / PascalCase splitter ---
_CAMEL_RE = re.compile(r'[A-Z][a-z]+(?:[A-Z][a-z]+|[A-Z]+)+')

# --- Identifier pattern (snake_case, etc) ---
_IDENT_PATTERN = re.compile(r'[a-zA-Z_]\w*(?:_\w+)+')

# --- Capitalized proper nouns (not at sentence start) ---
_PROPER_NOUN_RE = re.compile(r'(?<!\. )(?<!\A)(?<=\s)[A-Z][a-zA-Z]{2,}')


def _sentence_split(text: str) -> List[str]:
    """Split text into sentences, handling common abbreviations."""
    # Simple split on sentence-ending punctuation followed by space+capital
    parts = re.split(r'(?<=[.!?])\s+(?=[A-Z])', text)
    return [p.strip() for p in parts if p.strip()]


def _tokenize(text: str) -> List[str]:
    """Tokenize into words, preserving case for proper noun detection."""
    return re.findall(r'[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)*', text)


def _classify_entity_type(name: str) -> str:
    """Assign entity type based on heuristics."""
    lower = name.lower()

    # File paths
    if '.' in name and _FILE_PATTERN.match(name):
        ext = name.rsplit('.', 1)[-1].lower()
        if ext in ('py', 'js', 'ts', 'tsx', 'rs', 'go', 'java', 'cpp', 'c', 'h',
                    'json', 'yaml', 'yml', 'toml', 'md', 'txt', 'sql', 'sh'):
            return "File"

    # Technology names (PascalCase or known patterns)
    if name[0].isupper() and any(c.islower() for c in name):
        if any(tech in lower for tech in ('db', 'sql', 'api', 'mcp', 'sdk', 'cli')):
            return "Technology"

    # Compound concepts
    if ' ' in name or '_' in name:
        return "Concept"

    # PascalCase identifiers
    if _CAMEL_RE.match(name):
        return "Technology"

    # Capitalized single word
    if name[0].isupper():
        return "Keyword"

    return "Keyword"


def extract_entities(text: str) -> List[Dict]:
    """Extract entities from text using rule-based heuristics.

    Returns list of {"name": str, "type": str, "positions": list[int]}
    """
    if not text or not text.strip():
        return []

    entities: Dict[str, Dict] = {}  # name → entity dict

    # 1. Extract file paths
    for m in _FILE_PATTERN.finditer(text):
        name = m.group()
        if name.lower() not in _STOP_WORDS and len(name) > 2:
            entities[name] = {"name": name, "type": "File", "positions": [m.start()]}

    # 2. Extract compound nouns
    text_lower = text.lower()
    for compound in _COMPOUND_NOUNS:
        idx = text_lower.find(compound)
        if idx >= 0:
            # Use original case from text
            original = text[idx:idx + len(compound)]
            entities[compound] = {"name": compound, "type": "Concept", "positions": [idx]}

    # 3. Extract CamelCase/PascalCase identifiers
    for m in _CAMEL_RE.finditer(text):
        name = m.group()
        if name.lower() not in _STOP_WORDS:
            entities[name] = {"name": name, "type": _classify_entity_type(name), "positions": [m.start()]}

    # 4. Extract snake_case identifiers
    for m in _IDENT_PATTERN.finditer(text):
        name = m.group()
        if name.lower() not in _STOP_WORDS and len(name) > 3:
            # Skip if it's part of a file path already captured
            if not any(name in e["name"] and e["name"] != name for e in entities.values()):
                entities[name] = {"name": name, "type": _classify_entity_type(name), "positions": [m.start()]}

    # 5. Extract capitalized words (proper nouns, technology names)
    tokens = _tokenize(text)
    for i, token in enumerate(tokens):
        if (token[0].isupper() and len(token) > 2 and
                token.lower() not in _STOP_WORDS and
                token not in entities):
            # Skip if it's a sentence-start word (heuristic: preceded by nothing or period)
            if i == 0:
                continue
            entities[token] = {"name": token, "type": _classify_entity_type(token), "positions": []}

    # 6. Extract ALL-CAPS acronyms (3+ chars)
    for m in re.finditer(r'\b[A-Z]{3,}\b', text):
        name = m.group()
        if name not in _STOP_WORDS:
            entities[name] = {"name": name, "type": "Technology", "positions": [m.start()]}

    return list(entities.values())


def extract_cooccurrences(text: str) -> List[Tuple[str, str]]:
    """Extract co-occurring entity pairs within the same sentence."""
    sentences = _sentence_split(text)
    pairs = set()

    for sentence in sentences:
        ents = extract_entities(sentence)
        names = [e["name"] for e in ents]
        for a, b in combinations(sorted(set(names)), 2):
            pairs.add((a, b))

    return list(pairs)
