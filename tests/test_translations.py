"""Tests for translation file consistency."""

import json
from pathlib import Path

import pytest

_INTEGRATION_DIR = Path(__file__).parent.parent / "custom_components" / "ksenia_lares"
_STRINGS_FILE = _INTEGRATION_DIR / "strings.json"
_TRANSLATIONS_DIR = _INTEGRATION_DIR / "translations"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _collect_key_paths(d: dict, prefix: str = "") -> set[str]:
    """Recursively collect all dot-notation key paths from a nested dict."""
    paths: set[str] = set()
    for key, value in d.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            paths |= _collect_key_paths(value, path)
        else:
            paths.add(path)
    return paths


def test_en_json_is_identical_to_strings_json():
    """translations/en.json must be an exact content copy of strings.json."""
    strings = _load(_STRINGS_FILE)
    en = _load(_TRANSLATIONS_DIR / "en.json")
    assert en == strings, (
        "translations/en.json differs from strings.json — keep them in sync."
    )


@pytest.mark.parametrize(
    "translation_file",
    sorted(p for p in _TRANSLATIONS_DIR.glob("*.json") if p.stem != "en"),
    ids=lambda p: p.name,
)
def test_translation_keys_are_subset_of_strings(translation_file: Path):
    """Every key in a translation file must exist in strings.json (no rogue keys)."""
    strings_paths = _collect_key_paths(_load(_STRINGS_FILE))
    translation_paths = _collect_key_paths(_load(translation_file))

    extra = translation_paths - strings_paths
    assert not extra, (
        f"{translation_file.name} contains keys absent from strings.json:\n"
        + "\n".join(f"  {k}" for k in sorted(extra))
    )


@pytest.mark.parametrize(
    "translation_file",
    sorted(p for p in _TRANSLATIONS_DIR.glob("*.json") if p.stem != "en"),
    ids=lambda p: p.name,
)
def test_translation_completeness(translation_file: Path) -> None:
    """Every key in strings.json must be present in the translation file.
       Even if HA will fall back to English for missing keys, we want to be aware of any untranslated strings.
    """
    strings_paths = _collect_key_paths(_load(_STRINGS_FILE))
    translation_paths = _collect_key_paths(_load(translation_file))

    missing = strings_paths - translation_paths
    assert not missing, (
            f"{translation_file.name}: {len(missing)} untranslated key(s):\n"
            + "\n".join(f"  {k}" for k in sorted(missing))
    )
