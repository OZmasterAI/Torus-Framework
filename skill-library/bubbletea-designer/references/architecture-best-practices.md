# Bubble Tea Architecture Best Practices

## Model Design

### Keep State Flat
❌ Avoid: Deeply nested state
✅ Prefer: Flat structure with clear fields

```go
// Good
type model struct {
    items []Item
    cursor int
    selected map[int]bool
}

// Avoid
type model struct {
    state struct {
        data struct {
            items []Item
        }
    }
}
```

### Separate Concerns
- UI state in model
- Business logic in separate functions
- Network/IO in commands

### Component Ownership
Each component owns its state. Don't reach into component internals.

## Update Function

### Message Routing
Route messages to appropriate handlers:

```go
func (m model) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
    switch msg := msg.(type) {
    case tea.KeyMsg:
        return m.handleKeyboard(msg)
    case tea.WindowSizeMsg:
        return m.handleResize(msg)
    }
    return m.updateComponents(msg)
}
```

### Command Batching
Batch multiple commands:

```go
var cmds []tea.Cmd
cmds = append(cmds, cmd1, cmd2, cmd3)
return m, tea.Batch(cmds...)
```

## View Function

### Cache Expensive Renders
Don't recompute on every View() call:

```go
type model struct {
    cachedView string
    dirty bool
}

func (m model) View() string {
    if m.dirty {
        m.cachedView = m.render()
        m.dirty = false
    }
    return m.cachedView
}
```

### Responsive Layouts
Adapt to terminal size:

```go
if m.width < 80 {
    // Compact layout
} else {
    // Full layout
}
```

## Performance

### Minimize Allocations
Reuse slices and strings where possible

### Defer Heavy Operations
Move slow operations to commands (async)

### Debounce Rapid Updates
Don't update on every keystroke for expensive operations

## Error Handling

### User-Friendly Errors
Show actionable error messages

### Graceful Degradation
Fallback when features unavailable

### Error Recovery
Allow user to retry or cancel

## Testing

### Test Pure Functions
Extract business logic for easy testing

### Mock Commands
Test Update() without side effects

### Snapshot Views
Compare View() output for visual regression

## Accessibility

### Keyboard-First
All features accessible via keyboard

### Clear Indicators
Show current focus, selection state

### Help Text
Provide discoverable help (? key)

## Code Organization

### File Structure
```
main.go         - Entry point, model definition
update.go       - Update handlers
view.go         - View rendering
commands.go     - Command definitions
messages.go     - Custom message types
```

### Component Encapsulation
One component per file for complex TUIs

## Debugging

### Log to File
```go
f, _ := os.OpenFile("debug.log", os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0666)
log.SetOutput(f)
log.Printf("Debug: %+v", msg)
```

### Debug Mode
Toggle debug view with key binding

## Common Pitfalls

1. **Forgetting tea.Batch**: Returns only last command
2. **Not handling WindowSizeMsg**: Fixed-size components
3. **Blocking in Update()**: Freezes UI - use commands
4. **Direct terminal writes**: Use tea.Println for above-TUI output
5. **Ignoring ready state**: Rendering before initialization complete
