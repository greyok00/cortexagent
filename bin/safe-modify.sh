#!/bin/bash

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
BACKUP_DIR="$REPO_ROOT/.backups"
TIMESTAMP=$(date +%s)
DESCRIPTION="$1"; shift

mkdir -p "$BACKUP_DIR"

backup_file() {
    local file="$1"
    local base=$(basename "$file")
    local dir=$(dirname "$file")
    local safe_name=$(echo "$base" | sed 's/[\/]/_/g')
    local backup_name="${safe_name}.${TIMESTAMP}.bak"
    local backup_path="$BACKUP_DIR/$backup_name"

    cp -a "$file" "$backup_path"
    echo "  ✓ Backup: $file → $backup_path"
    echo "$backup_path"
}

restore_file() {
    local file="$1"
    local safe_name=$(basename "$file" | sed 's/[\/]/_/g')
    local latest=$(ls -t "$BACKUP_DIR/${safe_name}".*.bak 2>/dev/null | head -1)

    if [ -z "$latest" ]; then
        echo "  ✗ No backups found for: $file"
        return 1
    fi

    echo "  Restoring $file from $(basename "$latest")"
    cp -a "$latest" "$file"
    echo "  ✓ Restored"
}

list_backups() {
    local file="$1"
    local safe_name=$(basename "$file" | sed 's/[\/]/_/g')
    local backups=$(ls -lt "$BACKUP_DIR/${safe_name}".*.bak 2>/dev/null)

    if [ -z "$backups" ]; then
        echo "  No backups found for: $file"
        return
    fi

    echo "  Backups for $file:"
    echo "$backups"
}

case "$1" in
    --backup)
        echo "[$DESCRIPTION]"
        backup_file "$2"
        ;;
    --restore)
        echo "[$DESCRIPTION]"
        restore_file "$2"
        ;;
    --list)
        list_backups "$2"
        ;;
    --atomic-write)
        shift
        local_content=$(cat)
        target_file="$1"; shift
        echo "[$DESCRIPTION]"

        cp "$target_file" "$BACKUP_DIR/$(basename "$target_file" | sed 's/[\/]/_/g').${TIMESTAMP}.bak"
        echo "  ✓ Backup created"

        echo "$local_content" > "$target_file.tmp"
        mv "$target_file.tmp" "$target_file"
        echo "  ✓ Atomic write: $target_file"
        ;;
    *)
        echo "[$DESCRIPTION]"
        backup_file "$1"
        ;;
esac
