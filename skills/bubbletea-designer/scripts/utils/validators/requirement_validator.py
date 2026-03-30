#!/usr/bin/env python3
"""
Requirement validators for Bubble Tea Designer.
Validates user input and extracted requirements.
"""

from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum


class ValidationLevel(Enum):
    """Severity levels for validation results."""
    CRITICAL = "critical"
    WARNING = "warning"
    INFO = "info"


@dataclass
class ValidationResult:
    """Single validation check result."""
    check_name: str
    level: ValidationLevel
    passed: bool
    message: str
    details: Optional[Dict] = None


class ValidationReport:
    """Collection of validation results."""

    def __init__(self):
        self.results: List[ValidationResult] = []

    def add(self, result: ValidationResult):
        """Add validation result."""
        self.results.append(result)

    def has_critical_issues(self) -> bool:
        """Check if any critical issues found."""
        return any(
            r.level == ValidationLevel.CRITICAL and not r.passed
            for r in self.results
        )

    def all_passed(self) -> bool:
        """Check if all validations passed."""
        return all(r.passed for r in self.results)

    def get_warnings(self) -> List[str]:
        """Get all warning messages."""
        return [
            r.message for r in self.results
            if r.level == ValidationLevel.WARNING and not r.passed
        ]

    def get_summary(self) -> str:
        """Get summary of validation results."""
        total = len(self.results)
        passed = sum(1 for r in self.results if r.passed)
        critical = sum(
            1 for r in self.results
            if r.level == ValidationLevel.CRITICAL and not r.passed
        )

        return (
            f"Validation: {passed}/{total} passed "
            f"({critical} critical issues)"
        )

    def to_dict(self) -> Dict:
        """Convert to dictionary."""
        return {
            'passed': self.all_passed(),
            'summary': self.get_summary(),
            'warnings': self.get_warnings(),
            'critical_issues': [
                r.message for r in self.results
                if r.level == ValidationLevel.CRITICAL and not r.passed
            ],
            'all_results': [
                {
                    'check': r.check_name,
                    'level': r.level.value,
                    'passed': r.passed,
                    'message': r.message
                }
                for r in self.results
            ]
        }


class RequirementValidator:
    """Validates TUI requirements and descriptions."""

    def validate_description(self, description: str) -> ValidationReport:
        """
        Validate user-provided description.

        Args:
            description: Natural language TUI description

        Returns:
            ValidationReport with results
        """
        report = ValidationReport()

        # Check 1: Not empty
        report.add(ValidationResult(
            check_name="not_empty",
            level=ValidationLevel.CRITICAL,
            passed=bool(description and description.strip()),
            message="Description is empty" if not description else "Description provided"
        ))

        if not description:
            return report

        # Check 2: Minimum length (at least 10 words)
        words = description.split()
        min_words = 10
        has_min_length = len(words) >= min_words

        report.add(ValidationResult(
            check_name="minimum_length",
            level=ValidationLevel.WARNING,
            passed=has_min_length,
            message=f"Description has {len(words)} words (recommended: ≥{min_words})"
        ))

        # Check 3: Contains actionable verbs
        action_verbs = ['show', 'display', 'view', 'create', 'select', 'navigate',
                        'edit', 'input', 'track', 'monitor', 'search', 'filter']
        has_action = any(verb in description.lower() for verb in action_verbs)

        report.add(ValidationResult(
            check_name="has_actions",
            level=ValidationLevel.WARNING,
            passed=has_action,
            message="Description contains action verbs" if has_action else
                    "Consider adding action verbs (show, select, edit, etc.)"
        ))

        # Check 4: Contains data type mentions
        data_types = ['file', 'text', 'data', 'table', 'list', 'log', 'config',
                      'message', 'package', 'item', 'entry']
        has_data = any(dtype in description.lower() for dtype in data_types)

        report.add(ValidationResult(
            check_name="has_data_types",
            level=ValidationLevel.INFO,
            passed=has_data,
            message="Data types mentioned" if has_data else
                    "No explicit data types mentioned"
        ))

        return report

    def validate_requirements(self, requirements: Dict) -> ValidationReport:
        """
        Validate extracted requirements structure.

        Args:
            requirements: Structured requirements dict

        Returns:
            ValidationReport
        """
        report = ValidationReport()

        # Check 1: Has archetype
        has_archetype = 'archetype' in requirements and requirements['archetype']
        report.add(ValidationResult(
            check_name="has_archetype",
            level=ValidationLevel.CRITICAL,
            passed=has_archetype,
            message=f"TUI archetype: {requirements.get('archetype', 'MISSING')}"
        ))

        # Check 2: Has features
        features = requirements.get('features', [])
        has_features = len(features) > 0
        report.add(ValidationResult(
            check_name="has_features",
            level=ValidationLevel.CRITICAL,
            passed=has_features,
            message=f"Features identified: {len(features)}"
        ))

        # Check 3: Has interactions
        interactions = requirements.get('interactions', {})
        keyboard_interactions = interactions.get('keyboard', [])
        has_interactions = len(keyboard_interactions) > 0

        report.add(ValidationResult(
            check_name="has_interactions",
            level=ValidationLevel.WARNING,
            passed=has_interactions,
            message=f"Keyboard interactions: {len(keyboard_interactions)}"
        ))

        # Check 4: Has view specification
        views = requirements.get('views', '')
        has_views = bool(views)
        report.add(ValidationResult(
            check_name="has_view_spec",
            level=ValidationLevel.WARNING,
            passed=has_views,
            message=f"View type: {views or 'unspecified'}"
        ))

        # Check 5: Completeness (has all expected keys)
        expected_keys = ['archetype', 'features', 'interactions', 'data_types', 'views']
        missing_keys = set(expected_keys) - set(requirements.keys())

        report.add(ValidationResult(
            check_name="completeness",
            level=ValidationLevel.INFO,
            passed=len(missing_keys) == 0,
            message=f"Complete structure" if not missing_keys else
                    f"Missing keys: {missing_keys}"
        ))

        return report

    def suggest_clarifications(self, requirements: Dict) -> List[str]:
        """
        Suggest clarifying questions based on incomplete requirements.

        Args:
            requirements: Extracted requirements

        Returns:
            List of clarifying questions to ask user
        """
        questions = []

        # Check if archetype is unclear
        if not requirements.get('archetype') or requirements['archetype'] == 'general':
            questions.append(
                "What type of TUI is this? (file manager, installer, dashboard, "
                "form, viewer, etc.)"
            )

        # Check if features are vague
        features = requirements.get('features', [])
        if len(features) < 2:
            questions.append(
                "What are the main features/capabilities needed? "
                "(e.g., navigation, selection, editing, search, filtering)"
            )

        # Check if data type is unspecified
        data_types = requirements.get('data_types', [])
        if not data_types:
            questions.append(
                "What type of data will the TUI display? "
                "(files, text, tabular data, logs, etc.)"
            )

        # Check if interaction is unspecified
        interactions = requirements.get('interactions', {})
        if not interactions.get('keyboard') and not interactions.get('mouse'):
            questions.append(
                "How should users interact? Keyboard only, or mouse support needed?"
            )

        # Check if view type is unspecified
        if not requirements.get('views'):
            questions.append(
                "Should this be single-view or multi-view? Need tabs or navigation?"
            )

        return questions


