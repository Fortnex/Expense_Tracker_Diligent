"""Smart Expense Tracker API.

Endpoints:
    POST   /expenses                  Add an expense (category must be one of /categories)
    GET    /expenses                  List all expenses (optional ?category=)
    GET    /expenses/{id}             Get a single expense
    DELETE /expenses/{id}             Delete an expense
    GET    /expenses/totals/summary   Overall total/count and totals by category
    GET    /expenses/search?q=        Search expenses by title (bonus)
    GET    /categories                List the fixed set of valid categories
"""
from __future__ import annotations

import os

from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.openapi.utils import get_openapi

from .models import Expense, ExpenseCreate, TotalsResponse, CategoryTotal, Category
from .storage import ExpenseStore

app = FastAPI(
    title="Smart Expense Tracker API",
    description="A small REST API for tracking personal expenses.",
    version="1.0.0",
)


def custom_openapi():
    """Generate the OpenAPI schema, then strip the auto-added 422
    'Validation Error' block from every endpoint. FastAPI adds this by
    default to any route with parameters, but it clutters the docs for
    reviewers more than it helps."""
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(title=app.title, version=app.version, description=app.description, routes=app.routes)
    for path in schema.get("paths", {}).values():
        for method in path.values():
            method.get("responses", {}).pop("422", None)
    app.openapi_schema = schema
    return app.openapi_schema


app.openapi = custom_openapi

# Data file can be overridden (tests point this at a temp file so they don't
# clobber real data / each other).
DATA_FILE = os.environ.get("EXPENSES_DATA_FILE", "expenses.json")
store = ExpenseStore(DATA_FILE)


@app.get("/", tags=["meta"])
def root():
    return {"message": "Smart Expense Tracker API. See /docs for OpenAPI docs."}


@app.get("/categories", tags=["meta"])
def list_categories():
    """The fixed set of valid categories accepted when creating an expense."""
    return [c.value for c in Category]


@app.post("/expenses", response_model=Expense, status_code=201, tags=["expenses"])
def add_expense(payload: ExpenseCreate):
    """Add a new expense."""
    return store.add(payload)


@app.get("/expenses", response_model=list[Expense], tags=["expenses"])
def list_expenses(
    category: str = Query(
        default="",
        description="Filter by category",
        openapi_examples={"example": {"summary": "Food", "value": "Food"}},
    )
):
    """List all expenses, optionally filtered by category. Leave `category`
    blank to get every expense."""
    if category.strip():
        return store.filter_by_category(category)
    return store.list_all()


@app.get("/expenses/search", response_model=list[Expense], tags=["expenses"])
def search_expenses(q: str = Query(..., min_length=1, description="Search term for title")):
    """Bonus: search expenses whose title contains the query (case-insensitive)."""
    term = q.strip().lower()
    return [e for e in store.list_all() if term in e.title.lower()]


@app.get("/expenses/totals/summary", response_model=TotalsResponse, tags=["expenses"])
def get_totals():
    """Overall total/count, plus a total and count broken down by category."""
    by_cat = store.totals_by_category()
    return TotalsResponse(
        overall_total=store.total(),
        overall_count=len(store.list_all()),
        by_category=[
            CategoryTotal(category=k, total=v["total"], count=v["count"])
            for k, v in sorted(by_cat.items())
        ],
    )


@app.get("/expenses/{expense_id}", response_model=Expense, tags=["expenses"])
def get_expense(expense_id: int):
    expense = store.get(expense_id)
    if expense is None:
        raise HTTPException(status_code=404, detail=f"Expense {expense_id} not found")
    return expense


@app.delete("/expenses/{expense_id}", status_code=204, tags=["expenses"])
def delete_expense(expense_id: int):
    deleted = store.delete(expense_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Expense {expense_id} not found")
    # A 204 response must not include a body, so return an empty Response
    # rather than JSONResponse(content=None) (which sends a 4-byte "null"
    # body and crashes the ASGI server on the Content-Length mismatch).
    return Response(status_code=204)
