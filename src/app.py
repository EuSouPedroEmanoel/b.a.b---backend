from http import HTTPStatus

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi.errors import RateLimitExceeded
from starlette.responses import JSONResponse

from src.limiter import limiter
from src.routers import (
    auth,
    authors,
    books,
    copies,
    genres,
    loans,
    reservations,
    schools,
    users,
)
from src.schemas import Message

app = FastAPI()
app.state.limiter = limiter

# CORS para frontend Vite (W3C: permitir credenciais se necessário)
# allow_origin_regex libera localhost + IPs de rede (192.168.x.x, 10.x.x.x, 172.16-31.x.x) para acesso via Network do Vite
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        'http://localhost:5173',
        'http://127.0.0.1:5173',
    ],
    allow_origin_regex=r'http://(localhost|127\.0\.0\.1|192\.168\.\d+\.\d+|10\.\d+\.\d+\.\d+|172\.(1[6-9]|2\d|3[0-1])\.\d+\.\d+):5173',
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
app.include_router(genres.router)
app.include_router(authors.router)
app.include_router(schools.router)
app.include_router(loans.router)
app.include_router(reservations.router)


@app.get('/', status_code=HTTPStatus.OK, response_model=Message)
async def read_root():
    return {'message': 'olá mundo'}
