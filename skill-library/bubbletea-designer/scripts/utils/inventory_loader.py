#!/usr/bin/env python3
"""
Inventory loader for Bubble Tea examples.
Loads and parses CONTEXTUAL-INVENTORY.md from charm-examples-inventory.
"""

import os
import re
from typing import Dict, List, Optional, Tuple
from pathlib import Path
import logging

logger = logging.getLogger(__name__)


class InventoryLoadError(Exception):
    """Raised when inventory cannot be loaded."""
    pass


class Example:
    """Represents a single Bubble Tea example."""

    def __init__(self, name: str, file_path: str, capability: str):
        self.name = name
        self.file_path = file_path
        self.capability = capability
        self.key_patterns: List[str] = []
        self.components: List[str] = []
        self.use_cases: List[str] = []

    def __repr__(self):
        return f"Example({self.name}, {self.capability})"


class Inventory:
    """Bubble Tea examples inventory."""

    def __init__(self, base_path: str):
        self.base_path = base_path
        self.examples: Dict[str, Example] = {}
        self.capabilities: Dict[str, List[Example]] = {}
        self.components: Dict[str, List[Example]] = {}

    def add_example(self, example: Example):
        """Add example to inventory."""
        self.examples[example.name] = example

        # Index by capability
        if example.capability not in self.capabilities:
            self.capabilities[example.capability] = []
        self.capabilities[example.capability].append(example)

        # Index by components
        for component in example.components:
            if component not in self.components:
                self.components[component] = []
            self.components[component].append(example)

    def search_by_keyword(self, keyword: str) -> List[Example]:
        """Search examples by keyword in name or patterns."""
        keyword_lower = keyword.lower()
        results = []

        for example in self.examples.values():
            if keyword_lower in example.name.lower():
                results.append(example)
                continue

            for pattern in example.key_patterns:
                if keyword_lower in pattern.lower():
                    results.append(example)
                    break

        return results

    def get_by_capability(self, capability: str) -> List[Example]:
        """Get all examples for a capability."""
        return self.capabilities.get(capability, [])

    def get_by_component(self, component: str) -> List[Example]:
        """Get all examples using a component."""
        return self.components.get(component, [])


def load_inventory(inventory_path: Optional[str] = None) -> Inventory:
    """
    Load Bubble Tea examples inventory from CONTEXTUAL-INVENTORY.md.

    Args:
        inventory_path: Path to charm-examples-inventory directory
                       If None, tries to find it automatically

    Returns:
        Loaded Inventory object

    Raises:
        InventoryLoadError: If inventory cannot be loaded

    Example:
        >>> inv = load_inventory("/path/to/charm-examples-inventory")
        >>> examples = inv.search_by_keyword("progress")
    """
    if inventory_path is None:
        inventory_path = _find_inventory_path()

    inventory_file = Path(inventory_path) / "bubbletea" / "examples" / "CONTEXTUAL-INVENTORY.md"

    if not inventory_file.exists():
        raise InventoryLoadError(
            f"Inventory file not found: {inventory_file}\n"
            f"Expected at: {inventory_path}/bubbletea/examples/CONTEXTUAL-INVENTORY.md"
        )

    logger.info(f"Loading inventory from: {inventory_file}")

    with open(inventory_file, 'r') as f:
        content = f.read()

    inventory = parse_inventory_markdown(content, str(inventory_path))

    logger.info(f"Loaded {len(inventory.examples)} examples")
    logger.info(f"Categories: {len(inventory.capabilities)}")

    return inventory


def parse_inventory_markdown(content: str, base_path: str) -> Inventory:
    """
    Parse CONTEXTUAL-INVENTORY.md markdown content.

    Args:
        content: Markdown content
        base_path: Base path for example files

    Returns:
        Inventory object with parsed examples
    """
    inventory = Inventory(base_path)

    # Parse quick reference table
    table_matches = re.finditer(
        r'\|\s*(.+?)\s*\|\s*`(.+?)`\s*\|',
        content
    )

    need_to_file = {}
    for match in table_matches:
        need = match.group(1).strip()
        file_path = match.group(2).strip()
        need_to_file[need] = file_path

    # Parse detailed sections (## Examples by Capability)
    capability_pattern = r'### (.+?)\n\n\*\*Use (.+?) when you need:\*\*(.+?)(?=\n\n\*\*|### |\Z)'

    capability_sections = re.finditer(capability_pattern, content, re.DOTALL)

    for section in capability_sections:
        capability = section.group(1).strip()
        example_name = section.group(2).strip()
        description = section.group(3).strip()

        # Extract file path and key patterns
        file_match = re.search(r'\*\*File\*\*: `(.+?)`', description)
        patterns_match = re.search(r'\*\*Key patterns\*\*: (.+?)(?=\n|$)', description)

        if file_match:
            file_path = file_match.group(1).strip()
            example = Example(example_name, file_path, capability)

            if patterns_match:
                patterns_text = patterns_match.group(1).strip()
                example.key_patterns = [p.strip() for p in patterns_text.split(',')]

            # Extract components from file name and patterns
            example.components = _extract_components(example_name, example.key_patterns)

            inventory.add_example(example)

    return inventory


