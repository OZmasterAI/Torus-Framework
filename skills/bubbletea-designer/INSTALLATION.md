# Installation Guide

Step-by-step installation for Bubble Tea Designer skill.

## Prerequisites

- Claude Code CLI installed
- Python 3.8+
- charm-examples-inventory (optional but recommended)

## Installation

### Step 1: Install the Skill

```bash
/plugin marketplace add /path/to/bubbletea-designer
```

Or if you're in the directory containing bubbletea-designer:

```bash
/plugin marketplace add ./bubbletea-designer
```

### Step 2: Verify Installation

The skill should now be active. Test it with:

```
"Design a simple TUI for viewing log files"
```

You should see Claude activate the skill and generate a design report.

## Optional: Install charm-examples-inventory

For full pattern matching capabilities:

```bash
cd ~/charmtuitemplate/vinw  # Or your preferred location
git clone https://github.com/charmbracelet/bubbletea charm-examples-inventory
```

The skill will automatically search common locations:
- `./charm-examples-inventory`
- `../charm-examples-inventory`
- `~/charmtuitemplate/vinw/charm-examples-inventory`

## Verification

Run test scripts to verify everything works:

```bash
cd /path/to/bubbletea-designer
python3 scripts/analyze_requirements.py
python3 scripts/map_components.py
```

You should see test outputs with ✅ marks indicating success.

## Troubleshooting

### Skill Not Activating

**Issue**: Skill doesn't activate when you mention Bubble Tea
**Solution**:
- Check skill is installed: `/plugin list`
- Try explicit keywords: "design a bubbletea TUI"
- Restart Claude Code

### Inventory Not Found

**Issue**: "Cannot locate charm-examples-inventory"
**Solution**:
- Install inventory to a standard location (see Step 2 above)
- Or specify custom path when needed
- Skill works without inventory but with reduced pattern matching

### Import Errors

**Issue**: Python import errors when running scripts
**Solution**:
- Verify Python 3.8+ installed: `python3 --version`
- Scripts use relative imports, run from project directory

## Usage

Once installed, activate by mentioning:
- "Design a TUI for..."
- "Create a Bubble Tea interface..."
- "Which components should I use for..."
- "Plan architecture for a terminal UI..."

The skill activates automatically and generates comprehensive design reports.

## Uninstallation

To remove the skill:

```bash
/plugin marketplace remove bubbletea-designer
```

## Next Steps

- Read SKILL.md for complete documentation
- Try example queries from README.md
- Explore references/ for design patterns
- Study generated designs for your use cases
