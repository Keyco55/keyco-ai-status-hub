#!/bin/bash
# Same-source transactional deploy + verify for keyco-ai-status-hub.
#
# Installs the collector (src/ai-resource-hud) and the Swift menu helper
# (built from src/ai-resource-hud-menu.swift) from ONE source tree in a
# single operation, applies ad-hoc signing to the helper, writes a
# sanitized install manifest, and verifies installed hashes afterward.
#
# Transactional guarantee: any failure during deployment restores the exact
# pre-deploy runtime state (collector, menu helper, manifest) — a failure
# can never leave mixed versions behind. The manifest is committed LAST
# and always describes verified live artifacts.
#
# Source policy: real deployment from a dirty source tree is FORBIDDEN. The
# source must be a clean committed git checkout; tracked, staged, or
# untracked (non-ignored) modifications refuse the deployment.
#
# Safety: never touches AGY settings, LaunchAgents, provider credentials,
# or the network. Only writes under the target HOME's .local/bin and
# .cache/ai-resource-hud. Pass --home with a temporary root to exercise
# this script synthetically. Destination symlinks are refused, never
# followed.
#
# Shell note: bash with `set -euo pipefail` (not /bin/sh) so failures in
# pipelines such as `shasum ... | awk` propagate instead of being masked.
# Test-only failure injection lives behind STATUS_HUB_INJECT_FAIL and is
# inert unless explicitly set (see maybe_inject).
#
# Usage:
#   deploy-status-hub.sh [--home DIR] [--source DIR] [--verify-only] [--print-manifest]

set -euo pipefail

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
DEFAULT_SOURCE_DIR=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)

HOME_DIR="${HOME:-}"
SOURCE_DIR="$DEFAULT_SOURCE_DIR"
VERIFY_ONLY=0
PRINT_MANIFEST=0

# Test-only failure injection points (inert unless STATUS_HUB_INJECT_FAIL is
# set): collector-install | helper-install | manifest-write | verify
INJECT_FAIL="${STATUS_HUB_INJECT_FAIL:-}"

usage() {
    echo "usage: $(basename -- "$0") [--home DIR] [--source DIR] [--verify-only] [--print-manifest]" >&2
}

while [ $# -gt 0 ]; do
    case "$1" in
        --home)
            [ $# -ge 2 ] || { usage; exit 2; }
            HOME_DIR="$2"
            shift 2
            ;;
        --source)
            [ $# -ge 2 ] || { usage; exit 2; }
            SOURCE_DIR="$2"
            shift 2
            ;;
        --verify-only)
            VERIFY_ONLY=1
            shift
            ;;
        --print-manifest)
            PRINT_MANIFEST=1
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            usage
            exit 2
            ;;
    esac
done

[ -n "$HOME_DIR" ] || { echo "error: HOME is unset and --home was not given" >&2; exit 2; }
[ -d "$HOME_DIR" ] || { echo "error: home directory does not exist: $HOME_DIR" >&2; exit 2; }

COLLECTOR_SRC="$SOURCE_DIR/src/ai-resource-hud"
MENU_SRC="$SOURCE_DIR/src/ai-resource-hud-menu.swift"
BIN_DIR="$HOME_DIR/.local/bin"
RUNTIME_CACHE_DIR="$HOME_DIR/.cache/ai-resource-hud"
COLLECTOR_DEST="$BIN_DIR/ai-resource-hud"
HELPER_DEST="$BIN_DIR/ai-resource-hud-menu"
MANIFEST="$RUNTIME_CACHE_DIR/install.json"

[ -f "$COLLECTOR_SRC" ] || { echo "error: collector source missing: $COLLECTOR_SRC" >&2; exit 1; }
[ -f "$MENU_SRC" ] || { echo "error: menu source missing: $MENU_SRC" >&2; exit 1; }

# ---------------------------------------------------------------------------
# Transaction state (AGY-DEPLOY-01-R1). Once the first live mutation lands,
# ROLLBACK_NEEDED=1 and EVERY subsequent failure — explicit die() or an
# unexpected set -e exit (a failing date, hash, or rename included) — must
# route through rollback. The EXIT path below detects the flag; rollback is
# never left to a generic cleanup trap.
# ---------------------------------------------------------------------------
ROLLBACK_DIR=""
STAGE_DIR=""
STAGE_COLLECTOR=""
STAGE_HELPER=""
MANIFEST_TMP=""
HAD_COLLECTOR=0
HAD_HELPER=0
HAD_MANIFEST=0
ROLLBACK_NEEDED=0
ROLLBACK_DONE=0
ROLLBACK_OK=0

