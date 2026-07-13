# Decisions

## 2026-07-06 - Inventory-linked project documentation

### Context

Workspace cleanup requires each core project to have a lightweight local status trail.

### Decision

Create documentation-only `STATUS.md`, `TASKS.md`, and `DECISIONS.md` when missing. Do not modify source code, credentials, runtime configuration, or Git history.

### Impact

- Project review can start from local files and the Wiki page.
- Existing README remains unchanged.
- Unknown fields remain explicit instead of being guessed.

### Rollback

Remove only the generated documentation files listed in the corresponding Workspace-Control manifest after manual review.

### Sources

- `D:\AI-Workspace\Workspace-Control\cleanup-plan\inventory.json`
