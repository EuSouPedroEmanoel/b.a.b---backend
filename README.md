# Base de Acesso Bibliotecário — Backend

> Projeto acadêmico em desenvolvimento. Não é uma versão pronta para produção.

API REST responsável pelas regras de negócio da Base de Acesso Bibliotecário: catálogo, exemplares, usuários, empréstimos, reservas, calendários, políticas e recomendações.

## Arquitetura

- **API:** FastAPI com documentação OpenAPI em `/docs`.
- **Persistência:** PostgreSQL acessado por SQLAlchemy assíncrono.
- **Migrações:** Alembic em `migrations/`.
- **Segurança:** JWT (access/refresh), hashes Argon2 e RBAC por escola.
- **Organização:** rotas em `src/routers/`, modelos em `src/models/`, schemas em `src/schemas.py`.

## Requisitos

Python 3.14+, Poetry e PostgreSQL (ou Docker).

## Execução local

```bash
poetry install
poetry run task run
```

Com infraestrutura Docker:

```bash
docker compose up --build
```

## Qualidade

```bash
poetry run task lint
poetry run task test
```

## Configuração e segurança

Defina `SECRET_KEY`, `CPF_HMAC_SECRET`, credenciais do banco e demais variáveis por ambiente. Nunca versione segredos, tokens ou dados reais. Seeds de desenvolvimento devem ser usados apenas em ambiente isolado.

## Auditoria

O relatório de auditoria está em `../docs/security-audit/`. Achados e correções acompanhados nas [issues de segurança](https://github.com/EuSouPedroEmanoel/b.a.b---backend/issues).

## Licença

Distribuído sob a [licença MIT](LICENSE).