rollback() {
    # Idempotent: only the first invocation performs restoration.
    if [ "$ROLLBACK_DONE" -eq 1 ]; then
        return "$ROLLBACK_OK"
    fi
    ROLLBACK_DONE=1
    ROLLBACK_OK=1
    if [ -n "$MANIFEST_TMP" ]; then
        rm -f "$MANIFEST_TMP" || true
        MANIFEST_TMP=""
    fi
    if [ -z "$ROLLBACK_DIR" ]; then
        return 0
    fi
    if [ "$ROLLBACK_NEEDED" -eq 0 ]; then
        # No live mutation ever happened: nothing to restore.
        return 0
    fi
    if [ "${STATUS_HUB_INJECT_ROLLBACK_FAIL:-}" = "1" ]; then
        echo "error: injected rollback restoration failure" >&2
        ROLLBACK_OK=0
    else
        if [ "$HAD_COLLECTOR" -eq 1 ]; then
            cp -p "$ROLLBACK_DIR/ai-resource-hud" "$COLLECTOR_DEST" 2>/dev/null || ROLLBACK_OK=0
        elif [ -n "$STAGE_COLLECTOR" ] && [ -f "$COLLECTOR_DEST" ] \
            && cmp -s "$COLLECTOR_DEST" "$STAGE_COLLECTOR" 2>/dev/null; then
            # No pre-deploy collector existed: remove only the file this run
            # installed (hash-guarded so foreign state is never deleted).
            rm -f "$COLLECTOR_DEST" || ROLLBACK_OK=0
        fi
        if [ "$HAD_HELPER" -eq 1 ]; then
            cp -p "$ROLLBACK_DIR/ai-resource-hud-menu" "$HELPER_DEST" 2>/dev/null || ROLLBACK_OK=0
        elif [ -n "$STAGE_HELPER" ] && [ -f "$HELPER_DEST" ] \
            && cmp -s "$HELPER_DEST" "$STAGE_HELPER" 2>/dev/null; then
            rm -f "$HELPER_DEST" || ROLLBACK_OK=0
        fi
        if [ "$HAD_MANIFEST" -eq 1 ]; then
            cp -p "$ROLLBACK_DIR/install.json" "$MANIFEST" 2>/dev/null || ROLLBACK_OK=0
        else
            rm -f "$MANIFEST" 2>/dev/null || ROLLBACK_OK=0
        fi
    fi
    # Verify the restored state before claiming anything.
    if [ "$ROLLBACK_OK" -eq 1 ]; then
        if [ "$HAD_COLLECTOR" -eq 1 ]; then
            cmp -s "$ROLLBACK_DIR/ai-resource-hud" "$COLLECTOR_DEST" 2>/dev/null || ROLLBACK_OK=0
        else
            [ ! -e "$COLLECTOR_DEST" ] || ROLLBACK_OK=0
        fi
        if [ "$HAD_HELPER" -eq 1 ]; then
            cmp -s "$ROLLBACK_DIR/ai-resource-hud-menu" "$HELPER_DEST" 2>/dev/null || ROLLBACK_OK=0
        else
            [ ! -e "$HELPER_DEST" ] || ROLLBACK_OK=0
        fi
        if [ "$HAD_MANIFEST" -eq 1 ]; then
            cmp -s "$ROLLBACK_DIR/install.json" "$MANIFEST" 2>/dev/null || ROLLBACK_OK=0
        else
            [ ! -e "$MANIFEST" ] || ROLLBACK_OK=0
        fi
    fi
    if [ "$ROLLBACK_OK" -eq 1 ]; then
        echo "rollback: restored pre-deploy runtime state" >&2
        rm -rf "$ROLLBACK_DIR" || true
        ROLLBACK_DIR=""
    else
        # Never delete the only recovery copies after a failed restoration.
        echo "error: rollback FAILED; recovery backups kept in $ROLLBACK_DIR" >&2
    fi
    return "$ROLLBACK_OK"
}

