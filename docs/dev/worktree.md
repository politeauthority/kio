# Worktree Coordination

This file is **not git-tracked** (docs/ is gitignored) and lives on the shared filesystem.
All worktrees see it immediately — no commits needed.

## How to use

At the start of every session in a worktree:
1. Read this file.
2. Check the no-touch zones before editing any files.
3. Add your entry to the Active Worktrees table below.
4. Remove your entry when your branch is merged or your worktree is deleted.

## Active Worktrees

| Worktree | Branch | Claimed areas | Status |
|----------|--------|---------------|--------|
| _(none)_ | | | |

## No-Touch Zones

List files or directories another agent is actively editing so others don't create conflicts.

_(empty)_

---

## Worktree quick-reference

List all worktrees:
```bash
git worktree list
```

Create a new worktree and switch to it:
```bash
git worktree add .claude/worktrees/<name> -b <branch>
```

Remove a worktree after merging:
```bash
git worktree remove .claude/worktrees/<name>
```
