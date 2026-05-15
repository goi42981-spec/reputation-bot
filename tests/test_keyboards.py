"""Tests for inline keyboard construction and callback data parsing."""

from __future__ import annotations

from reputation_bot.config import POINT_OPTIONS
from reputation_bot.keyboards import parse_callback_data, reputation_keyboard


def test_reputation_keyboard_contains_all_options() -> None:
    kb = reputation_keyboard(target_user_id=42)
    rows = kb.inline_keyboard
    assert len(rows) == 3  # plus row, minus row, cancel row

    plus_labels = [b.text for b in rows[0]]
    minus_labels = [b.text for b in rows[1]]
    assert plus_labels == [f"+{v}" for v in POINT_OPTIONS]
    assert minus_labels == [f"-{v}" for v in POINT_OPTIONS]

    # callback data carries the target user id.
    assert rows[0][0].callback_data == "rep:42:+1"
    assert rows[1][-1].callback_data == f"rep:42:-{POINT_OPTIONS[-1]}"
    assert rows[2][0].callback_data == "rep:42:cancel"


def test_parse_callback_data_valid_plus() -> None:
    assert parse_callback_data("rep:42:+10") == (42, "+10")


def test_parse_callback_data_valid_minus() -> None:
    assert parse_callback_data("rep:42:-500") == (42, "-500")


def test_parse_callback_data_cancel() -> None:
    assert parse_callback_data("rep:42:cancel") == (42, "cancel")


def test_parse_callback_data_invalid() -> None:
    assert parse_callback_data("notrep:42:+1") is None
    assert parse_callback_data("rep:abc:+1") is None
    assert parse_callback_data("rep:42:xyz") is None
    assert parse_callback_data("rep:42:") is None
    assert parse_callback_data("rep:42:+abc") is None
