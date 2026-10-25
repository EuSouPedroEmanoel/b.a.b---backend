# Inventário de tratamentos — LGPD-03

Este documento registra o inventário técnico atual da Base de Acesso
Bibliotecário. Ele descreve o que o sistema implementa; não substitui a
definição institucional das bases legais, dos prazos de retenção, dos
contratos ou do responsável pelo tratamento.

## Responsabilidade e escopo

| Item | Estado atual | Decisão necessária |
| --- | --- | --- |
| Controlador | Cada escola individualmente, no âmbito de sua utilização | Formalizar entidade, contrato e dados de contato |
| Operador do sistema | Plataforma que processa dados em nome da escola | Formalizar contrato, instruções e responsabilidades |
| Escopo de isolamento | Usuários, empréstimos, reservas, políticas e solicitações usam a escola quando aplicável | Validar a matriz de papéis com cada escola |
| Encarregado/canal | E-mail institucional configurável por escola | Cadastrar o endereço real de cada escola |
| Público infantojuvenil | O modelo possui alunos e turma; o sistema informa salvaguardas sem cadastrar responsáveis | A escola define o vínculo, a validação institucional, o melhor interesse e a participação do responsável conforme o caso |

## Categorias e finalidades

| Categoria | Dados tratados | Finalidade técnica | Escopo | Retenção |
| --- | --- | --- | --- | --- |
| Conta e identificação | Nome, username, identificador escolar, CPF mascarado/derivados protegidos, nascimento, turma, escola, papel e situação | Autenticação, autorização, identificação da conta e operação escolar | Própria escola; superadministrador conforme RBAC | Conta desativada: 6 meses |
| Autenticação e segurança | Hash de senha, versão de autenticação, tokens e registros técnicos | Autenticar, revogar sessões, recuperar acesso e prevenir abuso | Acesso restrito ao backend | A definir; segredos nunca são exportados |
| Circulação | Empréstimos, devoluções, cópia, datas, situação e operador | Operar a biblioteca, controlar disponibilidade e preservar integridade | Titular e equipe autorizada da escola | Identificável até 31 de dezembro; depois vínculo removido |
| Reservas | Reserva, livro/cópia, datas, fila e situação | Gerenciar fila e disponibilidade | Titular e equipe autorizada da escola | Canceladas: sem histórico identificável |
| Preferências | Favoritos e status de leitura | Personalizar a experiência do titular | Somente o titular | Removíveis na anonimização |
| Direitos do titular | Tipo, descrição limitada, situação, decisão, ator, timestamps, prazo de 15 dias e auditoria minimizada | Atender acesso, correção, portabilidade, bloqueio, eliminação e anonimização | Titular; processamento restrito à escola | 720 dias após encerramento |
| Auditoria administrativa | Ator, papel, escola, operação, entidade, resumo e justificativa | Segurança, prestação de contas e investigação | Administradores autorizados e mesma escola | 365 dias; não incluir senha, token, CPF completo ou exportação |

## Compartilhamentos e serviços externos

| Serviço | Dados/contexto potencialmente exposto | Uso | Decisões pendentes |
| --- | --- | --- | --- |
| Google Books | ISBN, título ou parâmetros de catálogo | Consulta de informações bibliográficas | Não enviar dados de conta ou escola; contrato/região ainda devem ser formalizados |
| BrasilAPI | Município/UF ou dados auxiliares de calendário | Apoio a calendário e dados públicos | Não enviar dados de conta; contrato/região ainda devem ser formalizados |
| Proxy de imagens | URL de capa e contexto de requisição | Exibir capas externas | Não enviar dados de conta; avaliar transferência e retenção |
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
- O sistema não cadastra nem autentica responsáveis legais; a escola mantém esse
  vínculo e valida solicitações de titulares menores conforme sua política.
- O produto não cria consentimento genérico e não transforma o acesso à
  biblioteca em confirmação de leitura ou consentimento.

## Decisões que desbloqueiam LGPD-03 e LGPD-04

1. Cadastrar o e-mail real de cada escola.
2. Formalizar operador, contratos e responsabilidades.
3. Aprovar a base legal por finalidade, especialmente para alunos menores.
4. Aprovar os terceiros autorizados e suas condições contratuais.
5. Definir responsáveis institucionais pelo atendimento das solicitações.
6. Confirmar se existe algum tratamento baseado em consentimento; se não
   existir, não criar uma camada genérica de consentimentos.

## Próximo incremento técnico

Os prazos aprovados são implementados como regras fixas no serviço diário de
retenção, com bloqueios de preservação, métricas não pessoais e testes de
expurgo. O scheduler do ambiente deve executar
`poetry run task privacy-retention` uma vez ao dia, com uma única execução
concorrente e alerta em caso de falha. O contrato operacional está em
[`docs/lgpd-operacao.md`](lgpd-operacao.md). O sistema não cria uma camada
genérica de consentimentos.
