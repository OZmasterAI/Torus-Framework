#!/usr/bin/env python3
"""
Integration tests for Bubble Tea Designer.
Tests complete workflows from description to design report.
"""

import sys
from pathlib import Path

# Add scripts to path
sys.path.insert(0, str(Path(__file__).parent.parent / 'scripts'))

from analyze_requirements import extract_requirements
from map_components import map_to_components
from design_architecture import design_architecture
from generate_workflow import generate_implementation_workflow
from design_tui import comprehensive_tui_design_report


def test_analyze_requirements_basic():
    """Test requirement extraction from simple description."""
    print("\n✓ Testing extract_requirements()...")

    description = "Build a log viewer with search and highlighting"
    result = extract_requirements(description)

    # Validations
    assert 'archetype' in result, "Missing 'archetype' in result"
    assert 'features' in result, "Missing 'features'"
    assert result['archetype'] == 'viewer', f"Expected 'viewer', got {result['archetype']}"
    assert 'search' in result['features'], "Should identify 'search' feature"

    print(f"  ✓ Archetype: {result['archetype']}")
    print(f"  ✓ Features: {', '.join(result['features'])}")
    print(f"  ✓ Validation: {result['validation']['summary']}")

    return True


def test_map_components_viewer():
    """Test component mapping for viewer archetype."""
    print("\n✓ Testing map_to_components()...")

    requirements = {
        'archetype': 'viewer',
        'features': ['display', 'search', 'scrolling'],
        'data_types': ['text'],
        'views': 'single'
    }

    result = map_to_components(requirements)

    # Validations
    assert 'primary_components' in result, "Missing 'primary_components'"
    assert len(result['primary_components']) > 0, "No components selected"

    # Should include viewport for viewing
    comp_names = [c['component'] for c in result['primary_components']]
    has_viewport = any('viewport' in name.lower() for name in comp_names)

    print(f"  ✓ Components selected: {len(result['primary_components'])}")
    print(f"  ✓ Top component: {result['primary_components'][0]['component']}")
    print(f"  ✓ Has viewport: {has_viewport}")

    return True


def test_design_architecture():
    """Test architecture generation."""
    print("\n✓ Testing design_architecture()...")

    components = {
        'primary_components': [
            {'component': 'viewport.Model', 'score': 90},
            {'component': 'textinput.Model', 'score': 85}
        ]
    }

    requirements = {
        'archetype': 'viewer',
        'views': 'single'
    }

    result = design_architecture(components, {}, requirements)

    # Validations
    assert 'model_struct' in result, "Missing 'model_struct'"
    assert 'message_handlers' in result, "Missing 'message_handlers'"
    assert 'diagrams' in result, "Missing 'diagrams'"
    assert 'tea.KeyMsg' in result['message_handlers'], "Missing keyboard handler"

    print(f"  ✓ Model struct generated: {len(result['model_struct'])} chars")
    print(f"  ✓ Message handlers: {len(result['message_handlers'])}")
    print(f"  ✓ Diagrams: {len(result['diagrams'])}")

    return True


def test_generate_workflow():
    """Test workflow generation."""
    print("\n✓ Testing generate_implementation_workflow()...")

    architecture = {
        'model_struct': 'type model struct { ... }',
        'message_handlers': {'tea.KeyMsg': '...'}
    }

    result = generate_implementation_workflow(architecture, {})

    # Validations
    assert 'phases' in result, "Missing 'phases'"
    assert 'testing_checkpoints' in result, "Missing 'testing_checkpoints'"
    assert len(result['phases']) >= 2, "Should have multiple phases"

    print(f"  ✓ Workflow phases: {len(result['phases'])}")
    print(f"  ✓ Testing checkpoints: {len(result['testing_checkpoints'])}")
    print(f"  ✓ Estimated time: {result.get('total_estimated_time', 'N/A')}")

    return True


def test_comprehensive_report_log_viewer():
    """Test comprehensive report for log viewer."""
    print("\n✓ Testing comprehensive_tui_design_report() - Log Viewer...")

    description = "Build a log viewer with search and highlighting"
    result = comprehensive_tui_design_report(description)

    # Validations
    assert 'description' in result, "Missing 'description'"
    assert 'summary' in result, "Missing 'summary'"
    assert 'sections' in result, "Missing 'sections'"

    sections = result['sections']
    assert 'requirements' in sections, "Missing 'requirements' section"
    assert 'components' in sections, "Missing 'components' section"
    assert 'architecture' in sections, "Missing 'architecture' section"
    assert 'workflow' in sections, "Missing 'workflow' section"

    print(f"  ✓ TUI type: {result.get('tui_type', 'N/A')}")
    print(f"  ✓ Sections: {len(sections)}")
    print(f"  ✓ Summary: {result['summary'][:100]}...")
    print(f"  ✓ Validation: {result['validation']['summary']}")

    return True


