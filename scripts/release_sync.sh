#!/usr/bin/env bash
# Install or update PlasBench in ONE stable folder (normally ~/PlasBench), without touching anything that is yours.
#
#   release_sync.sh sync    RELEASE_DIR TARGET VERSION   copy a release into TARGET, replacing the previous release
#   release_sync.sh migrate OLD_INSTALL TARGET           carry an older versioned install (plasbench-0.x.y) into TARGET
#
# sync keeps TARGET/.plasbench-release-files: every file the release installed, with its SHA-256. On the next update
# only those files are replaced or removed. A release file you edited is copied to .plasbench-backup/<time>/ first,
# and nothing that is not a release file is ever touched: studies/ (your runs), config/local.env (your settings),
# your own tools under tools.d/, downloads and logs stay exactly where they are. Tool environments and databases live
# outside the folder and are reused as they are.
#
# migrate moves the old install's runs (results*/, studies/) into TARGET/studies/, and copies its settings
# (config/local.env, .ncbi.env, config/local.tsv) and own tools when TARGET has none yet. An old data/ directory that
# is a real directory (not yet shared) is moved to TARGET/data, where install.sh moves it to the shared data folder.
# It deletes nothing; the caller offers to remove the old folder afterwards.
set -euo pipefail

say() { printf '[plasbench] %s\n' "$*"; }
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
MANIFEST=".plasbench-release-files"

sha() { sha256sum "$1" | cut -d' ' -f1; }

