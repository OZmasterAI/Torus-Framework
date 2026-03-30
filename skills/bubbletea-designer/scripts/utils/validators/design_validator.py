#!/usr/bin/env python3
"""
Design validators for Bubble Tea Designer.
Validates design outputs (component selections, architecture, workflows).
"""

from typing import Dict, List, Optional
from .requirement_validator import ValidationReport, ValidationResult, ValidationLevel


class DesignValidator:
    """Validates TUI design outputs."""

    def validate_component_selection(
        self,
        components: Dict,
        requirements: Dict
    ) -> ValidationReport:
        """
        Validate component selection against requirements.

        Args:
            components: Selected components dict
            requirements: Original requirements

        Returns:
            ValidationReport
        """
        report = ValidationReport()

        # Check 1: At least one component selected
        primary = components.get('primary_components', [])
        has_components = len(primary) > 0

        report.add(ValidationResult(
            check_name="has_components",
            level=ValidationLevel.CRITICAL,
            passed=has_components,
            message=f"Primary components selected: {len(primary)}"
        ))

        # Check 2: Components cover requirements
        features = set(requirements.get('features', []))
        if features and primary:
            # Check if components mention required features
            covered_features = set()
            for comp in primary:
                justification = comp.get('justification', '').lower()
                for feature in features:
                    if feature.lower() in justification:
                        covered_features.add(feature)

            coverage = len(covered_features) / len(features) * 100 if features else 0
            report.add(ValidationResult(
                check_name="feature_coverage",
                level=ValidationLevel.WARNING,
                passed=coverage >= 50,
                message=f"Feature coverage: {coverage:.0f}% ({len(covered_features)}/{len(features)})"
            ))

        # Check 3: No duplicate components
        comp_names = [c.get('component', '') for c in primary]
        duplicates = [name for name in comp_names if comp_names.count(name) > 1]

        report.add(ValidationResult(
            check_name="no_duplicates",
            level=ValidationLevel.WARNING,
            passed=len(duplicates) == 0,
            message="No duplicate components" if not duplicates else
                    f"Duplicate components: {set(duplicates)}"
        ))

        # Check 4: Reasonable number of components (not too many)
        reasonable_count = len(primary) <= 6
        report.add(ValidationResult(
            check_name="reasonable_count",
            level=ValidationLevel.INFO,
            passed=reasonable_count,
            message=f"Component count: {len(primary)} ({'reasonable' if reasonable_count else 'may be too many'})"
        ))

        # Check 5: Each component has justification
        all_justified = all('justification' in c for c in primary)
        report.add(ValidationResult(
            check_name="all_justified",
            level=ValidationLevel.INFO,
            passed=all_justified,
            message="All components justified" if all_justified else
                    "Some components missing justification"
        ))

        return report

    def validate_architecture(self, architecture: Dict) -> ValidationReport:
        """
        Validate architecture design.

        Args:
            architecture: Architecture specification

        Returns:
            ValidationReport
        """
        report = ValidationReport()

        # Check 1: Has model struct
        has_model = 'model_struct' in architecture and architecture['model_struct']
        report.add(ValidationResult(
            check_name="has_model_struct",
            level=ValidationLevel.CRITICAL,
            passed=has_model,
            message="Model struct defined" if has_model else "Missing model struct"
        ))

        # Check 2: Has message handlers
        handlers = architecture.get('message_handlers', {})
        has_handlers = len(handlers) > 0

        report.add(ValidationResult(
            check_name="has_message_handlers",
            level=ValidationLevel.CRITICAL,
            passed=has_handlers,
            message=f"Message handlers defined: {len(handlers)}"
        ))

        # Check 3: Has key message handler (keyboard)
        has_key_handler = 'tea.KeyMsg' in handlers or 'KeyMsg' in handlers

        report.add(ValidationResult(
            check_name="has_keyboard_handler",
            level=ValidationLevel.WARNING,
            passed=has_key_handler,
            message="Keyboard handler present" if has_key_handler else
                    "Missing keyboard handler (tea.KeyMsg)"
        ))

        # Check 4: Has view logic
        has_view = 'view_logic' in architecture and architecture['view_logic']
        report.add(ValidationResult(
            check_name="has_view_logic",
            level=ValidationLevel.CRITICAL,
            passed=has_view,
            message="View logic defined" if has_view else "Missing view logic"
        ))

        # Check 5: Has diagrams
        diagrams = architecture.get('diagrams', {})
        has_diagrams = len(diagrams) > 0

        report.add(ValidationResult(
            check_name="has_diagrams",
            level=ValidationLevel.INFO,
            passed=has_diagrams,
            message=f"Architecture diagrams: {len(diagrams)}"
        ))

        return report

    def validate_workflow_completeness(self, workflow: Dict) -> ValidationReport:
        """
        Validate workflow has all necessary phases and tasks.

        Args:
            workflow: Workflow specification

        Returns:
            ValidationReport
        """
        report = ValidationReport()

        # Check 1: Has phases
        phases = workflow.get('phases', [])
        has_phases = len(phases) > 0

        report.add(ValidationResult(
            check_name="has_phases",
            level=ValidationLevel.CRITICAL,
            passed=has_phases,
            message=f"Workflow phases: {len(phases)}"
        ))

        if not phases:
            return report

        # Check 2: Each phase has tasks
        all_have_tasks = all(len(phase.get('tasks', [])) > 0 for phase in phases)

        report.add(ValidationResult(
            check_name="all_phases_have_tasks",
            level=ValidationLevel.WARNING,
            passed=all_have_tasks,
            message="All phases have tasks" if all_have_tasks else
                    "Some phases are missing tasks"
        ))

        # Check 3: Has testing checkpoints
        checkpoints = workflow.get('testing_checkpoints', [])
        has_testing = len(checkpoints) > 0

        report.add(ValidationResult(
            check_name="has_testing",
            level=ValidationLevel.WARNING,
            passed=has_testing,
            message=f"Testing checkpoints: {len(checkpoints)}"
        ))

        # Check 4: Reasonable phase count (2-6 phases)
        reasonable_phases = 2 <= len(phases) <= 6

        report.add(ValidationResult(
            check_name="reasonable_phases",
            level=ValidationLevel.INFO,
            passed=reasonable_phases,
            message=f"Phase count: {len(phases)} ({'good' if reasonable_phases else 'unusual'})"
        ))

        # Check 5: Has time estimates
        total_time = workflow.get('total_estimated_time')
        has_estimate = bool(total_time)

        report.add(ValidationResult(
            check_name="has_time_estimate",
            level=ValidationLevel.INFO,
            passed=has_estimate,
            message=f"Time estimate: {total_time or 'missing'}"
        ))

        return report

    def validate_design_report(self, report_data: Dict) -> ValidationReport:
        """
        Validate complete design report.

        Args:
            report_data: Complete design report

        Returns:
            ValidationReport
        """
        report = ValidationReport()

        # Check all required sections present
        required_sections = ['requirements', 'components', 'patterns', 'architecture', 'workflow']
        sections = report_data.get('sections', {})

        for section in required_sections:
            has_section = section in sections and sections[section]
            report.add(ValidationResult(
                check_name=f"has_{section}_section",
                level=ValidationLevel.CRITICAL,
                passed=has_section,
                message=f"Section '{section}': {'present' if has_section else 'MISSING'}"
            ))

        # Check has summary
        has_summary = 'summary' in report_data and report_data['summary']
        report.add(ValidationResult(
            check_name="has_summary",
            level=ValidationLevel.WARNING,
            passed=has_summary,
            message="Summary present" if has_summary else "Missing summary"
        ))

        # Check has scaffolding
        has_scaffolding = 'scaffolding' in report_data and report_data['scaffolding']
        report.add(ValidationResult(
            check_name="has_scaffolding",
            level=ValidationLevel.INFO,
            passed=has_scaffolding,
            message="Code scaffolding included" if has_scaffolding else
                    "No code scaffolding"
        ))

        # Check has next steps
        next_steps = report_data.get('next_steps', [])
        has_next_steps = len(next_steps) > 0

        report.add(ValidationResult(
            check_name="has_next_steps",
            level=ValidationLevel.INFO,
            passed=has_next_steps,
            message=f"Next steps: {len(next_steps)}"
        ))

        return report


