#!/usr/bin/env bash
set -euo pipefail
SOURCE_REPO="$PWD"
TARGET="${RUNNER_TEMP:?}/flash-small-source"
BASE=7abaae9902dc0b7d7579c66795885fada6e85a43
EXPECTED=c7ef71dbfc3ce4611a18823b7ab7e57a884b49f7
PATCH="$SOURCE_REPO/experiments/small-amounts.patch"
printf '%s  %s\n' "e767f0590ec37a440d76188d06d294775c7be3844e415e67e56dd874b7284489" "$PATCH" | sha256sum -c -
test ! -e "$TARGET"
git worktree add --detach "$TARGET" "$BASE"
git -C "$TARGET" apply --check --index "$PATCH"
git -C "$TARGET" apply --index "$PATCH"
ACTUAL=$(git -C "$TARGET" write-tree)
test "$ACTUAL" = "$EXPECTED"
mkdir -p "$TARGET/evidence/small"
printf '{"base_commit":"%s","experiment_commit":"%s","patched_source_tree":"%s","patch_sha256":"e767f0590ec37a440d76188d06d294775c7be3844e415e67e56dd874b7284489","source_is_patch_applied":true,"mainnet_broadcast":false,"realized_pnl":"0"}\n' "$BASE" "${GITHUB_SHA:?}" "$ACTUAL" > "$TARGET/evidence/small/source-provenance.json"
git -C "$TARGET" archive --format=zip --output="$TARGET/evidence/small/tested-patched-source.zip" "$ACTUAL"
echo "VERIFIED_PATCHED_SOURCE_TREE=$ACTUAL"
