from decimal import Decimal

from pydantic import BaseModel, Field


class CentreCreate(BaseModel):
    name: str = Field(min_length=2, max_length=150)
    location: str = Field(min_length=2)


class CentreResponse(BaseModel):
    id: int
    name: str
    location: str

    model_config = {"from_attributes": True}


class TestCreate(BaseModel):
    name: str = Field(min_length=2, max_length=150)
    description: str | None = None


class TestResponse(BaseModel):
    id: int
    name: str
    description: str | None

    model_config = {"from_attributes": True}


class CentreTestCreate(BaseModel):
    centre_id: int
    test_id: int
    price: Decimal = Field(gt=0)


class CentreTestResponse(BaseModel):
    id: int
    centre_id: int
    test_id: int
    price: Decimal

    model_config = {"from_attributes": True}