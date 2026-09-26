from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.core.security import get_current_user
from app.core.security import create_access_token, hash_password, verify_password
from app.core.rate_limit import limiter
from app.db.session import get_db
from app.models.models import User
from app.core.config import settings
from app.schemas.auth import (
    LoginRequest,
    SignupRequest,
    TokenResponse,
    UserResponse,
)


router = APIRouter(
    prefix="/auth",
    tags=["Authentication"],
)


@router.post(
    "/signup",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
)
@limiter.limit("10/minute")
def signup(
    request: Request,
    data: SignupRequest,
    db: Session = Depends(get_db),
):
    existing_user = db.scalar(
        select(User).where(User.email == data.email)
    )

    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )

    user = User(
        name=data.name,
        email=data.email,
        password_hash=hash_password(data.password),
        is_admin=data.email in settings.admin_emails,
    )

    db.add(user)

    try:
        db.commit()
    except IntegrityError:
        # Concurrent signup with the same email
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )

    db.refresh(user)

    token = create_access_token(user.id)

    return TokenResponse(
        access_token=token,
    )


@router.post(
    "/login",
    response_model=TokenResponse,
)
@limiter.limit("10/minute")
def login(
    request: Request,
    data: LoginRequest,
    db: Session = Depends(get_db),
):
    user = db.scalar(
        select(User).where(User.email == data.email)
    )

    if not user or not verify_password(
        data.password,
        user.password_hash,
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    token = create_access_token(user.id)

    return TokenResponse(
        access_token=token,
    )


@router.get("/me", response_model=UserResponse)
def get_me(current_user: User = Depends(get_current_user)):
    return current_user
