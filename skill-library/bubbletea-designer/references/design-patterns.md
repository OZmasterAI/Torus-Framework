# Bubble Tea Design Patterns

Common architectural patterns for TUI development.

## Pattern 1: Single-View Application

**When**: Simple, focused TUIs with one main view
**Components**: 1-3 components, single model struct
**Complexity**: Low

```go
type model struct {
    mainComponent component.Model
    ready bool
}
```

## Pattern 2: Multi-View State Machine

**When**: Multiple distinct screens (setup, main, done)
**Components**: State enum + view-specific components
**Complexity**: Medium

```go
type view int
const (
    setupView view = iota
    mainView
    doneView
)

type model struct {
    currentView view
    // Components for each view
}
```

## Pattern 3: Composable Views

**When**: Complex UIs with reusable sub-components
**Pattern**: Embed multiple bubble models
**Example**: Dashboard with multiple panels

```go
type model struct {
    panel1 Panel1Model
    panel2 Panel2Model
    panel3 Panel3Model
}

// Each panel is itself a Bubble Tea model
```

## Pattern 4: Master-Detail

**When**: Selection in one pane affects display in another
**Example**: File list + preview, Email list + content
**Layout**: Two-pane or three-pane

```go
type model struct {
    list list.Model
    detail viewport.Model
    selectedItem int
}
```

## Pattern 5: Form Flow

**When**: Multi-step data collection
**Pattern**: Array of inputs + focus management
**Example**: Configuration wizard

```go
type model struct {
    inputs []textinput.Model
    focusIndex int
    step int
}
```

## Pattern 6: Progress Tracker

**When**: Long-running sequential operations
**Pattern**: Queue + progress per item
**Example**: Installation, download manager

```go
type model struct {
    items []Item
    currentIndex int
    progress progress.Model
    spinner spinner.Model
}
```

## Layout Patterns

### Vertical Stack
```go
lipgloss.JoinVertical(lipgloss.Left,
    header,
    content,
    footer,
)
```

### Horizontal Panels
```go
lipgloss.JoinHorizontal(lipgloss.Top,
    leftPanel,
    separator,
    rightPanel,
)
```

### Three-Column (File Manager Style)
```go
lipgloss.JoinHorizontal(lipgloss.Top,
    parentDir,   // 25% width
    currentDir,  // 35% width
    preview,     // 40% width
)
```

## Message Passing Patterns

### Custom Messages
```go
type myCustomMsg struct {
    data string
}

func doSomethingCmd() tea.Msg {
    return myCustomMsg{data: "result"}
}

func (m model) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
    switch msg := msg.(type) {
    case myCustomMsg:
        // Handle custom message
    }
}
```

### Async Operations
```go
func fetchDataCmd() tea.Cmd {
    return func() tea.Msg {
        // Do async work
        data := fetchFromAPI()
        return dataFetchedMsg{data}
    }
}
```

## Error Handling Pattern

```go
type errMsg struct{ err error }

func (m model) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
    switch msg := msg.(type) {
    case errMsg:
        m.err = msg.err
        m.errVisible = true
        return m, nil
    }
}
```

## Keyboard Navigation Pattern

```go
case tea.KeyMsg:
    switch msg.String() {
    case "up", "k":
        m.cursor--
    case "down", "j":
        m.cursor++
    case "enter":
        m.selectCurrent()
    case "q", "ctrl+c":
        return m, tea.Quit
    }
```

## Responsive Layout Pattern

```go
case tea.WindowSizeMsg:
    m.width = msg.Width
    m.height = msg.Height

    // Update component dimensions
    m.viewport.Width = msg.Width
    m.viewport.Height = msg.Height - 5  // Reserve space for header/footer
```

## Help Overlay Pattern

```go
type model struct {
    showHelp bool
    help help.Model
}

func (m model) View() string {
    if m.showHelp {
        return m.help.View()
    }
    return m.mainView()
}
```
