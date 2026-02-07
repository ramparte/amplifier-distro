---
bundle:
  name: amplifier-distro-base
  version: 0.1.0
  description: Amplifier Distribution base bundle - standard agents, tools, and behaviors

includes:
  - foundation:behaviors/agents
  - foundation:behaviors/streaming-ui
  - foundation:behaviors/redaction

providers:
  - module: provider-anthropic
    config:
      default_model: claude-sonnet-4-20250514
  - module: provider-openai
    config:
      default_model: gpt-4o
---

# Amplifier Distro Base Bundle

The standard bundle for the Amplifier Distribution. Provides a curated
set of agents, tools, and behaviors that work well together.

## What's Included

- **Agents**: 16+ foundation agents (explorer, zen-architect, bug-hunter, etc.)
- **Streaming UI**: Real-time output rendering
- **Redaction**: Automatic secret redaction in sessions
- **Providers**: Anthropic (Claude) and OpenAI (GPT-4o)

## Customization

This bundle is meant to be inherited by personal bundles:

```yaml
includes:
  - amplifier-distro-base
  # Add your customizations below
```