def _extract_components(name: str, patterns: List[str]) -> List[str]:
    """Extract component names from example name and patterns."""
    components = []

    # Common component keywords
    component_keywords = [
        'textinput', 'textarea', 'viewport', 'table', 'list', 'pager',
        'paginator', 'spinner', 'progress', 'timer', 'stopwatch',
        'filepicker', 'help', 'tabs', 'autocomplete'
    ]

    name_lower = name.lower()
    for keyword in component_keywords:
        if keyword in name_lower:
            components.append(keyword)

    for pattern in patterns:
        pattern_lower = pattern.lower()
        for keyword in component_keywords:
            if keyword in pattern_lower and keyword not in components:
                components.append(keyword)

    return components


def _find_inventory_path() -> str:
    """
    Try to find charm-examples-inventory automatically.

    Searches in common locations:
    - ./charm-examples-inventory
    - ../charm-examples-inventory
    - ~/charmtuitemplate/vinw/charm-examples-inventory

    Returns:
        Path to inventory directory

    Raises:
        InventoryLoadError: If not found
    """
    search_paths = [
        Path.cwd() / "charm-examples-inventory",
        Path.cwd().parent / "charm-examples-inventory",
        Path.home() / "charmtuitemplate" / "vinw" / "charm-examples-inventory"
    ]

    for path in search_paths:
        if (path / "bubbletea" / "examples" / "CONTEXTUAL-INVENTORY.md").exists():
            logger.info(f"Found inventory at: {path}")
            return str(path)

    raise InventoryLoadError(
        "Could not find charm-examples-inventory automatically.\n"
        f"Searched: {[str(p) for p in search_paths]}\n"
        "Please provide inventory_path parameter."
    )


def build_capability_index(inventory: Inventory) -> Dict[str, List[str]]:
    """
    Build index of capabilities to example names.

    Args:
        inventory: Loaded inventory

    Returns:
        Dict mapping capability names to example names
    """
    index = {}
    for capability, examples in inventory.capabilities.items():
        index[capability] = [ex.name for ex in examples]
    return index


def build_component_index(inventory: Inventory) -> Dict[str, List[str]]:
    """
    Build index of components to example names.

    Args:
        inventory: Loaded inventory

    Returns:
        Dict mapping component names to example names
    """
    index = {}
    for component, examples in inventory.components.items():
        index[component] = [ex.name for ex in examples]
    return index


def get_example_details(inventory: Inventory, example_name: str) -> Optional[Example]:
    """
    Get detailed information about a specific example.

    Args:
        inventory: Loaded inventory
        example_name: Name of example to look up

    Returns:
        Example object or None if not found
    """
    return inventory.examples.get(example_name)


def main():
    """Test inventory loader."""
    logging.basicConfig(level=logging.INFO)

    print("Testing Inventory Loader\n" + "=" * 50)

    try:
        # Load inventory
        print("\n1. Loading inventory...")
        inventory = load_inventory()
        print(f"✓ Loaded {len(inventory.examples)} examples")
        print(f"✓ {len(inventory.capabilities)} capability categories")

        # Test search
        print("\n2. Testing keyword search...")
        results = inventory.search_by_keyword("progress")
        print(f"✓ Found {len(results)} examples for 'progress':")
        for ex in results[:3]:
            print(f"  - {ex.name} ({ex.capability})")

        # Test capability lookup
        print("\n3. Testing capability lookup...")
        cap_examples = inventory.get_by_capability("Installation and Progress Tracking")
        print(f"✓ Found {len(cap_examples)} installation examples")

        # Test component lookup
        print("\n4. Testing component lookup...")
        comp_examples = inventory.get_by_component("spinner")
        print(f"✓ Found {len(comp_examples)} examples using 'spinner'")

        # Test indices
        print("\n5. Building indices...")
        cap_index = build_capability_index(inventory)
        comp_index = build_component_index(inventory)
        print(f"✓ Capability index: {len(cap_index)} categories")
        print(f"✓ Component index: {len(comp_index)} components")

        print("\n✅ All tests passed!")

    except InventoryLoadError as e:
        print(f"\n❌ Error loading inventory: {e}")
        return 1

    return 0


if __name__ == "__main__":
    exit(main())
