# Bubble Tea TUI Designer

Automate the design process for Bubble Tea terminal user interfaces with intelligent component mapping, architecture generation, and implementation planning.

## What It Does

This skill helps you design Bubble Tea TUIs by:

1. **Analyzing requirements** from natural language descriptions
2. **Mapping to components** from the Charmbracelet ecosystem
3. **Generating architecture** with component hierarchy and message flow
4. **Creating workflows** with step-by-step implementation plans
5. **Providing scaffolding** with boilerplate code to get started

## Features

- ✅ Intelligent component selection based on requirements
- ✅ Pattern matching against 46 Bubble Tea examples
- ✅ ASCII architecture diagrams
- ✅ Complete implementation workflows
- ✅ Code scaffolding generation
- ✅ Design validation and suggestions

## Installation

```bash
/plugin marketplace add ./bubbletea-designer
```

## Quick Start

Simply describe your TUI and the skill will generate a complete design:

```
"Design a log viewer with search and highlighting"
```

The skill will automatically:
- Classify it as a "viewer" archetype
- Select viewport.Model and textinput.Model
- Generate architecture diagram
- Create step-by-step implementation workflow
- Provide code scaffolding

## Usage Examples

### Example 1: Simple Log Viewer
```
"Build a TUI for viewing log files with search"
```

### Example 2: File Manager
```
"Create a file manager with three-column view showing parent directory, current directory, and file preview"
```

### Example 3: Package Installer
```
"Design an installer UI with progress bars for sequential package installation"
```

### Example 4: Configuration Wizard
```
"Build a multi-step configuration wizard with form validation"
```

## How It Works

The designer follows a systematic process:

1. **Requirement Analysis**: Extract structured requirements from your description
2. **Component Mapping**: Match requirements to Bubble Tea components
3. **Pattern Selection**: Find relevant examples from inventory
4. **Architecture Design**: Create component hierarchy and message flow
5. **Workflow Generation**: Generate ordered implementation steps
6. **Design Report**: Combine all analyses into comprehensive document

## Output Structure

The comprehensive design report includes:

- **Executive Summary**: TUI type, components, time estimate
- **Requirements**: Parsed features, interactions, data types
- **Components**: Selected components with justifications
- **Patterns**: Relevant example files to study
- **Architecture**: Model struct, diagrams, message handlers
- **Workflow**: Phase-by-phase implementation plan
- **Code Scaffolding**: Basic main.go template
- **Next Steps**: What to do first

## Dependencies

The skill references the charm-examples-inventory for pattern matching.

Default search locations:
- `./charm-examples-inventory`
- `../charm-examples-inventory`
- `~/charmtuitemplate/vinw/charm-examples-inventory`

You can also specify a custom path:
```python
report = comprehensive_tui_design_report(
    "your description",
    inventory_path="/custom/path/to/inventory"
)
```

## Testing

Run the comprehensive test suite:

```bash
cd bubbletea-designer/tests
python3 test_integration.py
```

Individual script tests:
```bash
python3 scripts/analyze_requirements.py
python3 scripts/map_components.py
python3 scripts/design_tui.py "Build a log viewer"
```

## Files Structure

```
bubbletea-designer/
├── SKILL.md                    # Skill documentation
├── scripts/
│   ├── design_tui.py          # Main orchestrator
│   ├── analyze_requirements.py
│   ├── map_components.py
│   ├── select_patterns.py
│   ├── design_architecture.py
│   ├── generate_workflow.py
│   └── utils/
│       ├── inventory_loader.py
│       ├── component_matcher.py
│       ├── template_generator.py
│       ├── ascii_diagram.py
│       └── validators/
├── references/
│   ├── bubbletea-components-guide.md
│   ├── design-patterns.md
│   ├── architecture-best-practices.md
│   └── example-designs.md
├── assets/
│   ├── component-taxonomy.json
│   ├── pattern-templates.json
│   └── keywords.json
└── tests/
    └── test_integration.py
```

## Resources

- [Bubble Tea Documentation](https://github.com/charmbracelet/bubbletea)
- [Lipgloss Styling](https://github.com/charmbracelet/lipgloss)
- [Bubbles Components](https://github.com/charmbracelet/bubbles)
- [Charm Community](https://charm.sh/chat)

## License

MIT

## Contributing

Contributions welcome! This is an automated agent created by the agent-creator skill.

## Version

1.0.0 - Initial release

**Generated with Claude Code agent-creator skill**
