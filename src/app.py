from http import HTTPStatus

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi.errors import RateLimitExceeded
from starlette.responses import JSONResponse

from src.limiter import limiter
from src.routers import (
    auth,
    books,
    copies,
    loans,
    reservations,
    schools,
    users,
)
from src.schemas import Message

app = FastAPI()
app.state.limiter = limiter

# CORS para frontend Vite (W3C: permitir credenciais se necessário)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        'http://localhost:5173',
        'http://127.0.0.1:5173',
    ],
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
app.include_router(users.router)
app.include_router(books.router)
app.include_router(copies.router)
app.include_router(schools.router)
app.include_router(loans.router)
app.include_router(reservations.router)


@app.get('/', status_code=HTTPStatus.OK, response_model=Message)
async def read_root():
    return {'message': 'olá mundo'}
