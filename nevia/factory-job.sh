#!/usr/bin/env bash
# Build a change for GitHub issue $1 on a short-lived Nevia computer, then clean up.
# SKELETON: running a coding agent inside a computer is not yet verified.
set -euo pipefail
issue="${1:?issue number}"
name="factory-$issue"
nevia new "$name" --wait
trap 'nevia rm "$name" --yes --wait' EXIT
# 1. check out the repo, 2. branch the staging database, 3. run the agent, 4. open a PR.
# nevia pg branch factory-staging -b "factory-$issue" --wait
echo "TODO: install agent, run it against issue $issue, push a branch, open a PR"
