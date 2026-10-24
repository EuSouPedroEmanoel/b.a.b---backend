# Inventário de tratamentos — LGPD-03

Este documento registra o inventário técnico atual da Base de Acesso
Bibliotecário. Ele descreve o que o sistema implementa; não substitui a
definição institucional das bases legais, dos prazos de retenção, dos
contratos ou do responsável pelo tratamento.

## Responsabilidade e escopo

| Item | Estado atual | Decisão necessária |
| --- | --- | --- |
| Controlador | Escola responsável pelo uso da biblioteca, conforme o contexto da conta | Identificar formalmente a entidade e seus dados de contato |
| Operador do sistema | Projeto/aplicação que processa dados em nome da escola | Formalizar contrato, instruções e responsabilidades |
| Escopo de isolamento | Usuários, empréstimos, reservas, políticas e solicitações usam a escola quando aplicável | Validar a matriz de papéis com cada escola |
| Encarregado/canal | Não definido no código | Publicar nome ou canal oficial |
| Público infantojuvenil | O modelo possui alunos e turma | Definir salvaguardas e responsável legal conforme o caso |

## Categorias e finalidades

| Categoria | Dados tratados | Finalidade técnica | Escopo | Retenção |
| --- | --- | --- | --- | --- |
| Conta e identificação | Nome, username, CPF mascarado/derivados protegidos, nascimento, turma, escola, papel e situação | Autenticação, autorização, identificação da conta e operação escolar | Própria escola; superadministrador conforme RBAC | A definir institucionalmente |
| Autenticação e segurança | Hash de senha, versão de autenticação, tokens e registros técnicos | Autenticar, revogar sessões, recuperar acesso e prevenir abuso | Acesso restrito ao backend | A definir; segredos nunca são exportados |
| Circulação | Empréstimos, devoluções, cópia, datas, situação e operador | Operar a biblioteca, controlar disponibilidade e preservar integridade | Titular e equipe autorizada da escola | A definir; empréstimo ativo bloqueia anonimização |
| Reservas | Reserva, livro/cópia, datas, fila e situação | Gerenciar fila e disponibilidade | Titular e equipe autorizada da escola | A definir; reservas não necessárias podem ser canceladas |
| Preferências | Favoritos e status de leitura | Personalizar a experiência do titular | Somente o titular | Removíveis na anonimização |
| Direitos do titular | Tipo, descrição limitada, situação, decisão, ator, timestamps e auditoria minimizada | Atender acesso, correção, portabilidade, bloqueio, eliminação e anonimização | Titular; processamento restrito à escola | A definir conforme obrigação de prestação de contas |
| Auditoria administrativa | Ator, papel, escola, operação, entidade, resumo e justificativa | Segurança, prestação de contas e investigação | Administradores autorizados e mesma escola | A definir; não incluir senha, token, CPF completo ou exportação |

## Compartilhamentos e serviços externos

| Serviço | Dados/contexto potencialmente exposto | Uso | Decisões pendentes |
| --- | --- | --- | --- |
| Google Books | ISBN, título ou parâmetros de catálogo | Consulta de informações bibliográficas | Confirmar operador, região, contrato, minimização e retenção |
| BrasilAPI | Município/UF ou dados auxiliares de calendário | Apoio a calendário e dados públicos | Confirmar necessidade, operador e política de chamadas |
| Proxy de imagens | URL de capa e contexto de requisição | Exibir capas externas | Avaliar remoção, proxy próprio, transferência e retenção |
| PostgreSQL/Adminer | Dados persistidos e administração local | Armazenamento e suporte operacional | Restringir produção, remover credenciais padrão e definir acesso |

Nenhum compartilhamento deve ser interpretado como consentimento genérico. A
finalidade, a base legal e as responsabilidades precisam ser aprovadas pela
escola antes do uso com dados reais.

## Regras técnicas já implementadas

- Consultas administrativas são limitadas por `school_id`, papel ou capacidade.
- A central do titular retorna somente dados próprios e CPF mascarado.
- Exportações exigem senha atual e não incluem senha, hashes, tokens, HMAC ou
  dados de terceiros.
- Anonimização revoga autenticação, remove identificadores diretos e preserva
  somente históricos necessários à integridade operacional.
- Empréstimos ativos impedem a conclusão automática da anonimização.
- Solicitações, exportações, decisões e alterações de política geram auditoria
  minimizada.
- O aviso público é informativo e não registra visualização como consentimento.

## Decisões que desbloqueiam LGPD-03 e LGPD-04

1. Identificar controlador, operador, encarregado e canal oficial.
2. Aprovar a base legal por finalidade, especialmente para alunos menores.
3. Definir prazos de retenção por categoria e exceções de preservação.
4. Aprovar os terceiros autorizados e suas condições contratuais.
5. Definir prazos operacionais e responsáveis pelo atendimento das solicitações.
6. Confirmar se existe algum tratamento baseado em consentimento; se não
   existir, não criar uma camada genérica de consentimentos.

## Próximo incremento técnico

Após as decisões acima, implementar a matriz de retenção como configuração
versionada, com job de expurgo/anonimização, bloqueios de preservação, métricas
de atraso e testes de expurgo. Até que os prazos sejam aprovados, o sistema não
deve inventar períodos nem executar exclusões automáticas por suposição.
