from pydantic import BaseModel, ConfigDict, EmailStr, Field

from scr.models import BooksStates


class Message(BaseModel):
    message: str


# region - User
class UserSchema(BaseModel):
    username: str
    email: EmailStr
    password: str


class UserPublic(BaseModel):
    username: str
    email: EmailStr
    id: int

    model_config = ConfigDict(from_attributes=True)


class UserDB(UserSchema):
    id: int


class UserList(BaseModel):
    users: list[UserPublic]


# endregion
# region - Token
class Token(BaseModel):
    token_type: str
    access_token: str


# endregion
# region - Filters
class FilterPage(BaseModel):
    limit: int = Field(ge=1, default=10)
    offset: int = Field(ge=0, default=0)


class FilterBook(FilterPage):
    title: str | None = Field(None, min_length=3)
    description: str | None = None
    state: BooksStates | None = None


# endregion
# region - Books
class BooksSchema(BaseModel):
    title: str
    description: str
    state: BooksStates
    isbn: str | None = None
    internal_code: str | None = None


class BooksPublic(BooksSchema):
    id: int

    model_config = ConfigDict(from_attributes=True)


class BookList(BaseModel):
    books: list[BooksPublic]


class BookUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    state: BooksStates | None = None


# endregion
