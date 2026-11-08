#!/bin/sh
set -e

echo "Aguardando conexão com o banco de dados..."
if [ -n "${WAIT_FOR_DATABASE_HOST:-}" ]; then
python -c "
import socket, time
s = socket.socket()
while True:
    try:
        s.connect(('$WAIT_FOR_DATABASE_HOST', ${WAIT_FOR_DATABASE_PORT:-5432}))
        s.close()
        break
    except Exception:
        time.sleep(1)
"
fi

echo "Banco pronto! Executando migrações..."
poetry run alembic upgrade head

if [ "${SEED_DEV:-0}" = "1" ]; then
  echo "Populando banco dev (escolas, usuarios, livros)..."
  poetry run python -m src.seeds.dev
elif [ "${SEED_SUPER_ADMIN:-0}" = "1" ]; then
  echo "Criando super admin..."
  poetry run python -m src.seeds.create_super_admin
fi

echo "Iniciando aplicação..."
if [ "${UVICORN_RELOAD:-0}" = "1" ]; then
  exec poetry run uvicorn --host 0.0.0.0 --port "${PORT:-8000}" src.app:app --reload
fi
exec poetry run uvicorn --host 0.0.0.0 --port "${PORT:-8000}" src.app:app --workers "${UVICORN_WORKERS:-1}"
