# CODE WRITING POLICY — MANDATORY

Before writing or changing more than 200 lines, or any file likely to exceed 20,000 characters:

1. PLAN FIRST
   - Read the relevant existing files.
   - Produce a short implementation plan.
   - List every file that will be created or modified.
   - For each file, list the exact functions/classes/sections to add or change.
   - Do not write implementation code yet.

2. CHUNKED WRITES
   - NEVER emit an entire large file in one write tool call.
   - Split work into sequential chunks.
   - Each write must stay under 12,000 characters of code.
   - Prefer targeted edits: create file skeleton, then append or patch one section at a time.
   - Use a unique anchor for every insertion point, such as:
     # === CORTEX: SECTION: dashboard_agents ===
   - Never rely on "..." or "rest of file unchanged" inside a write.

3. CONTINUATION PROTOCOL
   - End every incomplete file with:
     # CORTEX_CONTINUATION_REQUIRED
   - Immediately continue in the next tool call.
   - Never stop and ask whether to continue unless a decision is genuinely required.
   - Track progress as:
     CHUNK 3/7 COMPLETE — next: render_subagents()

4. VERIFY AFTER EVERY CHUNK
   - After each write, run the appropriate check:
     - Python: python -m py_compile <file>
     - JavaScript/TypeScript: syntax check or build check
     - Shell: bash -n <file>
   - If verification fails, fix only the failing chunk before continuing.

5. FINAL VERIFICATION
   - After the last chunk, run the project's tests or primary entry point.
   - Print only:
     FILES CHANGED
     CHUNKS WRITTEN
     VERIFICATION RESULT
     NEXT STEP

NEVER attempt to output a complete large implementation in a single response or tool call. set this to default for cortexagent so it never truncates and works in chunks
