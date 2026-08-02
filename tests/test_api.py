"""Tests for the Smart Expense Tracker API.

Run with: pytest
Each test run uses a temp JSON file (see conftest.py) so tests never touch
real data and don't interfere with each other.
"""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    # Point the store at a fresh temp file *before* importing the app module,
    # since the module creates its ExpenseStore at import time.
    data_file = tmp_path / "expenses.json"
    monkeypatch.setenv("EXPENSES_DATA_FILE", str(data_file))

    import importlib
    from src import main as main_module
    importlib.reload(main_module)  # re-create app/store against the temp file

    with TestClient(main_module.app) as c:
        yield c


def make_expense(**overrides):
    payload = {
        "title": "Coffee",
        "amount": 4.5,
        "category": "Food",
        "date": "2026-01-15",
    }
    payload.update(overrides)
    return payload


def test_root(client):
    resp = client.get("/")
    assert resp.status_code == 200


def test_add_expense(client):
    resp = client.post("/expenses", json=make_expense())
    assert resp.status_code == 201
    body = resp.json()
    assert body["id"] == 1
    assert body["title"] == "Coffee"
    assert body["amount"] == 4.5
    assert body["category"] == "Food"
    assert body["date"] == "2026-01-15"


def test_add_expense_rejects_negative_amount(client):
    resp = client.post("/expenses", json=make_expense(amount=-5))
    assert resp.status_code == 422


def test_add_expense_rejects_zero_amount(client):
    resp = client.post("/expenses", json=make_expense(amount=0))
    assert resp.status_code == 422


def test_add_expense_rejects_blank_title(client):
    resp = client.post("/expenses", json=make_expense(title="   "))
    assert resp.status_code == 422


def test_add_expense_rejects_invalid_category(client):
    """Category must be one of the fixed enum values, e.g. can't be an
    arbitrary string like "string" or "banana"."""
    resp = client.post("/expenses", json=make_expense(category="banana"))
    assert resp.status_code == 422


def test_list_categories(client):
    resp = client.get("/categories")
    assert resp.status_code == 200
    categories = resp.json()
    assert "Food" in categories
    assert "Transport" in categories
    assert "string" not in categories


def test_list_expenses_empty(client):
    resp = client.get("/expenses")
    assert resp.status_code == 200
    assert resp.json() == []


def test_list_expenses_returns_all(client):
    client.post("/expenses", json=make_expense(title="Coffee"))
    client.post("/expenses", json=make_expense(title="Bus ticket", category="Transport", amount=2.0))
    resp = client.get("/expenses")
    assert resp.status_code == 200
    titles = {e["title"] for e in resp.json()}
    assert titles == {"Coffee", "Bus ticket"}


def test_filter_by_category(client):
    client.post("/expenses", json=make_expense(title="Coffee", category="Food"))
    client.post("/expenses", json=make_expense(title="Lunch", category="Food"))
    client.post("/expenses", json=make_expense(title="Bus ticket", category="Transport", amount=2.0))

    resp = client.get("/expenses", params={"category": "Food"})
    assert resp.status_code == 200
    titles = {e["title"] for e in resp.json()}
    assert titles == {"Coffee", "Lunch"}


def test_filter_by_category_is_case_insensitive(client):
    client.post("/expenses", json=make_expense(title="Coffee", category="Food"))
    resp = client.get("/expenses", params={"category": "food"})
    assert len(resp.json()) == 1


def test_get_single_expense(client):
    created = client.post("/expenses", json=make_expense()).json()
    resp = client.get(f"/expenses/{created['id']}")
    assert resp.status_code == 200
    assert resp.json()["title"] == "Coffee"


def test_get_missing_expense_404(client):
    resp = client.get("/expenses/999")
    assert resp.status_code == 404


def test_delete_expense(client):
    created = client.post("/expenses", json=make_expense()).json()
    resp = client.delete(f"/expenses/{created['id']}")
    assert resp.status_code == 204

    resp = client.get(f"/expenses/{created['id']}")
    assert resp.status_code == 404


def test_delete_missing_expense_404(client):
    resp = client.delete("/expenses/999")
    assert resp.status_code == 404


def test_totals_overall_and_by_category(client):
    client.post("/expenses", json=make_expense(title="Coffee", category="Food", amount=4.5))
    client.post("/expenses", json=make_expense(title="Lunch", category="Food", amount=10.5))
    client.post("/expenses", json=make_expense(title="Bus ticket", category="Transport", amount=2.0))

    resp = client.get("/expenses/totals/summary")
    assert resp.status_code == 200
    body = resp.json()
    assert body["overall_total"] == 17.0
    assert body["overall_count"] == 3

    by_cat = {c["category"]: (c["total"], c["count"]) for c in body["by_category"]}
    assert by_cat == {"Food": (15.0, 2), "Transport": (2.0, 1)}


def test_search_by_title(client):
    client.post("/expenses", json=make_expense(title="Morning Coffee"))
    client.post("/expenses", json=make_expense(title="Evening Coffee"))
    client.post("/expenses", json=make_expense(title="Bus ticket", category="Transport", amount=2.0))

    resp = client.get("/expenses/search", params={"q": "coffee"})
    assert resp.status_code == 200
    assert len(resp.json()) == 2


def test_data_persists_across_store_reload(tmp_path, monkeypatch):
    """The JSON file should survive a fresh ExpenseStore instantiation,
    simulating a server restart."""
    from src.storage import ExpenseStore
    from src.models import ExpenseCreate

    data_file = tmp_path / "persist.json"
    store1 = ExpenseStore(data_file)
    store1.add(ExpenseCreate(title="Coffee", amount=4.5, category="Food", date="2026-01-15"))

    store2 = ExpenseStore(data_file)  # simulate restart: reload from disk
    assert len(store2.list_all()) == 1
    assert store2.list_all()[0].title == "Coffee"
