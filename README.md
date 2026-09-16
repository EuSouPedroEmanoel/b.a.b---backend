# Base de Acesso Bibliotecário — Backend

> Projeto acadêmico em desenvolvimento. Não é uma versão pronta para produção.

API REST que concentra as regras de negócio da Base de Acesso Bibliotecário. O sistema permite que escolas mantenham um catálogo de livros e exemplares, cadastrem sua comunidade e controlem todo o ciclo de circulação.

Bibliotecários e administradores gerenciam autores, gêneros, livros, cópias físicas, usuários, calendários e políticas de empréstimo. Alunos e professores consultam o acervo, visualizam disponibilidade, fazem reservas e acompanham seus empréstimos. O backend registra retiradas e devoluções, calcula prazos, aplica limites por papel e escola e fornece recomendações baseadas no histórico de circulação.

Cada escola funciona como um tenant lógico: consultas e alterações devem respeitar `school_id`, enquanto operações realmente globais ficam reservadas ao superadministrador. A API também fornece autenticação JWT, renovação de sessão, validação de payloads e respostas padronizadas para que o frontend possa oferecer uma experiência segura e consistente.

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

## Licença

Distribuído sob a [licença MIT](LICENSE).

## Fluxos principais

1. O usuário autentica com suas credenciais.
2. A API valida assinatura, expiração e tipo do token.
3. O papel e a escola do usuário são carregados em cada requisição protegida.
4. Listagens aplicam filtros de tenant antes de consultar o banco.
5. Schemas Pydantic validam e normalizam os dados recebidos.
6. Operações de catálogo preservam autores, gêneros e exemplares relacionados.
7. Uma reserva é associada ao usuário e ao exemplar ou livro solicitado.
8. Um empréstimo registra retirada, prazo, devolução e status.
9. Políticas da escola determinam limites e períodos de circulação.
10. Recomendações usam sinais de interesse e disponibilidade do catálogo.

## Papéis

- `student`: consulta, reserva e acompanha os próprios empréstimos.
- `teacher`: utiliza o acervo e acompanha seus empréstimos.
- `librarian`: opera a circulação conforme as permissões da escola.
- `school_admin`: administra configurações e contas da escola.
- `super_admin`: executa operações globais de manutenção.

## Banco de dados

As migrações versionadas devem ser aplicadas antes de iniciar a API. Em desenvolvimento, o compose cria um PostgreSQL isolado; em produção, use banco gerenciado, backups e rotação de credenciais.

## Observabilidade

Erros de validação retornam respostas HTTP estruturadas. Logs devem conter contexto operacional suficiente para diagnóstico, sem tokens, senhas, CPF ou outros dados pessoais.

## Contribuição

Abra uma issue descrevendo o contexto, reproduza o problema com dados fictícios e proponha testes. Alterações de autorização devem incluir casos permitidos e negados.
