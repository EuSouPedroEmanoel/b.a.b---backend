from http import HTTPStatus

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi.errors import RateLimitExceeded
from starlette.responses import JSONResponse

from src.limiter import limiter
from src.routers import (
    account_activation,
    administrative_activities,
    auth,
    authors,
    books,
    circulation_policies,
    copies,
    favorites,
    genres,
    library_calendar,
    loans,
    privacy,
    reading_statuses,
    reservations,
    schools,
    users,
)
from src.schemas import ApiStatus
from src.security import require_account
from src.settings import Settings

settings = Settings()
app = FastAPI()
app.state.limiter = limiter

allow_origin_regex = (
    r'http://(localhost|127\.0\.0\.1|192\.168\.\d+\.\d+|10\.\d+\.\d+\.\d+|172\.(1[6-9]|2\d|3[0-1])\.\d+\.\d+):5173'
    if settings.ENVIRONMENT.lower() != 'production'
    else None
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_origin_regex=allow_origin_regex,
    allow_credentials=True,
    allow_methods=['*'],
    allow_headers=['*'],
)


@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request, exc):
    return JSONResponse(
        status_code=HTTPStatus.TOO_MANY_REQUESTS,
        content={'detail': 'Rate limit exceeded. Try again later.'},
    )


app.include_router(auth.router)
app.include_router(privacy.router)
app.include_router(account_activation.router)
app.include_router(
    administrative_activities.router,
    dependencies=[Depends(require_account)],
)
app.include_router(users.router, dependencies=[Depends(require_account)])
app.include_router(books.router)
app.include_router(copies.router, dependencies=[Depends(require_account)])
app.include_router(
    circulation_policies.router, dependencies=[Depends(require_account)]
)
app.include_router(
    library_calendar.router, dependencies=[Depends(require_account)]
)
app.include_router(genres.router)
app.include_router(authors.router)
app.include_router(schools.router, dependencies=[Depends(require_account)])
app.include_router(loans.router, dependencies=[Depends(require_account)])
app.include_router(
    reservations.router, dependencies=[Depends(require_account)]
)
app.include_router(reading_statuses.router)
app.include_router(reading_statuses.book_router)
app.include_router(favorites.router)


@app.get('/', status_code=HTTPStatus.OK, response_model=ApiStatus)
async def read_root():
    return {
        'name': 'Base de Acesso Bibliotecário API',
        'status': 'online',
    }