die() {
    echo "error: $*" >&2
    rollback || true
    exit 1
}

maybe_inject() {
    [ "${INJECT_FAIL:-}" = "$1" ] && die "injected failure ($1)"
    return 0
}

cleanup_stage() {
    if [ -n "${STAGE_DIR:-}" ]; then
        rm -rf "$STAGE_DIR" || true
    fi
    # Rollback backups are deleted only on verified success (inside
    # rollback() or the success path); a failed rollback keeps them.
    if [ -n "${ROLLBACK_DIR:-}" ] && [ "$ROLLBACK_OK" -eq 1 ]; then
        rm -rf "$ROLLBACK_DIR" || true
    fi
    return 0
}

on_exit() {
    local rc=$?
    if [ "$ROLLBACK_NEEDED" -eq 1 ] && [ "$ROLLBACK_DONE" -eq 0 ]; then
        # A post-mutation failure that bypassed die() (e.g. set -e on an
        # unexpected command): attempt rollback exactly once.
        rollback || true
    fi
    cleanup_stage
    exit "$rc"
}
trap on_exit EXIT INT TERM

sha256_file() {
    shasum -a 256 "$1" | awk '{print $1}'
}

manifest_field() {
    python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))[sys.argv[2]])' "$MANIFEST" "$1"
}

# ---------------------------------------------------------------------------
# Preconditions
# ---------------------------------------------------------------------------
require_clean_source() {
    git -C "$SOURCE_DIR" rev-parse --git-dir >/dev/null 2>&1 \
        || die "source is not a git checkout: $SOURCE_DIR"
    local dirty
    dirty=$(git -C "$SOURCE_DIR" status --porcelain 2>/dev/null | wc -l | tr -d ' ') \
        || die "cannot inspect source tree state"
    case "$dirty" in
        ''|*[!0-9]*) die "cannot inspect source tree state" ;;
    esac
    if [ "$dirty" -gt 0 ]; then
        die "refusing dirty source tree ($dirty uncommitted/untracked entries); commit, stash, or ignore them first"
    fi
    SOURCE_COMMIT=$(git -C "$SOURCE_DIR" rev-parse HEAD 2>/dev/null) \
        || die "cannot resolve source HEAD"
    [ -n "$SOURCE_COMMIT" ] || die "cannot resolve source HEAD"
}

# AGY-SHELL-01-R2: no deployment path may escape through a symlinked
# parent. Checked before any mkdir so missing parents are still created as
# real directories afterwards.
validate_parents() {
    local dir
    for dir in "$HOME_DIR/.local" "$BIN_DIR" "$HOME_DIR/.cache" "$RUNTIME_CACHE_DIR"; do
        if [ -L "$dir" ]; then
            die "parent directory must not be a symlink: $dir"
        fi
    done
}

# AGY-SHELL-01-R1: each existing destination must be absent or a regular
# file. Symlinks, directories, FIFOs, sockets, and devices are rejected by
# file type and never replaced.
require_regular_or_absent() {
    # $1 = path, $2 = label. -L matches dangling symlinks as well; -f is
    # true only for regular files, so every other type is refused below.
    if [ -L "$1" ]; then
        die "$2 must not be a symlink: $1"
    fi
    if [ -e "$1" ] && [ ! -f "$1" ]; then
        die "$2 must be absent or a regular file: $1"
    fi
}

validate_destinations() {
    if [ -e "$BIN_DIR" ] && [ ! -d "$BIN_DIR" ]; then
        die "bin destination is not a directory: $BIN_DIR"
    fi
    require_regular_or_absent "$COLLECTOR_DEST" "collector destination"
    require_regular_or_absent "$HELPER_DEST" "menu helper destination"
    require_regular_or_absent "$MANIFEST" "install manifest"
}

# Exact manifest schema: no missing keys, no extra keys.
MANIFEST_SCHEMA_KEYS="collector_sha256,installed_at,menu_sha256,runtime_version,schema_version,source_commit"

validate_manifest_schema() {
    local keys
    keys=$(python3 -c 'import json,sys; print(",".join(sorted(json.load(open(sys.argv[1])).keys())))' "$MANIFEST") \
        || die "malformed manifest: $MANIFEST"
    [ "$keys" = "$MANIFEST_SCHEMA_KEYS" ] || die "manifest schema mismatch: $MANIFEST"
}

