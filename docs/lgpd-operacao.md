# Operação de retenção e privacidade

## Rotina diária

A aplicação fornece uma rotina única para aplicar os prazos fixos de retenção:

```text
poetry run task privacy-retention
```

O scheduler do ambiente deve executá-la uma vez por dia, preferencialmente em
uma janela de baixa utilização. O scheduler deve garantir que não existam duas
execuções concorrentes; a rotina é idempotente para reexecuções sequenciais,
mas a coordenação entre workers pertence ao ambiente de execução.

Exemplo de contrato para um scheduler baseado em cron:

```cron
0 2 * * * cd /srv/base-acesso-bibliotecario/backend && poetry run task privacy-retention
```

Em produção, o diretório, usuário, ambiente Python, banco e destino dos logs
devem ser definidos pelo responsável da infraestrutura. O comando não deve
receber dados pessoais por argumentos ou variáveis de ambiente adicionais.

## Resultado e alertas

O processo termina com código diferente de zero quando não consegue concluir a
transação. Em caso de falha, o scheduler deve alertar a equipe responsável e
manter a próxima execução habilitada. A saída contém somente métricas
agregadas, como quantidade de contas anonimizadas, vínculos históricos
removidos e registros eliminados; não contém nomes, usernames, CPF, tokens,
descrições de solicitações ou conteúdo de exportações.

Uma execução bem-sucedida deve ser registrada como operação técnica. O sistema
não deve considerar o log operacional como autorização para ampliar prazos ou
ignorar preservações legais.

## Preservação e segurança operacional

- empréstimos ativos não são tratados como históricos;
- preservações legais ou incidentes ativos devem bloquear a exclusão aplicável
  e registrar a justificativa técnica;
- a rotina não altera as regras de preservação definidas pela escola;
- o banco deve possuir backup e restauração testada conforme a política da
  infraestrutura;
- logs do scheduler devem seguir o mesmo prazo e as mesmas restrições de
  minimização aplicáveis aos registros técnicos.

## Incidentes, ordens e cadeia de custódia

Incidentes ou ordens de preservação devem ser registrados pela equipe
responsável antes da execução da rotina, identificando somente o escopo
técnico necessário, a escola envolvida, o motivo, o responsável e a data de
revisão. Enquanto a preservação estiver ativa, os registros correspondentes
ficam fora do expurgo. O encerramento deve registrar quem liberou a retenção e
a justificativa.

O acesso a logs, backups e evidências deve ser concedido por menor privilégio,
com autenticação individual e registro de leitura ou cópia. Evidências devem
ser copiadas para armazenamento controlado, com hash e cadeia de custódia; não
devem ser anexadas a solicitações, auditorias ou tickets com dados pessoais
desnecessários.

Ordens judiciais devem ser recebidas por canal institucional, validadas pelo
responsável designado pela escola e encaminhadas à equipe da plataforma com o
escopo e o prazo documentados. A equipe não deve ampliar a coleta além da
ordem nem executar eliminação irreversível sem a autorização registrada.

Quando houver incidente, classificar impacto, dados potencialmente afetados,
escolas envolvidas e urgência; conter o acesso, preservar evidências, corrigir
a causa e registrar a linha do tempo. A comunicação à escola, aos titulares e
à ANPD deve ser decidida pelo controlador e pelos responsáveis institucionais,
conforme a avaliação do caso.

## Checklist de implantação

1. Aplicar as migrações antes da primeira execução.
2. Configurar o scheduler diário com uma única instância concorrente.
3. Garantir que o ambiente tenha acesso ao banco e às chaves necessárias.
4. Configurar alerta para código de saída diferente de zero.
5. Executar uma vez em ambiente de homologação e conferir apenas as métricas.
6. Registrar o responsável operacional e a janela de execução da escola.
