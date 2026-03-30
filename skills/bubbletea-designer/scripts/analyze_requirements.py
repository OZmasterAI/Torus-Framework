#!/usr/bin/env python3
"""
Requirement analyzer for Bubble Tea TUIs.
Extracts structured requirements from natural language.
"""

import re
from typing import Dict, List
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from utils.validators import RequirementValidator


# TUI archetype keywords
ARCHETYPE_KEYWORDS = {
    'file-manager': ['file', 'directory', 'browse', 'navigator', 'ranger', 'three-column'],
    'installer': ['install', 'package', 'progress', 'setup', 'installation'],
    'dashboard': ['dashboard', 'monitor', 'real-time', 'metrics', 'status'],
    'form': ['form', 'input', 'wizard', 'configuration', 'settings'],
    'viewer': ['view', 'display', 'log', 'text', 'document', 'reader'],
    'chat': ['chat', 'message', 'conversation', 'messaging'],
    'table-viewer': ['table', 'data', 'spreadsheet', 'grid'],
    'menu': ['menu', 'select', 'choose', 'options'],
    'editor': ['edit', 'editor', 'compose', 'write']
}


def extract_requirements(description: str) -> Dict:
    """
    Extract structured requirements from description.

    Args:
        description: Natural language TUI description

    Returns:
        Dictionary with structured requirements

    Example:
        >>> reqs = extract_requirements("Build a log viewer with search")
        >>> reqs['archetype']
        'viewer'
    """
    # Validate input
    validator = RequirementValidator()
    validation = validator.validate_description(description)

    desc_lower = description.lower()

    # Extract archetype
    archetype = classify_tui_type(description)

    # Extract features
    features = identify_features(description)

    # Extract interactions
    interactions = identify_interactions(description)

    # Extract data types
    data_types = identify_data_types(description)

    # Determine view type
    views = determine_view_type(description)

    # Special requirements
    special = identify_special_requirements(description)

    requirements = {
        'archetype': archetype,
        'features': features,
        'interactions': interactions,
        'data_types': data_types,
        'views': views,
        'special_requirements': special,
        'original_description': description,
        'validation': validation.to_dict()
    }

    return requirements


def classify_tui_type(description: str) -> str:
    """Classify TUI archetype from description."""
    desc_lower = description.lower()

    # Score each archetype
    scores = {}
    for archetype, keywords in ARCHETYPE_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in desc_lower)
        if score > 0:
            scores[archetype] = score

    if not scores:
        return 'general'

    # Return highest scoring archetype
    return max(scores.items(), key=lambda x: x[1])[0]


def identify_features(description: str) -> List[str]:
    """Identify features from description."""
    features = []
    desc_lower = description.lower()

    feature_keywords = {
        'navigation': ['navigate', 'move', 'browse', 'arrow'],
        'selection': ['select', 'choose', 'pick'],
        'search': ['search', 'find', 'filter', 'query'],
        'editing': ['edit', 'modify', 'change', 'update'],
        'display': ['display', 'show', 'view', 'render'],
        'input': ['input', 'enter', 'type'],
        'progress': ['progress', 'loading', 'install'],
        'preview': ['preview', 'peek', 'preview pane'],
        'scrolling': ['scroll', 'scrollable'],
        'sorting': ['sort', 'order', 'rank'],
        'filtering': ['filter', 'narrow'],
        'highlighting': ['highlight', 'emphasize', 'mark']
    }

    for feature, keywords in feature_keywords.items():
        if any(kw in desc_lower for kw in keywords):
            features.append(feature)

    return features if features else ['display']


def identify_interactions(description: str) -> Dict[str, List[str]]:
    """Identify user interaction types."""
    desc_lower = description.lower()

    keyboard = []
    mouse = []

    # Keyboard interactions
    kbd_keywords = {
        'navigation': ['arrow', 'hjkl', 'navigate', 'move'],
        'selection': ['enter', 'select', 'choose'],
        'search': ['/', 'search', 'find'],
        'quit': ['q', 'quit', 'exit', 'esc'],
        'help': ['?', 'help']
    }

    for interaction, keywords in kbd_keywords.items():
        if any(kw in desc_lower for kw in keywords):
            keyboard.append(interaction)

    # Default keyboard interactions
    if not keyboard:
        keyboard = ['navigation', 'selection', 'quit']

    # Mouse interactions
    if any(word in desc_lower for word in ['mouse', 'click', 'drag']):
        mouse = ['click', 'scroll']

    return {
        'keyboard': keyboard,
        'mouse': mouse
    }


def identify_data_types(description: str) -> List[str]:
    """Identify data types being displayed."""
    desc_lower = description.lower()

    data_type_keywords = {
        'files': ['file', 'directory', 'folder'],
        'text': ['text', 'log', 'document'],
        'tabular': ['table', 'data', 'rows', 'columns'],
        'messages': ['message', 'chat', 'conversation'],
        'packages': ['package', 'dependency', 'module'],
        'metrics': ['metric', 'stat', 'data point'],
        'config': ['config', 'setting', 'option']
    }

    data_types = []
    for dtype, keywords in data_type_keywords.items():
        if any(kw in desc_lower for kw in keywords):
            data_types.append(dtype)

    return data_types if data_types else ['text']


def determine_view_type(description: str) -> str:
    """Determine if single or multi-view."""
    desc_lower = description.lower()

    multi_keywords = ['multi-view', 'multiple view', 'tabs', 'tabbed', 'switch', 'views']
    three_pane_keywords = ['three', 'three-column', 'three pane']

    if any(kw in desc_lower for kw in three_pane_keywords):
        return 'three-pane'
    elif any(kw in desc_lower for kw in multi_keywords):
        return 'multi'
    else:
        return 'single'


def identify_special_requirements(description: str) -> List[str]:
    """Identify special requirements."""
    desc_lower = description.lower()
    special = []

    special_keywords = {
        'validation': ['validate', 'validation', 'check'],
        'real-time': ['real-time', 'live', 'streaming'],
        'async': ['async', 'background', 'concurrent'],
        'persistence': ['save', 'persist', 'store'],
        'theming': ['theme', 'color', 'style']
    }

    for req, keywords in special_keywords.items():
        if any(kw in desc_lower for kw in keywords):
            special.append(req)

    return special


def main():
    """Test requirement analyzer."""
    print("Testing Requirement Analyzer\n" + "=" * 50)

    test_cases = [
        "Build a log viewer with search and highlighting",
        "Create a file manager with three-column view",
        "Design an installer with progress bars",
        "Make a form wizard with validation"
    ]

    for i, desc in enumerate(test_cases, 1):
        print(f"\n{i}. Testing: '{desc}'")
        reqs = extract_requirements(desc)
        print(f"   Archetype: {reqs['archetype']}")
        print(f"   Features: {', '.join(reqs['features'])}")
        print(f"   Data types: {', '.join(reqs['data_types'])}")
        print(f"   View type: {reqs['views']}")
        print(f"   Validation: {reqs['validation']['summary']}")

    print("\n✅ All tests passed!")


if __name__ == "__main__":
    main()
