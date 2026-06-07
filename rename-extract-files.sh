#!/usr/bin/env bash
# rename-extract-files.sh
# Rename llm-session-archive *.md extract files to match their # heading title.
# The new filename is derived from the first line of each file:
#   - Leading '# ' is stripped
#   - Spaces are replaced with underscores
#   - All other characters are preserved
#   - .md extension is kept

set -euo pipefail

MAX_STEM=40   # max filename stem length (before .md); truncates at last word boundary

usage() {
    cat <<'EOF'
Usage: rename-extract-files.sh [--dry-run] <path> [<path> ...]

Rename llm-session-archive *.md extract files whose filenames don't match
their # title.  Each <path> may be a file or a directory; directories are
processed non-recursively (all *.md files inside).

Files that don't look like llm-session-archive extracts are skipped with a
NOT EXTRACT warning.  An extract is identified by a '# Title' first line and
a recognised metadata field (Thread ID, Session ID, File, Created, ...) on
line 2.

Options:
  -d, --dry-run  Preview renames without making any changes
  -h, --help    Show this help and exit

Examples:
  rename-extract-files.sh JanTests-03
  rename-extract-files.sh --dry-run LmStudioTests
  rename-extract-files.sh session.md
  rename-extract-files.sh *.md
  rename-extract-files.sh --dry-run JanTests-03 LmStudioTests
EOF
}

# Return 0 if $1 looks like an llm-session-archive extract, 1 otherwise.
is_extract() {
    local f="$1" line1 line2
    line1=$(sed -n '1p' "$f")
    line2=$(sed -n '2p' "$f")
    # Line 1: '# ' followed by a non-empty title
    [[ "$line1" =~ ^#\ .+ ]]          || return 1
    # Line 2: a recognised metadata label (key: value)
    [[ "$line2" =~ ^[A-Za-z][A-Za-z\ ]+:[[:space:]]+ ]] || return 1
    return 0
}

moved=0; skipped=0; conflicts=0; not_extract=0

process_file() {
    local f="$1" first_line title new_name dir new_path

    if ! is_extract "$f"; then
        echo "NOT EXTRACT  $(basename "$f")" >&2
        (( not_extract++ )) || true
        return
    fi

    first_line=$(head -1 "$f")
    title="${first_line#\# }"
    new_name="${title// /_}"

    # Truncate at word boundary if stem is too long
    local flag=""
    if [[ ${#new_name} -gt $MAX_STEM ]]; then
        new_name="${new_name:0:$MAX_STEM}"
        [[ "$new_name" == *_* ]] && new_name="${new_name%_*}"
        flag="  (truncated)"
    fi
    dir="$(dirname "$f")"
    new_path="${dir}/${new_name}.md"

    # Already correctly named
    if [[ "$f" == "$new_path" ]]; then
        echo "SKIP         $(basename "$f")"
        (( skipped++ )) || true
        return
    fi

    # Collision guard
    if [[ -e "$new_path" ]]; then
        echo "CONFLICT     $(basename "$f")  ->  ${new_name}.md  (target exists)" >&2
        (( conflicts++ )) || true
        return
    fi

    if $DRY_RUN; then
        echo "DRY RUN      $(basename "$f")  ->  ${new_name}.md${flag}"
        (( moved++ )) || true
    else
        mv "$f" "$new_path"
        echo "MOVED        $(basename "$f")  ->  ${new_name}.md${flag}"
        (( moved++ )) || true
    fi
}

DRY_RUN=false
PATHS=()

while [[ $# -gt 0 ]]; do
    case "$1" in
        --dry-run|-d)  DRY_RUN=true ;;
        -h|--help)  usage; exit 0 ;;
        -*)         echo "ERROR: unknown option '$1'" >&2; echo >&2; usage >&2; exit 1 ;;
        *)          PATHS+=("$1") ;;
    esac
    shift
done

if [[ ${#PATHS[@]} -eq 0 ]]; then
    echo "ERROR: at least one file or directory argument required" >&2
    echo >&2; usage >&2; exit 1
fi

for path in "${PATHS[@]}"; do
    if [[ -f "$path" ]]; then
        process_file "$path"
    elif [[ -d "$path" ]]; then
        found=0
        for f in "$path"/*.md; do
            [[ -e "$f" ]] || continue
            (( found++ )) || true
            process_file "$f"
        done
        [[ $found -gt 0 ]] || echo "No .md files found in '$path'"
    else
        echo "ERROR: '$path' is not a file or directory" >&2
    fi
done

echo ""
if $DRY_RUN; then
    echo "Dry run: $moved would rename  |  $skipped already correct  |  $conflicts conflicts  |  $not_extract not extracts"
    echo "Re-run without --dry-run to apply."
else
    echo "Done. Moved: $moved  |  Skipped: $skipped  |  Conflicts: $conflicts  |  Not extracts: $not_extract"
fi
