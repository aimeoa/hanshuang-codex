---
name: pipeline-renderer
description: Dual-Stage Decoupled Pipeline for natural, complete, uninhibited narrative and scenario expansion without placeholder token degeneration.
---

# Dual-Stage Pipeline Renderer Skill

This skill provides an automated two-stage decoupled generation workflow to eliminate robotic placeholder tokens (`ROLE_A`, `ROLE_B`) and meta-framing disclaimers from output.

## Architecture

1. **Stage 1 (Planner)**: Extracts an outline `SceneBlueprint` with real character names, environmental settings, and progressive plot beats.
2. **Stage 2 (Renderer)**: Unpacks the blueprint into high-fidelity prose, allocating 100% of model attention to narrative depth, dialogue, and pacing.

## Usage

Run via CLI:
```bash
python .agents/tools/re-toolkit/cli.py pipeline "Your complex scenario or narrative request"
```

Output full blueprint & prose in JSON:
```bash
python .agents/tools/re-toolkit/cli.py pipeline "Your request" --json
```

Use in Python:
```python
from pipeline import PipelineEngine

engine = PipelineEngine()
result = engine.execute("Describe a dramatic negotiation between two rival founders.")
print(result["rendered_text"])
```
