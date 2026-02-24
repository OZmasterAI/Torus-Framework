---
globs: .claude/domains/**, .claude/hooks/shared/domain_registry.py
---

# Domain Mastery Rules

## Directory Layout
```
~/.claude/domains/
  .active                     # Plain text: active domain name
  <domain-name>/
    behavior.md               # Behavioral overlay (injected when active)
    knowledge.md              # Synthesized expertise (injected at boot)
    profile.json              # Gate tuning, memory tags, graduation state
```

## Domains vs Modes (Orthogonal)
- **Modes** = task-type overlays (HOW you work): coding, debug, review, docs
- **Domains** = knowledge-area overlays (WHAT you know): framework, solana, web-dev
- Both can be active simultaneously

## Key Principles
- Raw memories (L1) in ChromaDB are never modified by graduation
- knowledge.md is a derivative artifact — a "textbook" written from "research notes"
- Token budget (~800 tokens default) prevents context bloat
- Tier 1 gates (01/02/03) are immune to domain downgrades

## profile.json Schema
Required fields: description, security_profile, gate_modes, disabled_gates, memory_tags, l2_keywords, auto_detect, graduation, token_budget

## Graduation Lifecycle
Learning → memories accumulate → threshold (20+) → `/domain graduate` → application
