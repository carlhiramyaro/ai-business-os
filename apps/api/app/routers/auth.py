from fastapi import APIRouter, Depends

from app.dependencies import get_current_user
from app.models import User
from app.schemas.auth import UserResponse

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.get("/me", response_model=UserResponse)
def me(current_user: User = Depends(get_current_user)):
    return current_user
