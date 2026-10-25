# Procedimentos de incidentes e logs

## Logs de acesso

Os logs necessários à aplicação do Marco Civil devem registrar o mínimo
operacional (data e hora, origem técnica, recurso e resultado), sem senha,
cookie, token, CPF completo, conteúdo de exportação ou descrição livre de
solicitação. O acesso aos logs é restrito à equipe autorizada e deve ser
auditável.

O prazo operacional padrão é de seis meses quando aplicável à obrigação de
registro de acesso. Após esse prazo, os registros devem ser eliminados ou
anonimizados, salvo preservação legal ou investigação ativa. Logs de aplicação,
auditoria administrativa e backups possuem prazos próprios documentados no
inventário e não devem ser confundidos com registros de acesso.

## Resposta a incidentes

1. Detectar e abrir um registro com identificador técnico, horário e equipe
   responsável.
2. Classificar a ocorrência por disponibilidade, integridade,
   confidencialidade e possível impacto a menores.
3. Conter o acesso, revogar sessões ou credenciais expostas e preservar apenas
   os artefatos necessários à investigação.
4. Avaliar escolas, categorias de dados e titulares afetados, sem duplicar
   dados pessoais no registro do incidente.
5. Corrigir a causa, validar a recuperação e documentar a linha do tempo.
6. O controlador decide comunicações à escola, aos titulares e à ANPD,
   considerando risco, obrigação aplicável e orientação jurídica.

Incidentes ativos e ordens de preservação bloqueiam a retenção correspondente.
A liberação precisa indicar responsável, escopo e justificativa.

## Checklist de produção

- TLS termina em proxy reverso configurado e HTTPS é obrigatório.
- Cookies de sessão, secrets e chaves são fornecidos por secret manager e têm
  rotação definida.
- CORS, allowlist do proxy de imagens e hosts de integração estão revisados.
- Scheduler diário da retenção está ativo com apenas uma instância e alerta de
  falha.
- Backups e restauração foram testados e possuem controle de acesso.
- Migrações foram aplicadas e o estado do banco foi conferido.
- E-mail institucional e responsável de privacidade de cada escola foram
  cadastrados.
- O procedimento de ordem judicial e os contatos de incidente foram definidos.
- Adminer, reload e credenciais padrão estão bloqueados em produção.
