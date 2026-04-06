# Example TUI Designs

Real-world design examples with component selections.

## Example 1: Log Viewer

**Requirements**: View large log files, search, navigate
**Archetype**: Viewer
**Components**:
- viewport.Model - Main log display
- textinput.Model - Search input
- help.Model - Keyboard shortcuts

**Architecture**:
```go
type model struct {
    viewport viewport.Model
    searchInput textinput.Model
    searchMode bool
    matches []int
    currentMatch int
}
```

**Key Features**:
- Toggle search with `/`
- Navigate matches with n/N
- Highlight matches in viewport

## Example 2: File Manager

**Requirements**: Three-column navigation, preview
**Archetype**: File Manager
**Components**:
- list.Model (x2) - Parent + current directory
- viewport.Model - File preview
- filepicker.Model - Alternative approach

**Layout**: Horizontal three-pane
**Complexity**: Medium-High

## Example 3: Package Installer

**Requirements**: Sequential installation with progress
**Archetype**: Installer
**Components**:
- list.Model - Package list
- progress.Model - Per-package progress
- spinner.Model - Download indicator

**Pattern**: Progress Tracker
**Workflow**: Queue-based sequential processing

## Example 4: Configuration Wizard

**Requirements**: Multi-step form with validation
**Archetype**: Form
**Components**:
- textinput.Model array - Multiple inputs
- help.Model - Per-step help
- progress/indicator - Step progress

**Pattern**: Form Flow
**Navigation**: Tab between fields, Enter to next step

## Example 5: Dashboard

**Requirements**: Multiple views, real-time updates
**Archetype**: Dashboard
**Components**:
- tabs - View switching
- table.Model - Data display
- viewport.Model - Log panel

**Pattern**: Composable Views
**Layout**: Tabbed with multiple panels per tab

## Component Selection Guide

| Use Case | Primary Component | Alternative | Supporting |
|----------|------------------|-------------|-----------|
| Log viewing | viewport | pager | textinput (search) |
| File selection | filepicker | list | viewport (preview) |
| Data table | table | list | paginator |
| Text editing | textarea | textinput | viewport |
| Progress | progress | spinner | - |
| Multi-step | views | tabs | help |
| Search/Filter | textinput | autocomplete | list |

## Complexity Matrix

| TUI Type | Components | Views | Estimated Time |
|----------|-----------|-------|----------------|
| Simple viewer | 1-2 | 1 | 1-2 hours |
| File manager | 3-4 | 1 | 3-4 hours |
| Installer | 3-4 | 3 | 2-3 hours |
| Dashboard | 4-6 | 3+ | 4-6 hours |
| Editor | 2-3 | 1-2 | 3-4 hours |