cmd_sync() {
    local src="$1" dst="$2" version="$3"
    [[ -d "$src" ]] || die "release folder not found: $src"
    mkdir -p "$dst"
    src="$(cd "$src" && pwd)"
    dst="$(cd "$dst" && pwd)"
    [[ "$src" != "$dst" ]] || die "the release and the install folder are the same: $dst"
    local manifest="$dst/$MANIFEST"
    if [[ ! -f "$manifest" ]] && [[ -n "$(ls -A "$dst" 2>/dev/null)" ]]; then
        die "$dst already exists and is not a PlasBench install folder (it has no $MANIFEST). Choose another folder with PLASBENCH_INSTALL_DIR, or empty it."
    fi

    declare -A old=() new=()
    local sum path previous=""
    if [[ -f "$manifest" ]]; then
        previous="$(sed -n '1s/^# version\t//p' "$manifest")"
        while IFS=$'\t' read -r sum path; do
            [[ -z "$sum" || "$sum" == \#* ]] && continue
            old[$path]="$sum"
        done < "$manifest"
    fi
    local list
    list="$(cd "$src" && find . -type f ! -path './.git/*' ! -name "$MANIFEST" | sed 's|^\./||' | LC_ALL=C sort)"
    while IFS= read -r path; do [[ -n "$path" ]] && new[$path]=1; done <<< "$list"

    local backup kept=0 removed=0 written=0
    backup="$dst/.plasbench-backup/$(date +%Y%m%d-%H%M%S)"
    keep_copy() {   # a release file the user changed: keep their version before it is replaced or removed
        mkdir -p "$backup/$(dirname "$1")"
        cp -p "$dst/$1" "$backup/$1"
        kept=$((kept + 1))
    }
    # 1. files the previous release installed and this one does not
    for path in "${!old[@]}"; do
        [[ -n "${new[$path]:-}" ]] && continue
        [[ -f "$dst/$path" ]] || continue
        [[ "$(sha "$dst/$path")" == "${old[$path]}" ]] || keep_copy "$path"
        rm -f "$dst/$path"
        removed=$((removed + 1))
    done
    # 2. this release's files
    local tmp_manifest="$dst/$MANIFEST.new"
    printf '# version\t%s\n' "$version" > "$tmp_manifest"
    while IFS= read -r path; do
        [[ -n "$path" ]] || continue
        if [[ -f "$dst/$path" ]]; then
            local current; current="$(sha "$dst/$path")"
            if [[ -n "${old[$path]:-}" && "$current" != "${old[$path]}" ]] \
                    || [[ -z "${old[$path]:-}" && "$current" != "$(sha "$src/$path")" ]]; then
                keep_copy "$path"
            fi
        fi
        mkdir -p "$dst/$(dirname "$path")"
        cp -p "$src/$path" "$dst/$path"
        printf '%s\t%s\n' "$(sha "$dst/$path")" "$path" >> "$tmp_manifest"
        written=$((written + 1))
    done <<< "$list"
    mv "$tmp_manifest" "$manifest"
    say "PlasBench ${previous:+$previous -> }$version in $dst: $written release files written, $removed removed"
    if [[ "$kept" -gt 0 ]]; then
        say "$kept file(s) you had changed were kept in ${backup#$dst/} (put local settings in config/local.env instead)"
    fi
}

unique_dir() {   # a free name under $1 for $2: name, name-2, name-3, ...
    local base="$1" name="$2" candidate n=2
    candidate="$base/$name"
    while [[ -e "$candidate" ]]; do candidate="$base/$name-$n"; n=$((n + 1)); done
    printf '%s' "$candidate"
}

cmd_migrate() {
    local old="$1" dst="$2"
    [[ -d "$old" && -d "$dst" ]] || die "migrate needs an existing old install and target"
    old="$(cd "$old" && pwd)"; dst="$(cd "$dst" && pwd)"
    [[ "$old" != "$dst" ]] || return 0
    local version
    version="$(sed -n 's/^__version__ = "\([^"]*\)".*/\1/p' "$old/plasbench/__init__.py" 2>/dev/null)"
    version="${version:-unknown}"
    say "carrying $old (PlasBench $version) into $dst"
    local file
    for file in config/local.env .ncbi.env config/local.tsv; do
        if [[ -f "$old/$file" && ! -f "$dst/$file" ]]; then
            mkdir -p "$dst/$(dirname "$file")"
            cp -p "$old/$file" "$dst/$file"
            say "  settings: $file"
        fi
    done
    if [[ -d "$old/data" && ! -L "$old/data" && ! -e "$dst/data" ]]; then
        mv "$old/data" "$dst/data"
        say "  downloads: data/ moved (install.sh shares it from there)"
    fi
    mkdir -p "$dst/studies"
    local dir name target moved=0
    for dir in "$old"/results "$old"/results_*; do
        [[ -d "$dir" && ! -L "$dir" ]] || continue
        [[ -n "$(ls -A "$dir" 2>/dev/null)" ]] || continue
        name="$(basename "$dir")"
        case "$name" in results) name="results-$version" ;; results_*) name="${name#results_}-$version" ;; esac
        target="$(unique_dir "$dst/studies" "$name")"
        mkdir -p "$target"
        mv "$dir" "$target/results"
        printf '{\n  "name": "%s",\n  "migrated_from": "%s",\n  "plasbench_version": "%s",\n  "created": "%s",\n  "runs": []\n}\n' \
            "$(basename "$target")" "$dir" "$version" "$(date +%Y-%m-%dT%H:%M:%S%z)" > "$target/study.json"
        say "  run: $(basename "$dir")/ -> studies/$(basename "$target")/results/"
        moved=$((moved + 1))
    done
    if [[ -d "$old/studies" ]]; then
        for dir in "$old"/studies/*/; do
            [[ -d "$dir" ]] || continue
            target="$(unique_dir "$dst/studies" "$(basename "$dir")")"
            mv "${dir%/}" "$target"
            say "  study: $(basename "$dir") -> studies/$(basename "$target")"
            moved=$((moved + 1))
        done
    fi
    if [[ -d "$old/tools.d" ]]; then
        for dir in "$old"/tools.d/*/; do
            [[ -d "$dir" && "$(basename "$dir")" != "examples" && ! -e "$dst/tools.d/$(basename "$dir")" ]] || continue
            mkdir -p "$dst/tools.d"
            cp -rp "${dir%/}" "$dst/tools.d/"
            say "  your tool: tools.d/$(basename "$dir")"
        done
    fi
    printf 'This PlasBench %s folder was carried into %s on %s; its runs are in %s/studies.\n' \
        "$version" "$dst" "$(date +%Y-%m-%d)" "$dst" > "$old/MOVED_TO_PlasBench.txt"
    say "  $moved run folder(s) moved; nothing was deleted"
}

# removable OLD: may the old folder be deleted? Not while it still holds the only copy of downloads.
cmd_removable() {
    local old="$1"
    if [[ -d "$old/data" && ! -L "$old/data" ]]; then
        echo "its data/ folder holds downloads that are not shared yet"
        return 1
    fi
    return 0
}

case "${1:-}" in
    sync) shift; [[ $# -eq 3 ]] || die "usage: release_sync.sh sync RELEASE_DIR TARGET VERSION"; cmd_sync "$@" ;;
    migrate) shift; [[ $# -eq 2 ]] || die "usage: release_sync.sh migrate OLD_INSTALL TARGET"; cmd_migrate "$@" ;;
    removable) shift; cmd_removable "$1" ;;
    *) die "usage: release_sync.sh sync|migrate|removable ..." ;;
esac
