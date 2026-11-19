from fastapi import APIRouter, Depends, Query

from app.dependencies import get_optional_user, require_admin
from app.models.schemas import ProductCreate, ProductUpdate
from app.observability.error_handlers import AppError, ok
from app.services import product_service
from app.utils.retry import retry_idempotent

router = APIRouter(prefix="/api/v1/products", tags=["products"])


@router.get("")
async def list_products(
    search: str | None = Query(default=None, max_length=100),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    include_inactive: bool = False,
    user: dict | None = Depends(get_optional_user),
):
    is_admin = bool(user and user["role"] == "admin")
    # Idempotent read -> bounded retry with jitter (APP-R-030)
    result = await retry_idempotent(
        lambda: product_service.list_products(search, page, page_size, include_inactive and is_admin),
        operation="list_products",
    )
    return ok(result)


@router.get("/{product_id}")
async def get_product(product_id: str, user: dict | None = Depends(get_optional_user)):
    is_admin = bool(user and user["role"] == "admin")
    doc = await retry_idempotent(
        lambda: product_service.get_product(product_id, include_inactive=is_admin),
        operation="get_product",
    )
    return ok(doc)


@router.post("")
async def create_product(body: ProductCreate, admin: dict = Depends(require_admin)):
    return ok(await product_service.create_product(body.model_dump(), admin["_id"]), status_code=201)


@router.patch("/{product_id}")
async def update_product(product_id: str, body: ProductUpdate, admin: dict = Depends(require_admin)):
    changes = body.model_dump(exclude_unset=True, exclude={"expected_version", "stock_delta"})
    if not changes and body.stock_delta is None:
        raise AppError(400, "REQUEST_SCHEMA_INVALID", "No fields to update.")
    doc = await product_service.update_product(
        product_id, changes, body.expected_version, body.stock_delta, admin["_id"])
    return ok(doc)