def test_comprehensive_report_file_manager():
    """Test comprehensive report for file manager."""
    print("\n✓ Testing comprehensive_tui_design_report() - File Manager...")

    description = "Create a file manager with three-column view"
    result = comprehensive_tui_design_report(description)

    # Validations
    assert result.get('tui_type') == 'file-manager', f"Expected 'file-manager', got {result.get('tui_type')}"

    reqs = result['sections']['requirements']
    assert 'filepicker' in str(reqs).lower() or 'list' in str(reqs).lower(), \
        "Should suggest file-related components"

    print(f"  ✓ TUI type: {result['tui_type']}")
    print(f"  ✓ Archetype correct")

    return True


def test_comprehensive_report_installer():
    """Test comprehensive report for installer."""
    print("\n✓ Testing comprehensive_tui_design_report() - Installer...")

    description = "Design an installer with progress bars for packages"
    result = comprehensive_tui_design_report(description)

    # Validations
    assert result.get('tui_type') == 'installer', f"Expected 'installer', got {result.get('tui_type')}"

    components = result['sections']['components']
    comp_names = str([c['component'] for c in components.get('primary_components', [])])
    assert 'progress' in comp_names.lower() or 'spinner' in comp_names.lower(), \
        "Should suggest progress components"

    print(f"  ✓ TUI type: {result['tui_type']}")
    print(f"  ✓ Progress components suggested")

    return True


def test_validation_integration():
    """Test that validation is integrated in all functions."""
    print("\n✓ Testing validation integration...")

    description = "Build a log viewer"
    result = comprehensive_tui_design_report(description)

    # Check each section has validation
    sections = result['sections']

    if 'requirements' in sections:
        assert 'validation' in sections['requirements'], "Requirements should have validation"
        print("  ✓ Requirements validated")

    if 'components' in sections:
        assert 'validation' in sections['components'], "Components should have validation"
        print("  ✓ Components validated")

    if 'architecture' in sections:
        assert 'validation' in sections['architecture'], "Architecture should have validation"
        print("  ✓ Architecture validated")

    if 'workflow' in sections:
        assert 'validation' in sections['workflow'], "Workflow should have validation"
        print("  ✓ Workflow validated")

    # Overall validation
    assert 'validation' in result, "Report should have overall validation"
    print("  ✓ Overall report validated")

    return True


def test_code_scaffolding():
    """Test code scaffolding generation."""
    print("\n✓ Testing code scaffolding generation...")

    description = "Simple log viewer"
    result = comprehensive_tui_design_report(description, detail_level="complete")

    # Validations
    assert 'scaffolding' in result, "Missing 'scaffolding'"
    assert 'main_go' in result['scaffolding'], "Missing 'main_go' scaffold"

    main_go = result['scaffolding']['main_go']
    assert 'package main' in main_go, "Should have package main"
    assert 'type model struct' in main_go, "Should have model struct"
    assert 'func main()' in main_go, "Should have main function"

    print(f"  ✓ Scaffolding generated: {len(main_go)} chars")
    print("  ✓ Contains package main")
    print("  ✓ Contains model struct")
    print("  ✓ Contains main function")

    return True


def main():
    """Run all integration tests."""
    print("=" * 70)
    print("INTEGRATION TESTS - Bubble Tea Designer")
    print("=" * 70)

    tests = [
        ("Requirement extraction", test_analyze_requirements_basic),
        ("Component mapping", test_map_components_viewer),
        ("Architecture design", test_design_architecture),
        ("Workflow generation", test_generate_workflow),
        ("Comprehensive report - Log Viewer", test_comprehensive_report_log_viewer),
        ("Comprehensive report - File Manager", test_comprehensive_report_file_manager),
        ("Comprehensive report - Installer", test_comprehensive_report_installer),
        ("Validation integration", test_validation_integration),
        ("Code scaffolding", test_code_scaffolding),
    ]

    results = []
    for test_name, test_func in tests:
        try:
            passed = test_func()
            results.append((test_name, passed))
        except Exception as e:
            print(f"\n  ❌ FAILED: {e}")
            import traceback
            traceback.print_exc()
            results.append((test_name, False))

    # Summary
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)

    for test_name, passed in results:
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{status}: {test_name}")

    passed_count = sum(1 for _, p in results if p)
    total_count = len(results)

    print(f"\nResults: {passed_count}/{total_count} passed")

    return passed_count == total_count


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
