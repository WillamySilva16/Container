# 🐳 APIs Docker — BD → Google Sheets

## Estrutura do projeto

```
projeto/
├── Dockerfile                  # Imagem base Python compartilhada
├── docker-compose.yml          # Todos os serviços + Ofelia
├── ofelia.ini                  # Documentação dos agendamentos
├── requirements.txt            # Dependências Python
├── .gitignore                  # Protege credenciais
│
├── credentials.json            # ⚠️ Service Account GCP única (NÃO versionar)
│
├── envs/
│   ├── hcm.env                 # Credenciais BD VETORH
│   └── hk.env                  # Credenciais BD SAR2G_RS_PRD
│
├── shared/
│   └── monitor.py              # Módulo compartilhado por todas as APIs
│
├── admissao_hcm/
│   └── admissaocm.py
├── admissao_hk/
│   └── admissao_HK.py
├── colaboradores_hk/
│   └── colaboradores.py
├── beneficios/
│   └── beneficios.py
├── turnover/
│   └── turnover.py
├── juridico/
│   └── juridico.py
├── sesmt/
│   └── sesmt.py
├── faltas_tt/
│   └── faltastt.py
├── excedente/
│   └── excedente.py
├── descobertos/
│   └── descobertos.py
├── sobra/
│   └── sobra.py
├── treinamento/
│   └── treinamento.py
├── exportar_folha_hcm/
│   └── exportar_folha_hcm.py
└── exportar_faltas_hk/
    └── exportar_faltas_hk.py
```

---

## Pré-requisitos

- Docker Desktop instalado na VM
- `credentials.json` na raiz (service account única com acesso a todas as planilhas)
- `envs/hcm.env` e `envs/hk.env` preenchidos

---

## Setup inicial — Service Account GCP

1. No GCP, crie uma nova service account (ex: `apis-docker`)
2. Dê permissão de **Editor** no projeto
3. Gere e baixe a chave `.json`
4. Renomeie para `credentials.json` e coloque na raiz do projeto
5. Em cada planilha do Google Sheets → **Compartilhar** → cole o e-mail da service account

---

## Como subir tudo

```bash
# 1. Build das imagens (primeira vez ou após mudar requirements.txt)
docker compose build

# 2. Subir todos os serviços em background
docker compose up -d

# 3. Verificar se está tudo rodando
docker compose ps
```

---

## Comandos úteis

```bash
# Ver logs de um serviço específico
docker compose logs -f admissao_hk

# Ver logs do Ofelia (agendador)
docker compose logs -f ofelia

# Parar tudo
docker compose down

# Reiniciar um serviço específico
docker compose restart admissao_hk

# Rodar um job manualmente (sem esperar o schedule)
docker compose exec admissao_hk python admissao_HK.py
```

---

## Agendamentos configurados

| Serviço              | Intervalo  | BD   |
|----------------------|------------|------|
| admissao_hcm         | 30 min     | HCM  |
| exportar_folha_hcm   | 5 min      | HCM  |
| admissao_hk          | 30 min     | HK   |
| colaboradores_hk     | 30 min     | HK   |
| exportar_faltas_hk   | 10 min     | HK   |
| faltas_tt            | 30 min     | HK   |
| descobertos          | 30 min     | HK   |
| beneficios           | 1 hora     | HK   |
| turnover             | 1 hora     | HK   |
| juridico_hk          | 1 hora     | HK   |
| sesmt                | 1 hora     | HK   |
| excedente            | 1 hora     | HK   |
| sobra                | 1 hora     | HK   |
| treinamento          | 1 hora     | HK   |

---

## Ajuste nos scripts Python

Após mover os arquivos pro Docker, o import do `monitor.py` muda de:

```python
# ANTES (caminho relativo no Windows)
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from monitor import run_with_monitor

# DEPOIS (sem sys.path.append — PYTHONPATH já aponta pra /shared)
from monitor import run_with_monitor
```

Também o `SERVICE_ACCOUNT_FILE` muda de:
```python
# ANTES
SERVICE_ACCOUNT_FILE = "monitoramento-api-admissao.json"

# DEPOIS
SERVICE_ACCOUNT_FILE = "/app/credentials.json"
```

---

## ⚠️ Segurança

- `envs/` e `credentials.json` estão no `.gitignore`
- **Nunca** commite credenciais no repositório
