#!/usr/bin/env python3
"""
Template generator for Bubble Tea TUIs.
Generates code scaffolding and boilerplate.
"""

from typing import List, Dict


def generate_model_struct(components: List[str], archetype: str) -> str:
    """Generate model struct with components."""
    component_fields = {
        'viewport': '    viewport viewport.Model',
        'textinput': '    textInput textinput.Model',
        'textarea': '    textArea textarea.Model',
        'table': '    table table.Model',
        'list': '    list list.Model',
        'progress': '    progress progress.Model',
        'spinner': '    spinner spinner.Model'
    }

    fields = []
    for comp in components:
        if comp in component_fields:
            fields.append(component_fields[comp])

    # Add common fields
    fields.extend([
        '    width int',
        '    height int',
        '    ready bool'
    ])

    return f"""type model struct {{
{chr(10).join(fields)}
}}"""


def generate_init_function(components: List[str]) -> str:
    """Generate Init() function."""
    inits = []
    for comp in components:
        if comp == 'viewport':
            inits.append('    m.viewport = viewport.New(80, 20)')
        elif comp == 'textinput':
            inits.append('    m.textInput = textinput.New()')
            inits.append('    m.textInput.Focus()')
        elif comp == 'spinner':
            inits.append('    m.spinner = spinner.New()')
            inits.append('    m.spinner.Spinner = spinner.Dot')
        elif comp == 'progress':
            inits.append('    m.progress = progress.New(progress.WithDefaultGradient())')

    init_cmds = ', '.join([f'{c}.Init()' for c in components if c != 'viewport'])

    return f"""func (m model) Init() tea.Cmd {{
{chr(10).join(inits) if inits else '    // Initialize components'}
    return tea.Batch({init_cmds if init_cmds else 'nil'})
}}"""


def generate_update_skeleton(interactions: Dict) -> str:
    """Generate Update() skeleton."""
    return """func (m model) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
    switch msg := msg.(type) {
    case tea.KeyMsg:
        switch msg.String() {
        case "ctrl+c", "q":
            return m, tea.Quit
        }

    case tea.WindowSizeMsg:
        m.width = msg.Width
        m.height = msg.Height
        m.ready = true
    }

    // Update components
    // TODO: Add component update logic

    return m, nil
}"""


def generate_view_skeleton(components: List[str]) -> str:
    """Generate View() skeleton."""
    renders = []
    for comp in components:
        renders.append(f'    // Render {comp}')
        renders.append(f'    // views = append(views, m.{comp}.View())')

    return f"""func (m model) View() string {{
    if !m.ready {{
        return "Loading..."
    }}

    var views []string

{chr(10).join(renders)}

    return lipgloss.JoinVertical(lipgloss.Left, views...)
}}"""


def generate_main_go(components: List[str], archetype: str) -> str:
    """Generate complete main.go scaffold."""
    imports = ['github.com/charmbracelet/bubbletea']

    if 'viewport' in components:
        imports.append('github.com/charmbracelet/bubbles/viewport')
    if 'textinput' in components:
        imports.append('github.com/charmbracelet/bubbles/textinput')
    if any(c in components for c in ['table', 'list', 'spinner', 'progress']):
        imports.append('github.com/charmbracelet/bubbles/' + components[0])

    imports.append('github.com/charmbracelet/lipgloss')

    import_block = '\n    '.join(f'"{imp}"' for imp in imports)

    return f"""package main

import (
    {import_block}
)

{generate_model_struct(components, archetype)}

{generate_init_function(components)}

{generate_update_skeleton({})}

{generate_view_skeleton(components)}

func main() {{
    p := tea.NewProgram(model{{}}, tea.WithAltScreen())
    if _, err := p.Run(); err != nil {{
        panic(err)
    }}
}}
"""
