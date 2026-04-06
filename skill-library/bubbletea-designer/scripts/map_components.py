#!/usr/bin/env python3
"""
Component mapper for Bubble Tea TUIs.
Maps requirements to appropriate components.
"""

import sys
from pathlib import Path
from typing import Dict, List

sys.path.insert(0, str(Path(__file__).parent))

from utils.component_matcher import (
    match_score,
    find_best_match,
    get_alternatives,
    explain_match,
    rank_components_by_relevance
)
from utils.validators import DesignValidator


def map_to_components(requirements: Dict, inventory=None) -> Dict:
    """
    Map requirements to Bubble Tea components.

    Args:
        requirements: Structured requirements from analyze_requirements
        inventory: Optional inventory object (unused for now)

    Returns:
        Dictionary with component recommendations

    Example:
        >>> components = map_to_components(reqs)
        >>> components['primary_components'][0]['component']
        'viewport.Model'
    """
    features = requirements.get('features', [])
    archetype = requirements.get('archetype', 'general')
    data_types = requirements.get('data_types', [])
    views = requirements.get('views', 'single')

    # Get ranked components
    ranked = rank_components_by_relevance(features, min_score=50)

    # Build primary components list
    primary_components = []
    for component, score, matching_features in ranked[:5]:  # Top 5
        justification = explain_match(component, ' '.join(matching_features), score)

        primary_components.append({
            'component': f'{component}.Model',
            'score': score,
            'justification': justification,
            'example_file': f'examples/{component}/main.go',
            'key_patterns': [f'{component} usage', 'initialization', 'message handling']
        })

    # Add archetype-specific components
    archetype_components = _get_archetype_components(archetype)
    for comp in archetype_components:
        if not any(c['component'].startswith(comp) for c in primary_components):
            primary_components.append({
                'component': f'{comp}.Model',
                'score': 70,
                'justification': f'Standard component for {archetype} TUIs',
                'example_file': f'examples/{comp}/main.go',
                'key_patterns': [f'{comp} patterns']
            })

    # Supporting components
    supporting = _get_supporting_components(features, views)

    # Styling
    styling = ['lipgloss for layout and styling']
    if 'highlighting' in features:
        styling.append('lipgloss for text highlighting')

    # Alternatives
    alternatives = {}
    for comp in primary_components[:3]:
        comp_name = comp['component'].replace('.Model', '')
        alts = get_alternatives(comp_name)
        if alts:
            alternatives[comp['component']] = [f'{alt}.Model' for alt in alts]

    result = {
        'primary_components': primary_components,
        'supporting_components': supporting,
        'styling': styling,
        'alternatives': alternatives
    }

    # Validate
    validator = DesignValidator()
    validation = validator.validate_component_selection(result, requirements)

    result['validation'] = validation.to_dict()

    return result


def _get_archetype_components(archetype: str) -> List[str]:
    """Get standard components for archetype."""
    archetype_map = {
        'file-manager': ['filepicker', 'viewport', 'list'],
        'installer': ['progress', 'spinner', 'list'],
        'dashboard': ['tabs', 'viewport', 'table'],
        'form': ['textinput', 'textarea', 'help'],
        'viewer': ['viewport', 'paginator', 'textinput'],
        'chat': ['viewport', 'textarea', 'textinput'],
        'table-viewer': ['table', 'paginator'],
        'menu': ['list'],
        'editor': ['textarea', 'viewport']
    }
    return archetype_map.get(archetype, [])


def _get_supporting_components(features: List[str], views: str) -> List[str]:
    """Get supporting components based on features."""
    supporting = []

    if views in ['multi', 'three-pane']:
        supporting.append('Multiple viewports for multi-pane layout')

    if 'help' not in features:
        supporting.append('help.Model for keyboard shortcuts')

    if views == 'multi':
        supporting.append('tabs.Model or state machine for view switching')

    return supporting


def main():
    """Test component mapper."""
    print("Testing Component Mapper\n" + "=" * 50)

    # Mock requirements
    requirements = {
        'archetype': 'viewer',
        'features': ['display', 'search', 'scrolling'],
        'data_types': ['text'],
        'views': 'single'
    }

    print("\n1. Testing map_to_components()...")
    components = map_to_components(requirements)

    print(f"   Primary components: {len(components['primary_components'])}")
    for comp in components['primary_components'][:3]:
        print(f"   - {comp['component']} (score: {comp['score']})")

    print(f"\n   Validation: {components['validation']['summary']}")

    print("\n✅ Tests passed!")


if __name__ == "__main__":
    main()
