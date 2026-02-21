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
if [[ "$FIX_MODE" == "true" ]]; then
    echo "Running: Black (auto-format)"
    if black custom_components/ksenia_lares/ --line-length=100; then
        echo "✓ Black passed"
    else
        LINT_FAILED=true
    fi
else
    echo "Running: Black (check)"
    if black custom_components/ksenia_lares/ --line-length=100 --check 2>&1; then
        echo "✓ Black passed"
    else
        LINT_FAILED=true
    fi
fi
echo

# isort
if [[ "$LINT_FAILED" == "false" ]]; then
    if [[ "$FIX_MODE" == "true" ]]; then
        echo "Running: isort (auto-sort)"
        if isort custom_components/ksenia_lares/ --profile=black --line-length=100; then
            echo "✓ isort passed"
        else
            LINT_FAILED=true
        fi
    else
        echo "Running: isort (check)"
        if isort custom_components/ksenia_lares/ --profile=black --line-length=100 --check-only 2>&1; then
            echo "✓ isort passed"
        else
            LINT_FAILED=true
        fi
    fi
    echo
fi

# Ruff
if [[ "$LINT_FAILED" == "false" ]]; then
    if [[ "$FIX_MODE" == "true" ]]; then
        echo "Running: Ruff (auto-fix)"
        if ruff check custom_components/ksenia_lares/ --fix --config=pyproject.toml; then
            echo "✓ Ruff passed"
        else
            LINT_FAILED=true
        fi
    else
        echo "Running: Ruff (check)"
        if ruff check custom_components/ksenia_lares/ --config=pyproject.toml 2>&1; then
            echo "✓ Ruff passed"
        else
            LINT_FAILED=true
        fi
    fi
    echo
fi

# Pyright
if [[ "$LINT_FAILED" == "false" ]]; then
    echo "Running: Pyright (check)"
    if pyright custom_components/ksenia_lares/ 2>&1; then
        echo "✓ Pyright passed"
    else
        LINT_FAILED=true
    fi
    echo
fi

# YAMLLint
if [[ "$LINT_FAILED" == "false" ]]; then
    echo "Running: YAMLLint"
    if yamllint -d "{extends: default, rules: {line-length: {max: 120}}}" custom_components/ksenia_lares/ 2>&1; then
        echo "✓ YAMLLint passed"
    else
        LINT_FAILED=true
    fi
    echo
fi

# JSON validation
if [[ "$LINT_FAILED" == "false" ]]; then
    echo "Running: JSON validation"
    JSON_FAILED=false
    while IFS= read -r -d '' f; do
        if ! python -m json.tool "$f" > /dev/null 2>&1; then
            echo "✗ Invalid JSON: $f"
            JSON_FAILED=true
        fi
    done < <(find custom_components/ksenia_lares/ -name "*.json" -print0)
    if [[ "$JSON_FAILED" == "true" ]]; then
        LINT_FAILED=true
    else
        echo "✓ JSON validation passed"
    fi
    echo
fi


# Bandit (security)
if [[ "$LINT_FAILED" == "false" ]]; then
    echo "Running: Bandit (security)"
    if bandit -r custom_components/ksenia_lares/ --configfile=pyproject.toml -q 2>&1; then
        echo "✓ Bandit passed"
    else
        LINT_FAILED=true
    fi
    echo
fi

# Radon complexity (informational only — does not fail the build)
if [[ "$LINT_FAILED" == "false" ]]; then
    echo "Running: Radon (complexity)"
    RADON_DETAIL=$(radon cc custom_components/ksenia_lares/ --min C 2>&1)
    [[ -n "$RADON_DETAIL" ]] && echo "$RADON_DETAIL"
    radon cc custom_components/ksenia_lares/ -a 2>&1 | tail -2
    echo "To see details run: 'radon cc custom_components/ksenia_lares/ --total-average'"
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
