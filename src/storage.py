"""Simple storage layer for expenses.

Keeps expenses in memory and persists them to a local JSON file after every
write, so data survives a server restart. No database required, per the
assignment spec.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path
from datetime import date as date_type

from .models import Expense, ExpenseCreate


class ExpenseStore:
    def __init__(self, data_file: str | Path = "expenses.json"):
        self._path = Path(data_file)
        self._lock = threading.Lock()
        self._expenses: dict[int, Expense] = {}
        self._next_id = 1
        self._load()

    # -- persistence -----------------------------------------------------
    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            raw = json.loads(self._path.read_text())
        except (json.JSONDecodeError, OSError):
            # Corrupt or unreadable file: start fresh rather than crash on boot.
            return
        for item in raw:
            try:
                expense = Expense(**item)
            except Exception:
                # Skip rows that don't match the current schema (e.g. old
                # test data saved before validation rules were tightened)
                # rather than crashing the whole server on startup.
                continue
            self._expenses[expense.id] = expense
        if self._expenses:
            self._next_id = max(self._expenses) + 1

    def _save(self) -> None:
        data = [
            json.loads(e.model_dump_json())
            for e in sorted(self._expenses.values(), key=lambda e: e.id)
        ]
        self._path.write_text(json.dumps(data, indent=2, default=str))

    # -- CRUD --------------------------------------------------------------
    def add(self, payload: ExpenseCreate) -> Expense:
        with self._lock:
            expense = Expense(id=self._next_id, **payload.model_dump())
            self._expenses[expense.id] = expense
            self._next_id += 1
            self._save()
            return expense

    def list_all(self) -> list[Expense]:
        return sorted(self._expenses.values(), key=lambda e: e.id)

    def get(self, expense_id: int) -> Expense | None:
        return self._expenses.get(expense_id)

    def filter_by_category(self, category: str) -> list[Expense]:
        cat = category.strip().lower()
        return [
            e for e in self.list_all()
            if self._category_str(e.category).strip().lower() == cat
        ]

    @staticmethod
    def _category_str(category) -> str:
        """Category may be a `Category` enum member or a plain string
        (legacy data). `str(enum_member)` returns "Category.FOOD" rather
        than "Food" for str-based Enums, so use `.value` when available."""
        return category.value if hasattr(category, "value") else category

    def delete(self, expense_id: int) -> bool:
        with self._lock:
            if expense_id not in self._expenses:
                return False
            del self._expenses[expense_id]
            self._save()
            return True

    def total(self) -> float:
        return round(sum(e.amount for e in self._expenses.values()), 2)

    def totals_by_category(self) -> dict[str, dict]:
        """Returns {category: {"total": float, "count": int}} for every
        category that has at least one expense."""
        totals: dict[str, dict] = {}
        for e in self._expenses.values():
            key = e.category.value if hasattr(e.category, "value") else e.category
            entry = totals.setdefault(key, {"total": 0.0, "count": 0})
            entry["total"] = round(entry["total"] + e.amount, 2)
            entry["count"] += 1
        return totals

    def clear(self) -> None:
        """Used by tests to reset state between runs."""
        with self._lock:
            self._expenses.clear()
            self._next_id = 1
            self._save()
