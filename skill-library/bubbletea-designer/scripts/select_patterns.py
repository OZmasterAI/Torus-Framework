#!/usr/bin/env python3
"""Pattern selector - finds relevant example files."""

import sys
from pathlib import Path
from typing import Dict, List, Optional

sys.path.insert(0, str(Path(__file__).parent))

from utils.inventory_loader import load_inventory, Inventory


def select_relevant_patterns(components: Dict, inventory_path: Optional[str] = None) -> Dict:
    """Select relevant example files."""
    try:
        inventory = load_inventory(inventory_path)
    except Exception as e:
        return {'examples': [], 'error': str(e)}

    primary_components = components.get('primary_components', [])
    examples = []

    for comp_info in primary_components[:3]:
        comp_name = comp_info['component'].replace('.Model', '')
        comp_examples = inventory.get_by_component(comp_name)

        for ex in comp_examples[:2]:
            examples.append({
                'file': ex.file_path,
                'capability': ex.capability,
                'relevance_score': comp_info['score'],
                'key_patterns': ex.key_patterns,
                'study_order': len(examples) + 1
            })

    return {
        'examples': examples,
        'recommended_study_order': list(range(1, len(examples) + 1)),
        'total_study_time': f"{len(examples) * 15} minutes"
    }