def validate_description_clarity(description: str) -> Tuple[bool, str]:
    """
    Quick validation of description clarity.

    Args:
        description: User description

    Returns:
        Tuple of (is_clear, message)
    """
    validator = RequirementValidator()
    report = validator.validate_description(description)

    if report.has_critical_issues():
        return False, "Description has critical issues: " + report.get_summary()

    warnings = report.get_warnings()
    if warnings:
        return True, "Description OK with suggestions: " + "; ".join(warnings)

    return True, "Description is clear"


def validate_requirements_completeness(requirements: Dict) -> Tuple[bool, str]:
    """
    Quick validation of requirements completeness.

    Args:
        requirements: Extracted requirements dict

    Returns:
        Tuple of (is_complete, message)
    """
    validator = RequirementValidator()
    report = validator.validate_requirements(requirements)

    if report.has_critical_issues():
        return False, "Requirements incomplete: " + report.get_summary()

    warnings = report.get_warnings()
    if warnings:
        return True, "Requirements OK with warnings: " + "; ".join(warnings)

    return True, "Requirements complete"


def main():
    """Test requirement validator."""
    print("Testing Requirement Validator\n" + "=" * 50)

    validator = RequirementValidator()

    # Test 1: Empty description
    print("\n1. Testing empty description...")
    report = validator.validate_description("")
    print(f"   {report.get_summary()}")
    assert report.has_critical_issues(), "Should fail for empty description"
    print("   ✓ Correctly detected empty description")

    # Test 2: Good description
    print("\n2. Testing good description...")
    good_desc = "Create a file manager TUI with three-column view showing parent directory, current directory, and file preview"
    report = validator.validate_description(good_desc)
    print(f"   {report.get_summary()}")
    print("   ✓ Good description validated")

    # Test 3: Vague description
    print("\n3. Testing vague description...")
    vague_desc = "Build a TUI"
    report = validator.validate_description(vague_desc)
    print(f"   {report.get_summary()}")
    warnings = report.get_warnings()
    if warnings:
        print(f"   Warnings: {warnings}")
    print("   ✓ Vague description detected")

    # Test 4: Requirements validation
    print("\n4. Testing requirements validation...")
    requirements = {
        'archetype': 'file-manager',
        'features': ['navigation', 'selection', 'preview'],
        'interactions': {
            'keyboard': ['arrows', 'enter', 'backspace'],
            'mouse': []
        },
        'data_types': ['files', 'directories'],
        'views': 'multi'
    }
    report = validator.validate_requirements(requirements)
    print(f"   {report.get_summary()}")
    assert report.all_passed(), "Should pass for complete requirements"
    print("   ✓ Complete requirements validated")

    # Test 5: Incomplete requirements
    print("\n5. Testing incomplete requirements...")
    incomplete = {
        'archetype': '',
        'features': []
    }
    report = validator.validate_requirements(incomplete)
    print(f"   {report.get_summary()}")
    assert report.has_critical_issues(), "Should fail for incomplete requirements"
    print("   ✓ Incomplete requirements detected")

    # Test 6: Clarification suggestions
    print("\n6. Testing clarification suggestions...")
    questions = validator.suggest_clarifications(incomplete)
    print(f"   Generated {len(questions)} clarifying questions:")
    for i, q in enumerate(questions, 1):
        print(f"   {i}. {q}")
    print("   ✓ Clarifications generated")

    print("\n✅ All tests passed!")


if __name__ == "__main__":
    main()
