# Base de Acesso Bibliotecário — Backend

> Projeto acadêmico em desenvolvimento. Não é uma versão pronta para produção.

API REST para gerenciamento de acervo, usuários, empréstimos, reservas e recomendações bibliotecárias.

## Stack

- Python 3.13 e FastAPI
- SQLAlchemy assíncrono e PostgreSQL
- Alembic para migrações
- JWT para autenticação

## Desenvolvimento

```bash
poetry install
poetry run task run
```

Para subir API, banco e Adminer via Docker: `docker compose up --build`.

## Segredos

Configure `CPF_HMAC_SECRET`, `SECRET_KEY` e demais variáveis por ambiente. Nunca versione credenciais, tokens ou dados reais.