verify_installation() {
    [ -f "$MANIFEST" ] || { echo "error: install manifest missing: $MANIFEST" >&2; return 1; }
    [ -f "$COLLECTOR_DEST" ] || { echo "error: installed collector missing" >&2; return 1; }
    [ -f "$HELPER_DEST" ] || { echo "error: installed menu helper missing" >&2; return 1; }
    local installed_collector installed_menu recorded_collector recorded_menu recorded_commit
    installed_collector=$(sha256_file "$COLLECTOR_DEST") || return 1
    installed_menu=$(sha256_file "$HELPER_DEST") || return 1
    recorded_collector=$(manifest_field collector_sha256) || return 1
    recorded_menu=$(manifest_field menu_sha256) || return 1
    [ "$installed_collector" = "$recorded_collector" ] || { echo "error: collector hash mismatch" >&2; return 1; }
    [ "$installed_menu" = "$recorded_menu" ] || { echo "error: menu helper hash mismatch" >&2; return 1; }
    recorded_commit=$(manifest_field source_commit) || return 1
    [ "$recorded_commit" = "$SOURCE_COMMIT" ] || { echo "error: manifest source_commit does not match source HEAD" >&2; return 1; }
    echo "verify: collector sha256 $installed_collector"
    echo "verify: menu helper sha256 $installed_menu"
    echo "verify: source commit $recorded_commit"
    return 0
}

if [ "$VERIFY_ONLY" -eq 1 ]; then
    # AGY-PROV-01-R1: verify-only enforces the same clean-source policy and
    # proves provenance: exact schema, commit equality, hash equality.
    SOURCE_COMMIT=""
    require_clean_source
    validate_parents
    validate_destinations
    validate_manifest_schema
    verify_installation || exit 1
    echo "verify: OK (same-source provenance confirmed)"
    exit 0
fi

command -v swiftc >/dev/null 2>&1 || die "swiftc not found in PATH"
command -v shasum >/dev/null 2>&1 || die "shasum not found in PATH"
if [ "$(uname -s)" = "Darwin" ]; then
    command -v codesign >/dev/null 2>&1 || die "codesign not found in PATH"
fi
command -v python3 >/dev/null 2>&1 || die "python3 not found in PATH"
command -v git >/dev/null 2>&1 || die "git not found in PATH"

# 1. Validate source (clean committed tree only) and destinations.
SOURCE_COMMIT=""
require_clean_source
validate_parents
validate_destinations

mkdir -p "$BIN_DIR" "$RUNTIME_CACHE_DIR"
chmod 0700 "$RUNTIME_CACHE_DIR"

STAGE_DIR=$(mktemp -d "${TMPDIR:-/tmp}/status-hub-deploy.XXXXXX")
ROLLBACK_DIR=$(mktemp -d "${TMPDIR:-/tmp}/status-hub-rollback.XXXXXX")
STAGE_COLLECTOR="$STAGE_DIR/ai-resource-hud"
STAGE_HELPER="$STAGE_DIR/ai-resource-hud-menu"
MANIFEST_TMP=""

# 2-4. Build/stage collector + helper, sign, hash staged artifacts.
cp "$COLLECTOR_SRC" "$STAGE_COLLECTOR" || die "cannot stage collector"
chmod 0755 "$STAGE_COLLECTOR" || die "cannot stage collector"
swiftc -O -o "$STAGE_HELPER" "$MENU_SRC" -framework AppKit || die "swift helper build failed"
if [ "$(uname -s)" = "Darwin" ]; then
    codesign --force -s - -- "$STAGE_HELPER" || die "ad-hoc signing failed"
fi
STAGED_COLLECTOR_SHA=$(sha256_file "$STAGE_COLLECTOR") || die "cannot hash staged collector"
STAGED_HELPER_SHA=$(sha256_file "$STAGE_HELPER") || die "cannot hash staged helper"

# 5. Preserve current live state for rollback.
if [ -f "$COLLECTOR_DEST" ]; then
    cp -p "$COLLECTOR_DEST" "$ROLLBACK_DIR/ai-resource-hud" || die "cannot back up collector"
    HAD_COLLECTOR=1
