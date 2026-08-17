#!/bin/bash
# snapshot.sh — Full system snapshot with integrity verification
# Usage:
#   snapshot.sh save          # Create a full snapshot
#   snapshot.sh verify        # Verify current state matches snapshot
#   snapshot.sh restore       # Restore from snapshot
#   snapshot.sh diff          # Show differences from snapshot

set -euo pipefail

# Derived from this script's location — works for any clone, no hardcoded path.
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
WORKDIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"
SNAPSHOT_DIR="$WORKDIR/.snapshots"
TIMESTAMP=$(date +%s)
SNAPSHOT_NAME="snap-${TIMESTAMP}"

mkdir -p "$SNAPSHOT_DIR"

CRITICAL_FILES=(
    "bin/cortexagent"
    "cortex/packages/tui/src/keys.ts"
    "cortex/packages/tui/dist/keys.js"
    "cortex/packages/coding-agent/dist/cli.js"
    "cortex/packages/coding-agent/dist/main.js"
    "lib/overseer.py"
    "lib/daemon.py"
    "lib/observability.py"
    "config/settings.toml"
)

hash_file() {
    sha256sum "$1" 2>/dev/null | awk '{print $1}' || echo "MISSING"
}

save_snapshot() {
    echo "╔══════════════════════════════════════════════════════════════╗"
    echo "║                    SNAPSHOT SAVE                           ║"
    echo "╚══════════════════════════════════════════════════════════════╝"
    echo ""
    
    local snap_dir="$SNAPSHOT_DIR/$SNAPSHOT_NAME"
    mkdir -p "$snap_dir"
    
    echo "  Snapshot directory: $snap_dir"
    echo ""
    
    # Hash current state
    echo "  Recording file hashes..."
    echo -n "" > "$snap_dir/hashes.txt"
    for f in "${CRITICAL_FILES[@]}"; do
        local full_path="$WORKDIR/$f"
        if [ -f "$full_path" ]; then
            local hash=$(hash_file "$full_path")
            local size=$(stat -c%s "$full_path" 2>/dev/null || echo "?")
            local date=$(stat -c%y "$full_path" 2>/dev/null | cut -d' ' -f1,2)
            echo "$f|$hash|$size|$date" >> "$snap_dir/hashes.txt"
            echo "  ✓ $f ($size bytes, $date)"
        else
            echo "  ✗ $f — NOT FOUND"
        fi
    done
    
    echo ""
    echo "  Snapshot saved: $SNAPSHOT_NAME"
    echo "  Hash file: $snap_dir/hashes.txt"
}

verify_snapshot() {
    echo "╔══════════════════════════════════════════════════════════════╗"
    echo "║                    VERIFICATION                            ║"
    echo "╚══════════════════════════════════════════════════════════════╝"
    echo ""
    
    local latest=$(ls -d "$SNAPSHOT_DIR"/snap-*/ | sort -r | head -1)
    
    if [ -z "$latest" ]; then
        echo "  No snapshots found!"
        return 1
    fi
    
    echo "  Checking against: $latest"
    echo ""
    
    local issues=0
    while IFS='|' read -r filepath hash size date; do
        local full_path="$WORKDIR/$filepath"
        
        if [ ! -f "$full_path" ]; then
            echo "  ✗ $filepath — MISSING"
            ((issues++))
            continue
        fi
        
        local current_hash=$(hash_file "$full_path")
        
        if [ "$current_hash" == "$hash" ]; then
            echo "  ✓ $filepath — unchanged"
        else
            echo "  ✗ $filepath — CHANGED"
            echo "      Snapshot:  $hash"
            echo "      Current:   $current_hash"
            ((issues++))
        fi
    done < "$latest/hashes.txt"
    
    echo ""
    if [ $issues -eq 0 ]; then
        echo "  ✓ All files verified — system intact"
    else
        echo "  ⚠ $issues file(s) have changed since last snapshot"
    fi
}

restore_snapshot() {
    echo "╔══════════════════════════════════════════════════════════════╗"
    echo "║                    RESTORE                                 ║"
    echo "╚══════════════════════════════════════════════════════════════╝"
    echo ""
    
    local latest=$(ls -d "$SNAPSHOT_DIR"/snap-*/ | sort -r | head -1)
    
    if [ -z "$latest" ]; then
        echo "  No snapshots found!"
        return 1
    fi
    
    echo "  Restoring from: $latest"
    echo ""
    
    # Restore each file from its copy in the snapshot dir
    while IFS='|' read -r filepath hash size date; do
        local full_path="$WORKDIR/$filepath"
        local src="$latest/$filepath"
        
        if [ -f "$src" ]; then
            echo "  Restoring $filepath..."
            cp -a "$src" "$full_path"
            echo "  ✓ $filepath restored"
        else
            echo "  ✗ $filepath — backup not found in snapshot"
        fi
    done < "$latest/hashes.txt"
    
    echo ""
    echo "  Restore complete."
    echo "  Run: ./bin/snapshot.sh verify"
}

diff_snapshot() {
    local latest=$(ls -d "$SNAPSHOT_DIR"/snap-*/ | sort -r | head -1)
    
    if [ -z "$latest" ]; then
        echo "  No snapshots found!"
        return
    fi
    
    echo "╔══════════════════════════════════════════════════════════════╗"
    echo "║                    DIFF                                    ║"
    echo "╚══════════════════════════════════════════════════════════════╝"
    echo ""
    
    while IFS='|' read -r filepath hash size date; do
        local full_path="$WORKDIR/$filepath"
        
        if [ ! -f "$full_path" ]; then
            echo "  ✗ $filepath — MISSING (was present at snapshot time)"
            continue
        fi
        
        local current_hash=$(hash_file "$full_path")
        if [ "$current_hash" != "$hash" ]; then
            echo "  CHANGED: $filepath"
            diff -u <(echo "$hash") <(hash_file "$full_path") || true
            echo ""
            echo "  File size changed: $size → $(stat -c%s "$full_path" 2>/dev/null || echo '?') bytes"
            echo ""
        fi
    done < "$latest/hashes.txt"
}

case "${1:-help}" in
    save)
        save_snapshot
        ;;
    verify)
        verify_snapshot
        ;;
    restore)
        restore_snapshot
        ;;
    diff)
        diff_snapshot
        ;;
    *)
        echo "Usage: $0 {save|verify|restore|diff}"
        echo ""
        echo "  save    - Create a full snapshot of all critical files"
        echo "  verify  - Check current files against last snapshot"
        echo "  restore - Restore all files from last snapshot"
        echo "  diff    - Show what changed since last snapshot"
        ;;
esac
