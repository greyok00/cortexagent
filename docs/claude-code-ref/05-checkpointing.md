# Claude Code Checkpointing

> Source: https://code.claude.com/docs/en/checkpointing.md
> Pulled 2026-08-11

Claude Code automatically tracks Claude's file edits as you work, allowing
you to quickly undo changes and rewind to previous states if anything gets
off track.

## How checkpoints work

As you work with Claude, checkpointing automatically captures the state of
your code before each user prompt.

### Automatic tracking

- Every user prompt creates a new checkpoint
- Claude Code keeps file snapshots for the 100 most recent checkpoints in a
  session. Discarding an older checkpoint deletes the snapshot files that no
  remaining checkpoint references (each file's first snapshot is kept as the
  baseline for the VS Code extension's session diffs).
- Checkpoints save with the conversation, so you can still run `/rewind`
  after resuming a session
- Checkpoints delete along with sessions after 30 days (change the period
  with `cleanupPeriodDays` setting)

## Rewind and summarize

Run `/rewind`, or press `Esc` twice when the prompt input is empty, to open
the rewind menu.

If the prompt input contains text, double `Esc` clears it instead of opening
the menu. The cleared text is saved to input history, so press `Up` to recall
it after you finish in the rewind menu.

### Rewind menu actions

- **Restore code and conversation**: revert both code and conversation
- **Restore conversation**: rewind to that message while keeping current code
- **Restore code**: revert file changes while keeping the conversation
- **Summarize from here**: compress the conversation from this point forward
- **Summarize up to here**: compress the conversation before this point
- **Never mind**: return to the message list without making changes

The two code restore options appear only when the selected checkpoint has
tracked file changes to revert.

## Rewind past a cleared conversation

If you ran `/clear` earlier in the same Claude Code process, the rewind menu
shows an additional entry at the top: `/resume <session-id> (previous session)`.
Requires Claude Code v2.1.191+.

## Limitations

### Bash command changes not tracked

Checkpointing does not track files modified by bash commands (`rm`, `mv`,
`cp`). These cannot be undone through rewind.

### Subagent edits not restored

Subagent edits usually don't capture in your session's checkpoints:
- **Foreground forked skill**: rewinding restores its edits
- **Any other subagent**: rewinding doesn't restore — use git

### External changes not tracked

Only files edited within the current session are captured.

### Symlinked and hard-linked paths not restored

Skipped with `Restored the code, but skipped N files` warning.

## CortexAgent's relationship

CortexAgent doesn't manage checkpointing — that's a claude-code product feature.
Our subagents don't rewind (print mode is one-shot). If a subagent's edits
go wrong, use git to revert.
