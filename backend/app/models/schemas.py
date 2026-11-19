from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator
from pydantic_core import PydanticCustomError

OrderStatus = Literal["PENDING", "CONFIRMED", "SHIPPED", "DELIVERED", "CANCELLED"]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RegisterRequest(Strict):
    name: str = Field(min_length=1, max_length=80)
    email: EmailStr
    password: str = Field(min_length=8, max_length=72)


class LoginRequest(Strict):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=72)


class ProductCreate(Strict):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)
    price: int = Field(gt=0, le=100_000_000, description="Minor currency units (cents)")
    stock_quantity: int = Field(ge=0, le=1_000_000)
    is_active: bool = True


class ProductUpdate(Strict):
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    description: Optional[str] = Field(default=None, max_length=2000)
    price: Optional[int] = Field(default=None, gt=0, le=100_000_000)
    stock_quantity: Optional[int] = Field(default=None, ge=0, le=1_000_000)
    stock_delta: Optional[int] = Field(default=None, ge=-1_000_000, le=1_000_000)
    is_active: Optional[bool] = None
    expected_version: Optional[int] = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _one_stock_mode(self):
        if self.stock_quantity is not None and self.stock_delta is not None:
            raise ValueError("Provide either stock_quantity or stock_delta, not both.")
        return self


class OrderItemIn(Strict):
    product_id: str = Field(min_length=1, max_length=64)
    quantity: int = Field(gt=0, le=100)


class LegacyCartItem(Strict):
    """Contract used only by legacy 0.9.x clients (adapter in routes/orders.py)."""
    id: str = Field(min_length=1, max_length=64)
    qty: int = Field(gt=0, le=100)


class OrderCreate(Strict):
    items: Optional[list[OrderItemIn]] = Field(default=None, max_length=50)
    cart: Optional[list[LegacyCartItem]] = Field(default=None, max_length=50)

    @model_validator(mode="after")
    def _exactly_one(self):
        if (self.items is None) == (self.cart is None):
            raise PydanticCustomError("items_required", "Provide `items` (or legacy `cart`).")
        return self


class OrderStatusUpdate(Strict):
    status: OrderStatus
    note: Optional[str] = Field(default=None, max_length=200)
    workflow_execution_id: Optional[str] = Field(default=None, pattern=r"^[A-Za-z0-9._:-]{1,64}$")
