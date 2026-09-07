# Configuração do segredo de CPF

`CPF_HMAC_SECRET` é obrigatório e deve ser configurado no ambiente da
aplicação. Gere um valor aleatório com:

```bash
python -c "import secrets; print(secrets.token_urlsafe(64))"
```

Guarde o valor em um secret da infraestrutura e mantenha-o estável. Nunca o
registre no Git, no Dockerfile ou em logs.
