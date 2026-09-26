from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload, selectinload

from app.core.security import require_admin
from app.db.session import get_db
from app.models.models import CentreTest, DiagnosticCentre, DiagnosticTest, User
from app.schemas.catalog import (
    CentreCreate,
    CentreResponse,
    CentreTestCreate,
    CentreTestPriceUpdate,
    CentreTestResponse,
    TestCreate,
    TestResponse,
)

router = APIRouter(
    prefix="/catalog",
    tags=["Diagnostic Centres & Tests"],
)

# Read endpoints are public; every write requires an admin user.

centre_with_tests = selectinload(DiagnosticCentre.tests).options(
    joinedload(CentreTest.test)
)


@router.post(
    "/centres",
    response_model=CentreResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_centre(
    data: CentreCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    centre = DiagnosticCentre(
        name=data.name,
        location=data.location,
    )

    db.add(centre)
    db.commit()
    db.refresh(centre)

    return centre


@router.get(
    "/centres",
    response_model=list[CentreResponse],
)
def list_centres(
    location: str | None = Query(default=None, description="Case-insensitive match"),
    test_id: int | None = Query(default=None, description="Only centres offering this test"),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    query = select(DiagnosticCentre).options(centre_with_tests)

    if location:
        query = query.where(DiagnosticCentre.location.ilike(f"%{location}%"))

    if test_id is not None:
        query = query.where(
            DiagnosticCentre.tests.any(CentreTest.test_id == test_id)
        )

    return db.scalars(
        query.order_by(DiagnosticCentre.id).limit(limit).offset(offset)
    ).all()


@router.get(
    "/centres/{centre_id}",
    response_model=CentreResponse,
)
def get_centre(
    centre_id: int,
    db: Session = Depends(get_db),
):
    centre = db.scalar(
        select(DiagnosticCentre)
        .options(centre_with_tests)
        .where(DiagnosticCentre.id == centre_id)
    )

    if not centre:
        raise HTTPException(
            status_code=404,
            detail="Diagnostic centre not found",
        )

    return centre


@router.post(
    "/tests",
    response_model=TestResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_test(
    data: TestCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    test = DiagnosticTest(
        name=data.name,
        description=data.description,
    )

    db.add(test)
    db.commit()
    db.refresh(test)

    return test


@router.get(
    "/tests",
    response_model=list[TestResponse],
)
def list_tests(
    search: str | None = Query(default=None, description="Case-insensitive name match"),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    query = select(DiagnosticTest)

    if search:
        query = query.where(DiagnosticTest.name.ilike(f"%{search}%"))

    return db.scalars(
        query.order_by(DiagnosticTest.id).limit(limit).offset(offset)
    ).all()


@router.get(
    "/tests/{test_id}",
    response_model=TestResponse,
)
def get_test(
    test_id: int,
    db: Session = Depends(get_db),
):
    test = db.get(DiagnosticTest, test_id)

    if not test:
        raise HTTPException(
            status_code=404,
            detail="Diagnostic test not found",
        )

    return test


@router.post(
    "/centre-tests",
    response_model=CentreTestResponse,
    status_code=status.HTTP_201_CREATED,
)
def add_test_to_centre(
    data: CentreTestCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    if not db.get(DiagnosticCentre, data.centre_id):
        raise HTTPException(404, "Diagnostic centre not found")

    if not db.get(DiagnosticTest, data.test_id):
        raise HTTPException(404, "Diagnostic test not found")

    centre_test = CentreTest(
        centre_id=data.centre_id,
        test_id=data.test_id,
        price=data.price,
    )

    db.add(centre_test)

    try:
        db.commit()
    except IntegrityError:
        # uq_centre_test also protects against concurrent duplicates
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Test is already available at this centre",
        )

    db.refresh(centre_test)

    return centre_test


@router.patch(
    "/centre-tests/{centre_test_id}",
    response_model=CentreTestResponse,
)
def update_centre_test_price(
    centre_test_id: int,
    data: CentreTestPriceUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Existing bookings keep the price they were booked at."""
    centre_test = db.get(CentreTest, centre_test_id)

    if not centre_test:
        raise HTTPException(404, "Centre test not found")

    centre_test.price = data.price
    db.commit()
    db.refresh(centre_test)

    return centre_test


@router.delete(
    "/centre-tests/{centre_test_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def remove_test_from_centre(
    centre_test_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    centre_test = db.get(CentreTest, centre_test_id)

    if not centre_test:
        raise HTTPException(404, "Centre test not found")

    db.delete(centre_test)
    db.commit()

    return Response(status_code=status.HTTP_204_NO_CONTENT)
