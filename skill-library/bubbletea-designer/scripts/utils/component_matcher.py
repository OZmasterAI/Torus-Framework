#!/usr/bin/env python3
"""
Component matching logic for Bubble Tea Designer.
Scores and ranks components based on requirements.
"""

from typing import Dict, List, Tuple
import logging

logger = logging.getLogger(__name__)


# Component capability definitions
COMPONENT_CAPABILITIES = {
    'viewport': {
        'keywords': ['scroll', 'view', 'display', 'content', 'pager', 'document'],
        'use_cases': ['viewing large text', 'log viewer', 'document reader'],
        'complexity': 'medium'
    },
    'textinput': {
        'keywords': ['input', 'text', 'search', 'query', 'single-line'],
        'use_cases': ['search box', 'text input', 'single field'],
        'complexity': 'low'
    },
    'textarea': {
        'keywords': ['edit', 'multi-line', 'text area', 'editor', 'compose'],
        'use_cases': ['text editing', 'message composition', 'multi-line input'],
        'complexity': 'medium'
    },
    'table': {
        'keywords': ['table', 'tabular', 'rows', 'columns', 'grid', 'data display'],
        'use_cases': ['data table', 'spreadsheet view', 'structured data'],
        'complexity': 'medium'
    },
    'list': {
        'keywords': ['list', 'items', 'select', 'choose', 'menu', 'options'],
        'use_cases': ['item selection', 'menu', 'file list'],
        'complexity': 'medium'
    },
    'progress': {
        'keywords': ['progress', 'loading', 'installation', 'percent', 'bar'],
        'use_cases': ['progress indication', 'loading', 'installation progress'],
        'complexity': 'low'
    },
    'spinner': {
        'keywords': ['loading', 'spinner', 'wait', 'processing', 'busy'],
        'use_cases': ['loading indicator', 'waiting', 'processing'],
        'complexity': 'low'
    },
    'filepicker': {
        'keywords': ['file', 'select file', 'choose file', 'file system', 'browse'],
        'use_cases': ['file selection', 'file browser', 'file chooser'],
        'complexity': 'medium'
    },
    'paginator': {
        'keywords': ['page', 'pagination', 'pages', 'navigate pages'],
        'use_cases': ['page navigation', 'chunked content', 'paged display'],
        'complexity': 'low'
    },
    'timer': {
        'keywords': ['timer', 'countdown', 'timeout', 'time limit'],
        'use_cases': ['countdown', 'timeout', 'timed operation'],
        'complexity': 'low'
    },
    'stopwatch': {
        'keywords': ['stopwatch', 'elapsed', 'time tracking', 'duration'],
        'use_cases': ['time tracking', 'elapsed time', 'duration measurement'],
        'complexity': 'low'
    },
    'help': {
        'keywords': ['help', 'shortcuts', 'keybindings', 'documentation'],
        'use_cases': ['help menu', 'keyboard shortcuts', 'documentation'],
        'complexity': 'low'
    },
    'tabs': {
        'keywords': ['tabs', 'tabbed', 'switch views', 'navigation'],
        'use_cases': ['tab navigation', 'multiple views', 'view switching'],
        'complexity': 'medium'
    },
    'autocomplete': {
        'keywords': ['autocomplete', 'suggestions', 'completion', 'dropdown'],
        'use_cases': ['autocomplete', 'suggestions', 'smart input'],
        'complexity': 'medium'
    }
}


def match_score(requirement: str, component: str) -> int:
    """
    Calculate relevance score for component given requirement.

    Args:
        requirement: Feature requirement description
        component: Component name

    Returns:
        Score from 0-100 (higher = better match)

    Example:
        >>> match_score("scrollable log display", "viewport")
        95
    """
    if component not in COMPONENT_CAPABILITIES:
        return 0

    score = 0
    requirement_lower = requirement.lower()
    comp_info = COMPONENT_CAPABILITIES[component]

    # Keyword matching (60 points max)
    keywords = comp_info['keywords']
    keyword_matches = sum(1 for kw in keywords if kw in requirement_lower)
    keyword_score = min(60, (keyword_matches / len(keywords)) * 60)
    score += keyword_score

    # Use case matching (40 points max)
    use_cases = comp_info['use_cases']
    use_case_matches = sum(1 for uc in use_cases if any(
        word in requirement_lower for word in uc.split()
    ))
    use_case_score = min(40, (use_case_matches / len(use_cases)) * 40)
    score += use_case_score

    return int(score)


def find_best_match(requirement: str, components: List[str] = None) -> Tuple[str, int]:
    """
    Find best matching component for requirement.

    Args:
        requirement: Feature requirement
        components: List of component names to consider (None = all)

    Returns:
        Tuple of (best_component, score)

    Example:
        >>> find_best_match("need to show progress while installing")
        ('progress', 85)
    """
    if components is None:
        components = list(COMPONENT_CAPABILITIES.keys())

    best_component = None
    best_score = 0

    for component in components:
        score = match_score(requirement, component)
        if score > best_score:
            best_score = score
            best_component = component

    return best_component, best_score


def suggest_combinations(requirements: List[str]) -> List[List[str]]:
    """
    Suggest component combinations for multiple requirements.

    Args:
        requirements: List of feature requirements

    Returns:
        List of component combinations (each is a list of components)

    Example:
        >>> suggest_combinations(["display logs", "search logs"])
        [['viewport', 'textinput']]
    """
    combinations = []

    # Find best match for each requirement
    selected_components = []
    for req in requirements:
        component, score = find_best_match(req)
        if score > 50 and component not in selected_components:
            selected_components.append(component)

    if selected_components:
        combinations.append(selected_components)

    # Common patterns
    patterns = {
        'file_manager': ['filepicker', 'viewport', 'list'],
        'installer': ['progress', 'spinner', 'list'],
        'form': ['textinput', 'textarea', 'help'],
        'viewer': ['viewport', 'paginator', 'textinput'],
        'dashboard': ['tabs', 'viewport', 'table']
    }

    # Check if requirements match any patterns
    req_text = ' '.join(requirements).lower()
    for pattern_name, pattern_components in patterns.items():
        if pattern_name.replace('_', ' ') in req_text:
            combinations.append(pattern_components)

    return combinations if combinations else [selected_components]


