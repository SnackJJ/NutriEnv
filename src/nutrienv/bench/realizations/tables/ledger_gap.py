from __future__ import annotations

from ..types import LedgerGapRow

LEDGER_GAP_ROWS: tuple[LedgerGapRow, ...] = (
    LedgerGapRow(
        "lg-gold-lunch",
        "I forgot to log lunch — 150g of chicken breast. Add just that.",
        ("chicken_breast", "150 g", "today-lunch"),
        (
            ("banana", 100.0, "today-breakfast"),
            ("white_rice", 200.0, "today-dinner"),
        ),
        source="gold",
    ),
    LedgerGapRow(
        "lg-miss-breakfast",
        "I forgot breakfast — 80 g of oats. Add just that.",
        ("oats", "80 g", "today-breakfast"),
        (
            ("chicken_breast", 150.0, "today-lunch"),
            ("white_rice", 200.0, "today-dinner"),
        ),
    ),
    LedgerGapRow(
        "lg-miss-dinner",
        "Dinner never made it onto the ledger — 200 g of pasta. Add just that.",
        ("pasta", "200 g", "today-dinner"),
        (
            ("oats", 80.0, "today-breakfast"),
            ("chicken_breast", 150.0, "today-lunch"),
        ),
    ),
    LedgerGapRow(
        "lg-miss-snack",
        "I skipped logging my snack — a cup of Greek yogurt. Add just that.",
        ("greek_yogurt", "a cup", "today-snack"),
        (
            ("banana", 118.0, "today-breakfast"),
            ("chicken_breast", 150.0, "today-lunch"),
            ("white_rice", 200.0, "today-dinner"),
        ),
    ),
    LedgerGapRow(
        "lg-miss-lunch-three",
        "Lunch is the hole — a can of tuna. Add just that.",
        ("tuna", "a can", "today-lunch"),
        (
            ("oats", 80.0, "today-breakfast"),
            ("apple", 182.0, "today-snack"),
            ("salmon", 150.0, "today-dinner"),
        ),
    ),
)
