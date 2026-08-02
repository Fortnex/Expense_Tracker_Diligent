"""Pydantic models for the Expense Tracker API."""
from datetime import date as date_type
from enum import Enum

from pydantic import BaseModel, Field, field_validator


class Category(str, Enum):
    """Fixed set of allowed expense categories. Using an enum (rather than a
    free-text string) means the API rejects garbage values like "string" or
    "test" at the validation layer, and Swagger UI renders this as a
    dropdown instead of an open text box."""

    FOOD = "Food"
    TRANSPORT = "Transport"
    ENTERTAINMENT = "Entertainment"
    UTILITIES = "Utilities"
    HEALTH = "Health"
    SHOPPING = "Shopping"
    BILLS = "Bills"
    EDUCATION = "Education"
    TRAVEL = "Travel"
    OTHER = "Other"


class ExpenseCreate(BaseModel):
    """Payload for creating a new expense. `id` is assigned by the server."""

    title: str = Field(..., min_length=1, max_length=200)
    amount: float = Field(..., gt=0, description="Must be a positive number")
    category: Category
    date: date_type

    @field_validator("title")
    @classmethod
    def not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("must not be blank")
        return v.strip()


class Expense(ExpenseCreate):
    """A stored expense, including its server-assigned id."""

    id: int


class CategoryTotal(BaseModel):
    category: str
    total: float
    count: int = Field(..., description="Number of expenses in this category")


class TotalsResponse(BaseModel):
    overall_total: float
    overall_count: int
    by_category: list[CategoryTotal]

