from pydantic import BaseModel, EmailStr, Field, field_validator


class _EmailModel(BaseModel):
    email: EmailStr

    @field_validator("email")
    @classmethod
    def normalise_email(cls, value: str) -> str:
        return value.strip().lower()


class SignupRequest(_EmailModel):
    name: str = Field(min_length=2, max_length=100)
    password: str = Field(min_length=8, max_length=128)


class LoginRequest(_EmailModel):
    password: str = Field(min_length=1, max_length=128)


class UserResponse(BaseModel):
    id: int
    name: str
    email: str
    is_admin: bool

    model_config = {"from_attributes": True}


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"