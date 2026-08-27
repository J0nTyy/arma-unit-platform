"""Message variation: loading, humour gating, no-repeat, overrides, tone."""

import re
from pathlib import Path

import pytest

from app.services.message_catalog import MessageCatalog

BASE = """
plain_list:
  - "Only option."
varied:
  variants:
    - "Straight one."
    - "Straight two."
  witty:
    - "Witty one."
greet:
  variants:
    - "Hello {name}!"
"""


def write_messages(directory: Path, content: str, name: str = "test.yaml") -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / name).write_text(content, encoding="utf-8")
    return directory


def test_loads_both_schemas_and_formats_placeholders(tmp_path):
    catalog = MessageCatalog(write_messages(tmp_path / "base", BASE))
    assert catalog.pick("plain_list") == "Only option."
    assert catalog.pick("greet", name="Kartikey") == "Hello Kartikey!"


def test_humour_gating(tmp_path):
    base = write_messages(tmp_path / "base", BASE)
    for level in ("none", "low"):
        pool = MessageCatalog(base, humour=level).variants_for("varied")
        assert "Witty one." not in pool and len(pool) == 2
    for level in ("medium", "high"):
        pool = MessageCatalog(base, humour=level).variants_for("varied")
        assert "Witty one." in pool and len(pool) == 3


def test_never_repeats_the_previous_pick(tmp_path):
    catalog = MessageCatalog(write_messages(tmp_path / "base", BASE))
    picks = [catalog.pick("varied") for _ in range(30)]
    assert all(a != b for a, b in zip(picks, picks[1:]))
    assert set(picks) <= set(catalog.variants_for("varied"))  # only approved text


def test_unit_override_replaces_key(tmp_path):
    base = write_messages(tmp_path / "base", BASE)
    override = write_messages(
        tmp_path / "unit", 'varied:\n  variants:\n    - "Our voice."\n'
    )
    catalog = MessageCatalog(base, override)
    assert catalog.variants_for("varied") == ["Our voice."]
    assert catalog.pick("plain_list") == "Only option."  # non-overridden keys stay


def test_missing_key_fallback_and_error(tmp_path):
    catalog = MessageCatalog(write_messages(tmp_path / "base", BASE))
    assert catalog.pick("nope", fallback="Default {x}.", x=1) == "Default 1."
    with pytest.raises(KeyError):
        catalog.pick("nope")


def test_malformed_file_is_skipped_not_fatal(tmp_path):
    base = write_messages(tmp_path / "base", BASE)
    write_messages(base, ":\nnot yaml [", name="broken.yaml")
    assert MessageCatalog(base).pick("plain_list") == "Only option."


# --- tone rules over the SHIPPED content --------------------------------------

SHIPPED = Path("content/messages")
BANNED = re.compile(r"\bo7\b|🫡", re.IGNORECASE)


def test_shipped_messages_have_no_salute_spam():
    files = list(SHIPPED.glob("*.yaml"))
    assert files, "shipped message packs missing"
    for file in files:
        assert not BANNED.search(file.read_text(encoding="utf-8")), file


def test_app_code_has_no_salute_strings():
    for file in Path("app").rglob("*.py"):
        assert not BANNED.search(file.read_text(encoding="utf-8")), file


def test_shipped_catalog_loads_with_expected_keys():
    catalog = MessageCatalog(SHIPPED)
    assert {
        "member_greeting", "announce_published_tail", "announce_cancelled_tail",
        "announce_rescheduled_tail", "reminder_no_signups",
        "cert_granted_public", "ask_prompt",
    } <= catalog.keys()
    # Greeting variants all carry the required placeholders.
    for variant in catalog.variants_for("member_greeting"):
        for placeholder in ("{member}", "{unit_name}", "{channels}"):
            assert placeholder in variant