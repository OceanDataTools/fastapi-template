#!/usr/bin/env bash
# Find commits that downstream releases pin as a submodule and that only the
# project branches keep reachable. Run it before force-moving <project> /
# <project>_dev (see RELEASING.md, "Syncing project branches after a release").
#
# Usage, from the root of this repo:
#   scripts/check-downstream-pins.sh <downstream repo path> <submodule path> <project branch>
# e.g.
#   scripts/check-downstream-pins.sh ../openrvdas web_backend openrvdas
#
# Prints one line per commit that needs a tag (UNTAGGED), or that GitHub no
# longer has (MISSING), with the downstream tags that pin it. No output means
# every pinned commit survives the sync.
set -euo pipefail
DOWNSTREAM=$1 SUBMODULE=$2 PROJECT=$3
git fetch -q origin --tags
git -C "$DOWNSTREAM" fetch -q --tags
for tag in $(git -C "$DOWNSTREAM" tag -l); do
  sha=$(git -C "$DOWNSTREAM" ls-tree "$tag" "$SUBMODULE" | awk '{print $3}')
  [ -n "$sha" ] && echo "$sha $tag"
done | sort -k1,1 | awk '{tags[$1]=tags[$1]" "$2} END {for (s in tags) print s tags[s]}' |
while read -r sha tags; do
  if ! git cat-file -e "$sha^{commit}" 2>/dev/null; then
    git fetch -q origin "$sha" 2>/dev/null || { echo "MISSING   $sha  ($tags) - not on GitHub any more"; continue; }
  fi
  # Refs that survive the sync: everything except the project branches.
  keep=$(git for-each-ref --contains "$sha" --format='%(refname:short)' refs/remotes/origin refs/tags |
    grep -vx -e "origin/$PROJECT" -e "origin/${PROJECT}_dev" -e origin -e origin/HEAD || true)
  if [ -z "$keep" ]; then echo "UNTAGGED  $sha  ($tags)"; fi
done