def validate_component_fit(component: str, requirement: str) -> bool:
    """
    Quick check if component fits requirement.

    Args:
        component: Component name (e.g., "viewport.Model")
        requirement: Requirement description

    Returns:
        True if component appears suitable
    """
    component_lower = component.lower()
    requirement_lower = requirement.lower()

    # Simple keyword matching
    keyword_map = {
        'viewport': ['scroll', 'view', 'display', 'content'],
        'textinput': ['input', 'text', 'search', 'query'],
        'textarea': ['edit', 'multi-line', 'text area'],
        'table': ['table', 'tabular', 'rows', 'columns'],
        'list': ['list', 'items', 'select', 'choose'],
        'progress': ['progress', 'loading', 'installation'],
        'spinner': ['loading', 'spinner', 'wait'],
        'filepicker': ['file', 'select file', 'choose file']
    }

    for comp_key, keywords in keyword_map.items():
        if comp_key in component_lower:
            return any(kw in requirement_lower for kw in keywords)

    return False


def main():
    """Test design validator."""
    print("Testing Design Validator\n" + "=" * 50)

    validator = DesignValidator()

    # Test 1: Component selection validation
    print("\n1. Testing component selection validation...")
    components = {
        'primary_components': [
            {
                'component': 'viewport.Model',
                'score': 95,
                'justification': 'Scrollable display for log content'
            },
            {
                'component': 'textinput.Model',
                'score': 90,
                'justification': 'Search query input'
            }
        ]
    }
    requirements = {
        'features': ['display', 'search', 'scroll']
    }
    report = validator.validate_component_selection(components, requirements)
    print(f"   {report.get_summary()}")
    assert not report.has_critical_issues(), "Should pass for valid components"
    print("   ✓ Component selection validated")

    # Test 2: Architecture validation
    print("\n2. Testing architecture validation...")
    architecture = {
        'model_struct': 'type model struct {...}',
        'message_handlers': {
            'tea.KeyMsg': 'handle keyboard',
            'tea.WindowSizeMsg': 'handle resize'
        },
        'view_logic': 'func (m model) View() string {...}',
        'diagrams': {
            'component_hierarchy': '...'
        }
    }
    report = validator.validate_architecture(architecture)
    print(f"   {report.get_summary()}")
    assert report.all_passed(), "Should pass for complete architecture"
    print("   ✓ Architecture validated")

    # Test 3: Workflow validation
    print("\n3. Testing workflow validation...")
    workflow = {
        'phases': [
            {
                'name': 'Phase 1: Setup',
                'tasks': [
                    {'task': 'Initialize project'},
                    {'task': 'Install dependencies'}
                ]
            },
            {
                'name': 'Phase 2: Core',
                'tasks': [
                    {'task': 'Implement viewport'}
                ]
            }
        ],
        'testing_checkpoints': ['After Phase 1', 'After Phase 2'],
        'total_estimated_time': '2 hours'
    }
    report = validator.validate_workflow_completeness(workflow)
    print(f"   {report.get_summary()}")
    assert report.all_passed(), "Should pass for complete workflow"
    print("   ✓ Workflow validated")

    # Test 4: Complete design report validation
    print("\n4. Testing complete design report validation...")
    design_report = {
        'sections': {
            'requirements': {...},
            'components': {...},
            'patterns': {...},
            'architecture': {...},
            'workflow': {...}
        },
        'summary': 'TUI design for log viewer',
        'scaffolding': 'package main...',
        'next_steps': ['Step 1', 'Step 2']
    }
    report = validator.validate_design_report(design_report)
    print(f"   {report.get_summary()}")
    assert report.all_passed(), "Should pass for complete report"
    print("   ✓ Design report validated")

    # Test 5: Component fit check
    print("\n5. Testing component fit check...")
    assert validate_component_fit("viewport.Model", "scrollable log display")
    assert validate_component_fit("textinput.Model", "search query input")
    assert not validate_component_fit("spinner.Model", "text input field")
    print("   ✓ Component fit checks working")

    print("\n✅ All tests passed!")


if __name__ == "__main__":
    main()