fi
if [ -f "$HELPER_DEST" ]; then
    cp -p "$HELPER_DEST" "$ROLLBACK_DIR/ai-resource-hud-menu" || die "cannot back up menu helper"
    HAD_HELPER=1
fi
if [ -f "$MANIFEST" ]; then
    cp -p "$MANIFEST" "$ROLLBACK_DIR/install.json" || die "cannot back up manifest"
    HAD_MANIFEST=1
fi

# Same-directory temp-file replacement: never write live destinations
# directly, so a crash cannot leave a half-written artifact behind.
install_file() {
    # $1 = staged source, $2 = live destination, $3 = mode
    local tmp
    tmp=$(mktemp "${2%/*}/.deploy.XXXXXX") || return 1
    cp "$1" "$tmp" || { rm -f "$tmp"; return 1; }
    chmod "$3" "$tmp" || { rm -f "$tmp"; return 1; }
    mv "$tmp" "$2" || { rm -f "$tmp"; return 1; }
}

# 6-7. Commit replacements, then verify LIVE hashes. From the first
# successful install_file on, ROLLBACK_NEEDED stays 1 until the whole
# transaction (artifacts + manifest + final verification) succeeds, so any
# later failure — including timestamp, hash, or rename commands failing
# under set -e — routes through rollback via die() or the EXIT path.
install_file "$STAGE_COLLECTOR" "$COLLECTOR_DEST" 0755 || die "collector installation failed"
ROLLBACK_NEEDED=1
maybe_inject collector-install
install_file "$STAGE_HELPER" "$HELPER_DEST" 0755 || die "menu helper installation failed"
maybe_inject helper-install
LIVE_COLLECTOR_SHA=$(sha256_file "$COLLECTOR_DEST") || die "cannot hash installed collector"
LIVE_HELPER_SHA=$(sha256_file "$HELPER_DEST") || die "cannot hash installed helper"
[ "$LIVE_COLLECTOR_SHA" = "$STAGED_COLLECTOR_SHA" ] || die "installed collector hash mismatch"
[ "$LIVE_HELPER_SHA" = "$STAGED_HELPER_SHA" ] || die "installed helper hash mismatch"
maybe_inject verify

# 8. Commit manifest LAST, describing the verified live artifacts.
installed_at=$(date -u +%Y-%m-%dT%H:%M:%SZ) || die "cannot generate timestamp"
maybe_inject timestamp
runtime_version="${AI_RESOURCE_HUD_RUNTIME_VERSION:-unknown}"
MANIFEST_TMP=$(mktemp "$RUNTIME_CACHE_DIR/.install.XXXXXX") || die "cannot stage manifest"
python3 - "$MANIFEST_TMP" "$SOURCE_COMMIT" "$LIVE_COLLECTOR_SHA" "$LIVE_HELPER_SHA" "$installed_at" "$runtime_version" <<'EOF' || die "cannot render manifest"
import json, sys
_, path, source_commit, collector_sha, menu_sha, installed_at, runtime_version = sys.argv
record = {
    "schema_version": 1,
    "source_commit": source_commit,
    "collector_sha256": collector_sha,
    "menu_sha256": menu_sha,
    "installed_at": installed_at,
    "runtime_version": runtime_version,
}
with open(path, "w", encoding="utf-8") as handle:
    json.dump(record, handle, sort_keys=True, separators=(",", ":"))
    handle.write("\n")
EOF
maybe_inject manifest-write
chmod 0600 "$MANIFEST_TMP" || die "cannot stage manifest"
mv "$MANIFEST_TMP" "$MANIFEST" || die "cannot commit manifest"
chmod 0600 "$MANIFEST" || die "cannot commit manifest"
MANIFEST_TMP=""
maybe_inject manifest-commit

verify_installation || die "post-install verification failed"
if [ "$PRINT_MANIFEST" -eq 1 ]; then
    echo "manifest: $(cat "$MANIFEST")"
fi
echo "deploy: OK (collector + menu helper installed from the same source tree)"
ROLLBACK_NEEDED=0
ROLLBACK_DONE=1
ROLLBACK_OK=1
rm -rf "$ROLLBACK_DIR" "$STAGE_DIR"
ROLLBACK_DIR=""
STAGE_DIR=""
