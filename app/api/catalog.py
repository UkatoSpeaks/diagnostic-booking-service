from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.db.session import get_db
from app.models.models import CentreTest, DiagnosticCentre, DiagnosticTest, User
from app.schemas.catalog import (
    CentreCreate,
    CentreResponse,
    CentreTestCreate,
    CentreTestResponse,
    TestCreate,
    TestResponse,
)

router = APIRouter(
    prefix="/catalog",
    tags=["Diagnostic Centres & Tests"],
)


@router.post(
    "/centres",
    response_model=CentreResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_centre(
    data: CentreCreate,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
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
    db: Session = Depends(get_db),
):
    return db.scalars(
        select(DiagnosticCentre)
    ).all()


@router.get(
    "/centres/{centre_id}",
    response_model=CentreResponse,
)
def get_centre(
    centre_id: int,
    db: Session = Depends(get_db),
):
    centre = db.get(DiagnosticCentre, centre_id)

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
    _: User = Depends(get_current_user),
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
    db: Session = Depends(get_db),
):
    return db.scalars(
        select(DiagnosticTest)
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
    _: User = Depends(get_current_user),
):
    centre = db.get(DiagnosticCentre, data.centre_id)
    test = db.get(DiagnosticTest, data.test_id)

    if not centre:
        raise HTTPException(404, "Diagnostic centre not found")

    if not test:
        raise HTTPException(404, "Diagnostic test not found")

    existing = db.scalar(
        select(CentreTest).where(
            CentreTest.centre_id == data.centre_id,
            CentreTest.test_id == data.test_id,
        )
    )

    if existing:
        raise HTTPException(
            status_code=409,
            detail="Test is already available at this centre",
        )

    centre_test = CentreTest(
        centre_id=data.centre_id,
        test_id=data.test_id,
        price=data.price,
    )

    db.add(centre_test)
    db.commit()
    db.refresh(centre_test)

    return centre_test