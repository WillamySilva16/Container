# APIs Docker - BD para Google Sheets

Projeto com varios jobs Python que leem dados dos bancos HCM/HK e atualizam abas no Google Sheets.

## Como ficou o Docker

O `docker-compose.yml` foi configurado para subir os containers dos jobs sem executar os scripts automaticamente.

Por padrao, cada container fica ocioso com:

```bash
tail -f /dev/null
```

Isso evita que todos os jobs batam no banco e no Google Sheets ao mesmo tempo quando voce roda `docker compose up -d`.

## Pre-requisitos

- Docker Desktop instalado
- `credentials.json` na raiz do projeto
- `envs/hcm.env` preenchido
- `envs/hk.env` preenchido

Os arquivos de credenciais ficam fora da imagem por causa do `.dockerignore` e sao montados no container via volume.

## Subir os containers sem rodar jobs

```bash
docker compose build
docker compose up -d
docker compose ps
```

Nesse modo, nenhum `main.py` roda automaticamente.

## Rodar um job manualmente

Use `docker compose exec <servico> python main.py`.

Exemplos:

```bash
docker compose exec treinamento python main.py
docker compose exec admissao_hk python main.py
docker compose exec folha_hcm python main.py
```

## Ativar os agendamentos

O Ofelia fica em um profile separado chamado `scheduler`.

Para ativar:

```bash
docker compose --profile scheduler up -d
docker compose logs -f ofelia
```

Para desligar o agendador sem derrubar os jobs:

```bash
docker compose stop ofelia
```

## Servicos configurados

HCM:

- `admissao_hcm`
- `exportar_folha_hcm`
- `folha_hcm`
- `reembolso_hcm`
- `sesmt_hcm`

HK:

- `admissao_hk`
- `colaboradores_hk`
- `beneficios`
- `turnover_hk`
- `juridico`
- `sesmt_hk`
- `faltas_tt`
- `excedente`
- `descobertos`
- `sobra`
- `treinamento`
- `exportar_faltas_hk`
- `turnover`

## Comandos uteis

```bash
# Ver logs de um container
docker compose logs -f treinamento

# Reiniciar um container sem rodar o job
docker compose restart treinamento

# Parar tudo
docker compose down

# Validar o compose
docker compose config --services
```

## Seguranca

- Nao commite `credentials.json`.
- Nao commite arquivos dentro de `envs/`.
- Evite publicar saida completa de `docker compose config`, porque ela pode expandir variaveis do `env_file`.
