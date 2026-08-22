from http import HTTPStatus

from fastapi import FastAPI

from scr.routers import auth, books, copies, users
from scr.schemas import Message

app = FastAPI()
app.include_router(auth.router)
app.include_router(users.router)
app.include_router(books.router)
app.include_router(copies.router)


@app.get('/', status_code=HTTPStatus.OK, response_model=Message)
async def read_root():
    return {'message': 'olá mundo'}
