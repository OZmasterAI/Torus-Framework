#!/usr/bin/env python3
"""Architecture designer for Bubble Tea TUIs."""

import sys
from pathlib import Path
from typing import Dict, List

sys.path.insert(0, str(Path(__file__).parent))

from utils.template_generator import (
    generate_model_struct,
    generate_init_function,
    generate_update_skeleton,
    generate_view_skeleton
)
from utils.ascii_diagram import (
    draw_component_tree,
    draw_message_flow,
    draw_state_machine
)
from utils.validators import DesignValidator


def design_architecture(components: Dict, patterns: Dict, requirements: Dict) -> Dict:
    """Design TUI architecture."""
    primary = components.get('primary_components', [])
    comp_names = [c['component'].replace('.Model', '') for c in primary]
    archetype = requirements.get('archetype', 'general')
    views = requirements.get('views', 'single')

    # Generate code structures
    model_struct = generate_model_struct(comp_names, archetype)
    init_logic = generate_init_function(comp_names)
    message_handlers = {
        'tea.KeyMsg': 'Handle keyboard input (arrows, enter, q, etc.)',
        'tea.WindowSizeMsg': 'Handle window resize, update component dimensions'
    }

    # Add component-specific handlers
    if 'progress' in comp_names or 'spinner' in comp_names:
        message_handlers['progress.FrameMsg'] = 'Update progress/spinner animation'

    view_logic = generate_view_skeleton(comp_names)

    # Generate diagrams
    diagrams = {
        'component_hierarchy': draw_component_tree(comp_names, archetype),
        'message_flow': draw_message_flow(list(message_handlers.keys()))
    }

    if views == 'multi':
        diagrams['state_machine'] = draw_state_machine(['View 1', 'View 2', 'View 3'])

    architecture = {
        'model_struct': model_struct,
        'init_logic': init_logic,
        'message_handlers': message_handlers,
        'view_logic': view_logic,
        'diagrams': diagrams
    }

    # Validate
    validator = DesignValidator()
    validation = validator.validate_architecture(architecture)
    architecture['validation'] = validation.to_dict()

    return architecture
