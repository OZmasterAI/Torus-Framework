#!/usr/bin/env python3
"""
Main TUI designer orchestrator.
Combines all analyses into comprehensive design report.
"""

import sys
import argparse
from pathlib import Path
from typing import Dict, Optional, List

sys.path.insert(0, str(Path(__file__).parent))

from analyze_requirements import extract_requirements
from map_components import map_to_components
from select_patterns import select_relevant_patterns
from design_architecture import design_architecture
from generate_workflow import generate_implementation_workflow
from utils.helpers import get_timestamp
from utils.template_generator import generate_main_go
from utils.validators import DesignValidator


def comprehensive_tui_design_report(
    description: str,
    inventory_path: Optional[str] = None,
    include_sections: Optional[List[str]] = None,
    detail_level: str = "complete"
) -> Dict:
    """
    Generate comprehensive TUI design report.

    This is the all-in-one function that combines all design analyses.

    Args:
        description: Natural language TUI description
        inventory_path: Path to charm-examples-inventory
        include_sections: Which sections to include (None = all)
        detail_level: "summary" | "detailed" | "complete"

    Returns:
        Complete design report dictionary with all sections

    Example:
        >>> report = comprehensive_tui_design_report(
        ...     "Build a log viewer with search"
        ... )
        >>> print(report['summary'])
        "TUI Design: Log Viewer..."
    """
    if include_sections is None:
        include_sections = ['requirements', 'components', 'patterns', 'architecture', 'workflow']

    report = {
        'description': description,
        'generated_at': get_timestamp(),
        'sections': {}
    }

    # Phase 1: Requirements Analysis
    if 'requirements' in include_sections:
        requirements = extract_requirements(description)
        report['sections']['requirements'] = requirements
        report['tui_type'] = requirements['archetype']
    else:
        requirements = extract_requirements(description)
        report['tui_type'] = requirements.get('archetype', 'general')

    # Phase 2: Component Mapping
    if 'components' in include_sections:
        components = map_to_components(requirements)
        report['sections']['components'] = components
    else:
        components = map_to_components(requirements)

    # Phase 3: Pattern Selection
    if 'patterns' in include_sections:
        patterns = select_relevant_patterns(components, inventory_path)
        report['sections']['patterns'] = patterns
    else:
        patterns = {'examples': []}

    # Phase 4: Architecture Design
    if 'architecture' in include_sections:
        architecture = design_architecture(components, patterns, requirements)
        report['sections']['architecture'] = architecture
    else:
        architecture = design_architecture(components, patterns, requirements)

    # Phase 5: Workflow Generation
    if 'workflow' in include_sections:
        workflow = generate_implementation_workflow(architecture, patterns)
        report['sections']['workflow'] = workflow

    # Generate summary
    report['summary'] = _generate_summary(report, requirements, components)

    # Generate code scaffolding
    if detail_level == "complete":
        primary_comps = [
            c['component'].replace('.Model', '')
            for c in components.get('primary_components', [])[:3]
        ]
        report['scaffolding'] = {
            'main_go': generate_main_go(primary_comps, requirements.get('archetype', 'general'))
        }

    # File structure recommendation
    report['file_structure'] = {
        'recommended': ['main.go', 'go.mod', 'README.md']
    }

    # Next steps
    report['next_steps'] = _generate_next_steps(patterns, workflow if 'workflow' in report['sections'] else None)

    # Resources
    report['resources'] = {
        'documentation': [
            'https://github.com/charmbracelet/bubbletea',
            'https://github.com/charmbracelet/lipgloss'
        ],
        'tutorials': [
            'Bubble Tea tutorial: https://github.com/charmbracelet/bubbletea/tree/master/tutorials'
        ],
        'community': [
            'Charm Discord: https://charm.sh/chat'
        ]
    }

    # Overall validation
    validator = DesignValidator()
    validation = validator.validate_design_report(report)
    report['validation'] = validation.to_dict()

    return report


def _generate_summary(report: Dict, requirements: Dict, components: Dict) -> str:
    """Generate executive summary."""
    tui_type = requirements.get('archetype', 'general')
    features = requirements.get('features', [])
    primary = components.get('primary_components', [])

    summary_parts = [
        f"TUI Design: {tui_type.replace('-', ' ').title()}",
        f"\nPurpose: {report.get('description', 'N/A')}",
        f"\nKey Features: {', '.join(features)}",
        f"\nPrimary Components: {', '.join([c['component'] for c in primary[:3]])}",
    ]

    if 'workflow' in report.get('sections', {}):
        summary_parts.append(
            f"\nEstimated Implementation Time: {report['sections']['workflow'].get('total_estimated_time', 'N/A')}"
        )

    return '\n'.join(summary_parts)


def _generate_next_steps(patterns: Dict, workflow: Optional[Dict]) -> List[str]:
    """Generate next steps list."""
    steps = ['1. Review the architecture diagram and component selection']

    examples = patterns.get('examples', [])
    if examples:
        steps.append(f'2. Study example files: {examples[0]["file"]}')

    if workflow:
        steps.append('3. Follow the implementation workflow starting with Phase 1')
        steps.append('4. Test at each checkpoint')

    steps.append('5. Refer to Bubble Tea documentation for component details')

    return steps


def main():
    """CLI for TUI designer."""
    parser = argparse.ArgumentParser(description='Bubble Tea TUI Designer')
    parser.add_argument('description', help='TUI description')
    parser.add_argument('--inventory', help='Path to charm-examples-inventory')
    parser.add_argument('--detail', choices=['summary', 'detailed', 'complete'], default='complete')

    args = parser.parse_args()

    print("=" * 60)
    print("Bubble Tea TUI Designer")
    print("=" * 60)

    report = comprehensive_tui_design_report(
        args.description,
        inventory_path=args.inventory,
        detail_level=args.detail
    )

    print(f"\n{report['summary']}")

    if 'architecture' in report['sections']:
        print("\n" + "=" * 60)
        print("ARCHITECTURE")
        print("=" * 60)
        print(report['sections']['architecture']['diagrams']['component_hierarchy'])

    if 'workflow' in report['sections']:
        print("\n" + "=" * 60)
        print("IMPLEMENTATION WORKFLOW")
        print("=" * 60)
        for phase in report['sections']['workflow']['phases']:
            print(f"\n{phase['name']} ({phase['total_time']})")
            for task in phase['tasks']:
                print(f"  - {task['task']}")

    print("\n" + "=" * 60)
    print("NEXT STEPS")
    print("=" * 60)
    for step in report['next_steps']:
        print(step)

    print("\n" + "=" * 60)
    print(f"Validation: {report['validation']['summary']}")
    print("=" * 60)


if __name__ == "__main__":
    main()
