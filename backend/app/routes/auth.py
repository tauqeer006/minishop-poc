from fastapi import APIRouter, Depends

from app.dependencies import get_current_user
from app.models.schemas import LoginRequest, RegisterRequest
from app.observability.error_handlers import ok
from app.services import auth_service

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post("/register")
async def register(body: RegisterRequest):
    return ok(await auth_service.register(body.name, body.email, body.password), status_code=201)


@router.post("/login")
async def login(body: LoginRequest):
    return ok(await auth_service.login(body.email, body.password))


@router.get("/me")
async def me(user: dict = Depends(get_current_user)):
    return ok({k: user[k] for k in ("_id", "name", "email", "role", "created_at")})
