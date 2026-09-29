#!/usr/bin/env bash
# Fast local pre-PR check -- see CONTRIBUTING.md.
#
# Runs: the two standing guard tests, plus any test file touched directly by
# this branch's diff against master, plus any changed source file's
# same-named test (services/foo.py -> tests/test_foo.py) if one exists.
#
# This is a fast sanity check, NOT a substitute for the full suite. It will
# not catch a regression in code you didn't touch, or one only exercised by
# a test whose name doesn't match the changed file's basename.
set -euo pipefail
cd "$(dirname "$0")/.."   # dataops-agent/

TESTS="tests/test_rls_coverage_guard.py tests/test_celery_tenant_context_guard.py"

CHANGED=$(cd backend && git diff master --name-only --relative 2>/dev/null || true)
for f in $CHANGED; do
  case "$f" in
    tests/test_*.py)
      TESTS="$TESTS $f"
      ;;
    *.py)
      candidate="tests/test_$(basename "$f")"
      [ -f "backend/$candidate" ] && TESTS="$TESTS $candidate"
      ;;
  esac
done

TESTS=$(printf '%s\n' $TESTS | sort -u | tr '\n' ' ')
echo "Fast pre-PR subset: $TESTS"
docker compose exec backend python -m pytest $TESTS -v
