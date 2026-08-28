#!/bin/sh
set -e

echo "Aguardando conexão com o banco de dados..."
python -c "
import socket, time
s = socket.socket()
while True:
    try:
        s.connect(('float-tasks-db', 5432))
        s.close()
        break
    except Exception:
        time.sleep(1)
"

echo "Banco pronto! Executando migrações..."
poetry run alembic upgrade head

if [ "$SEED_DEV" = "1" ]; then
  echo "Populando banco dev (escolas, usuarios, livros)..."
  poetry run python -m src.seeds.dev || echo "Aviso: seed dev falhou"
else
  echo "Criando super admin..."
  poetry run python -m src.seeds.create_super_admin || echo "Aviso: seed super_admin falhou"
fi

echo "Iniciando aplicação..."
exec poetry run uvicorn --host 0.0.0.0 src.app:app --reload
