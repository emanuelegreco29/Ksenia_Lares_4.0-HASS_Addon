#!/bin/bash
# Linting script for Ksenia Lares integration code (excludes tests)

FIX_MODE=false
LINT_FAILED=false

# Parse arguments
if [[ "$1" == "--help" ]]; then
    echo "Linting script for Ksenia Lares integration"
    echo ""
    echo "Usage: ./scripts/lint.sh [OPTION]"
    echo ""
    echo "Options:"
    echo "  (no args)    Check for linting issues (read-only)"
    echo "  --fix        Auto-fix formatting and import issues"
    echo "  --help       Show this help message"
    exit 0
fi

if [[ "$1" == "--fix" ]]; then
    FIX_MODE=true
fi

echo "🔍 Running linting on integration code..."
[[ "$FIX_MODE" == "true" ]] && echo "📝 FIX MODE: Auto-correcting issues..."
echo

# Black
if $FIX_MODE; then
    echo "Running: Black (auto-format)"
    black custom_components/ksenia_lares/ --line-length=100 || LINT_FAILED=true
else
    echo "Running: Black (check)"
    if ! black custom_components/ksenia_lares/ --line-length=100 --check 2>&1; then
        LINT_FAILED=true
    fi
fi
if [[ "$LINT_FAILED" == "false" ]]; then
    echo "✓ Black passed"
fi
echo

# isort
if [[ "$LINT_FAILED" == "false" ]]; then
    if $FIX_MODE; then
        echo "Running: isort (auto-sort)"
        isort custom_components/ksenia_lares/ --profile=black --line-length=100 || LINT_FAILED=true
    else
        echo "Running: isort (check)"
        if ! isort custom_components/ksenia_lares/ --profile=black --line-length=100 --check-only 2>&1; then
            LINT_FAILED=true
        fi
    fi
    if [[ "$LINT_FAILED" == "false" ]]; then
        echo "✓ isort passed"
    fi
    echo
fi

# Ruff
if [[ "$LINT_FAILED" == "false" ]]; then
    if $FIX_MODE; then
        echo "Running: Ruff (auto-fix)"
        ruff check custom_components/ksenia_lares/ --fix --config=pyproject.toml || LINT_FAILED=true
    else
        echo "Running: Ruff (check)"
        if ! ruff check custom_components/ksenia_lares/ --config=pyproject.toml 2>&1; then
            LINT_FAILED=true
        fi
    fi
    if [[ "$LINT_FAILED" == "false" ]]; then
        echo "✓ Ruff passed"
    fi
    echo
fi

# Bandit (security - continue even if previous failed)
if [[ "$LINT_FAILED" == "false" ]]; then
    echo "Running: Bandit (security)"
    if ! bandit -r custom_components/ksenia_lares/ --configfile=pyproject.toml -q 2>&1; then
        LINT_FAILED=true
    else
        echo "✓ Bandit passed"
    fi
    echo
fi

# Summary
echo "────────────────────────────────────"
if [[ "$LINT_FAILED" == "true" ]]; then
    if [[ "$FIX_MODE" == "true" ]]; then
        echo "⚠️  Some issues could not be auto-fixed. Please review the errors above."
        exit 1
    else
        echo "❌ Linting issues found!"
        echo ""
        echo "To auto-fix formatting and import issues, run:"
        echo ""
        echo "  ./scripts/lint.sh --fix"
        echo ""
        exit 1
    fi
else
    echo "✅ All checks passed!"
    exit 0
fi
echo

# YAMLLint
echo "Running: YAMLLint"
yamllint -d "{extends: default, rules: {line-length: {max: 120}}}" custom_components/ksenia_lares/ || true
echo "✓ YAMLLint passed"
echo

# Radon
echo "Running: Radon (complexity metrics)"
radon cc custom_components/ksenia_lares/ -a
echo
radon mi custom_components/ksenia_lares/ -s
echo

echo "✓ All checks passed!"