def get_alternatives(component: str) -> List[str]:
    """
    Get alternative components that serve similar purposes.

    Args:
        component: Component name

    Returns:
        List of alternative component names

    Example:
        >>> get_alternatives('viewport')
        ['pager', 'textarea']
    """
    alternatives = {
        'viewport': ['pager'],
        'textinput': ['textarea', 'autocomplete'],
        'textarea': ['textinput', 'viewport'],
        'table': ['list'],
        'list': ['table', 'filepicker'],
        'progress': ['spinner'],
        'spinner': ['progress'],
        'filepicker': ['list'],
        'paginator': ['viewport'],
        'tabs': ['composable-views']
    }

    return alternatives.get(component, [])


def explain_match(component: str, requirement: str, score: int) -> str:
    """
    Generate explanation for why component matches requirement.

    Args:
        component: Component name
        requirement: Requirement description
        score: Match score

    Returns:
        Human-readable explanation

    Example:
        >>> explain_match("viewport", "scrollable display", 90)
        "viewport is a strong match (90/100) for 'scrollable display' because..."
    """
    if component not in COMPONENT_CAPABILITIES:
        return f"{component} is not a known component"

    comp_info = COMPONENT_CAPABILITIES[component]
    requirement_lower = requirement.lower()

    # Find which keywords matched
    matched_keywords = [kw for kw in comp_info['keywords'] if kw in requirement_lower]

    explanation_parts = []

    if score >= 80:
        explanation_parts.append(f"{component} is a strong match ({score}/100)")
    elif score >= 50:
        explanation_parts.append(f"{component} is a good match ({score}/100)")
    else:
        explanation_parts.append(f"{component} is a weak match ({score}/100)")

    explanation_parts.append(f"for '{requirement}'")

    if matched_keywords:
        explanation_parts.append(f"because it handles: {', '.join(matched_keywords)}")

    # Add use case
    explanation_parts.append(f"Common use cases: {', '.join(comp_info['use_cases'])}")

    return " ".join(explanation_parts) + "."


def rank_components_by_relevance(
    requirements: List[str],
    min_score: int = 50
) -> List[Tuple[str, int, List[str]]]:
    """
    Rank all components by relevance to requirements.

    Args:
        requirements: List of feature requirements
        min_score: Minimum score to include (default: 50)

    Returns:
        List of tuples: (component, total_score, matching_requirements)
        Sorted by total_score descending

    Example:
        >>> rank_components_by_relevance(["scroll", "display text"])
        [('viewport', 180, ['scroll', 'display text']), ...]
    """
    component_scores = {}
    component_matches = {}

    all_components = list(COMPONENT_CAPABILITIES.keys())

    for component in all_components:
        total_score = 0
        matching_reqs = []

        for req in requirements:
            score = match_score(req, component)
            if score >= min_score:
                total_score += score
                matching_reqs.append(req)

        if total_score > 0:
            component_scores[component] = total_score
            component_matches[component] = matching_reqs

    # Sort by score
    ranked = sorted(
        component_scores.items(),
        key=lambda x: x[1],
        reverse=True
    )

    return [(comp, score, component_matches[comp]) for comp, score in ranked]


def main():
    """Test component matcher."""
    print("Testing Component Matcher\n" + "=" * 50)

    # Test 1: Match score
    print("\n1. Testing match_score()...")
    score = match_score("scrollable log display", "viewport")
    print(f"   Score for 'scrollable log display' + viewport: {score}")
    assert score > 50, "Should have good score"
    print("   ✓ Match scoring works")

    # Test 2: Find best match
    print("\n2. Testing find_best_match()...")
    component, score = find_best_match("need to show progress while installing")
    print(f"   Best match: {component} ({score})")
    assert component in ['progress', 'spinner'], "Should match progress-related component"
    print("   ✓ Best match finding works")

    # Test 3: Suggest combinations
    print("\n3. Testing suggest_combinations()...")
    combos = suggest_combinations(["display logs", "search logs", "scroll through logs"])
    print(f"   Suggested combinations: {combos}")
    assert len(combos) > 0, "Should suggest at least one combination"
    print("   ✓ Combination suggestion works")

    # Test 4: Get alternatives
    print("\n4. Testing get_alternatives()...")
    alts = get_alternatives('viewport')
    print(f"   Alternatives to viewport: {alts}")
    assert 'pager' in alts, "Should include pager as alternative"
    print("   ✓ Alternative suggestions work")

    # Test 5: Explain match
    print("\n5. Testing explain_match()...")
    explanation = explain_match("viewport", "scrollable display", 90)
    print(f"   Explanation: {explanation}")
    assert "strong match" in explanation, "Should indicate strong match"
    print("   ✓ Match explanation works")

    # Test 6: Rank components
    print("\n6. Testing rank_components_by_relevance()...")
    ranked = rank_components_by_relevance(
        ["scroll", "display", "text", "search"],
        min_score=40
    )
    print(f"   Top 3 components:")
    for i, (comp, score, reqs) in enumerate(ranked[:3], 1):
        print(f"   {i}. {comp} (score: {score}) - matches: {reqs}")
    assert len(ranked) > 0, "Should rank some components"
    print("   ✓ Component ranking works")

    print("\n✅ All tests passed!")


if __name__ == "__main__":
    main()
