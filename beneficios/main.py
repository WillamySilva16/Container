import os
import pyodbc
import pandas as pd
import gspread
import logging
import numpy as np

from google.oauth2.service_account import Credentials
from dotenv import load_dotenv
from datetime import datetime
from monitor import run_with_monitor  # noqa: E402

# ===============================
# LOGGING
# ===============================
logging.basicConfig(
    filename="beneficios.log",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)

# ===============================
# LOAD ENV
# ===============================
load_dotenv()
# ===============================
# CONFIGURAÇÕES GOOGLE
# ===============================
SERVICE_ACCOUNT_FILE = "/app/credentials.json"
SPREADSHEET_ID = "1lVgybWRYe_vctwA0a9JtDVH6tBYZVtfQyWNEocV0iT0"
WORKSHEET_NAME = "API BENEFICIOS"

# ===============================
# PLANILHA DE LOG
# ===============================
LOG_SPREADSHEET_ID = "1Q1LjFhquJs6U0NccUo1HJzqzQ9TNlYl-7cdOFYRIMTA"
LOG_WORKSHEET_NAME = "API-BENEFICIOS"

# ===============================
# CONEXÃO SQL SERVER
# ===============================

def conectar_bd():
    conn_str = (
        "DRIVER={ODBC Driver 17 for SQL Server};"
        f"SERVER={os.getenv('DB_SERVER')};"
        f"DATABASE={os.getenv('DB_DATABASE')};"
        f"UID={os.getenv('DB_USER')};"
        f"PWD={os.getenv('DB_PASSWORD')};"
        "TrustServerCertificate=yes;"
    )
    return pyodbc.connect(conn_str, timeout=30)

# ===============================
# QUERY
# ===============================

QUERY = """
SELECT DISTINCT
    FUNC.NUMCAD     AS RE,
    FUNC.NOMFUN     AS [NOME DO FUNCIONARIO],
    SIT.dessit      AS [DESCRIÇÃO DA SITUAÇÃO],
    EMP.apeemp      AS [NOME DA EMPRESA],
    FUNC.DATADM     AS [DATA DE ADMISSÃO],
    FUNC.CODBAN     AS [CODIGO DO BANCO],
    FUNC.CODAGE     AS AGENCIA,
    FUNC.CONBAN     AS CONTA,
    FUNC.DIGBAN     AS DIGITO,
    FUNC.TPCTBA     AS [TIPO DE CONTA]

FROM r034fun FUNC
INNER JOIN R030EMP EMP
    ON FUNC.NUMEMP = EMP.NUMEMP
LEFT JOIN R010SIT SIT
    ON FUNC.SITAFA = SIT.CODSIT
WHERE SIT.dessit IN (
    'Trabalhando',
    'Férias',
    'Auxílio Doença',
    'Atestado',
    'Licença Maternidade',
    'Licença Paternidade'
)
ORDER BY FUNC.NUMCAD;
"""

# ===============================
# GOOGLE SHEETS
# ===============================

def conectar_sheets():
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE,
        scopes=scopes
    )
    return gspread.authorize(creds)
# ===============================
# LOG NO SHEETS
# ===============================

def atualizar_log_sheets(status, mensagem):
    try:
        gc = conectar_sheets()
        sh = gc.open_by_key(LOG_SPREADSHEET_ID)

        try:
            ws = sh.worksheet(LOG_WORKSHEET_NAME)
        except gspread.exceptions.WorksheetNotFound:
            ws = sh.add_worksheet(title=LOG_WORKSHEET_NAME, rows=1000, cols=5)
            ws.update("A1", [["DATA", "STATUS", "MENSAGEM"]])

        agora = datetime.now().strftime("%d/%m/%Y %H:%M:%S")

        ws.append_row([agora, status, mensagem])

    except Exception as e:
        print("Erro ao atualizar planilha de log:", e)

# ===============================
# MAIN
# ===============================

def main():
    try:
        logging.info("Iniciando processo")

        # ================= SQL =================
        logging.info("Conectando no SQL Server")
        conn = conectar_bd()

        logging.info("Executando query")
        df = pd.read_sql(QUERY, conn)
        conn.close()

        logging.info(f"Registros retornados: {len(df)}")

        # ================= TRATAMENTO =================
        # Converter datetime para string
        for col in df.select_dtypes(include=["datetime64[ns]"]).columns:
            df[col] = df[col].dt.strftime("%d/%m/%Y")

        # Corrigir NaN / Inf
        df = df.replace([np.inf, -np.inf], "")
        df = df.fillna("")
        df = df.astype(str)

        # ================= GOOGLE SHEETS =================
        logging.info("Conectando no Google Sheets")
        gc = conectar_sheets()
        sh = gc.open_by_key(SPREADSHEET_ID)

        try:
            ws = sh.worksheet(WORKSHEET_NAME)
            logging.info("Aba encontrada no Sheets")
        except gspread.exceptions.WorksheetNotFound:
            logging.info("Aba não encontrada, criando nova")
            ws = sh.add_worksheet(title=WORKSHEET_NAME, rows=1000, cols=25)

        logging.info("Atualizando dados no Sheets")

        # 🔎 Quantas linhas existem hoje
        existing_rows = len(ws.get_all_values())

        # 🧹 Limpa somente os dados (mantém header)
        if existing_rows > 1:
            ws.batch_clear([f"B2:K{existing_rows}"])

        # ✍️ Atualiza dados a partir da linha 2
        ws.update("B2", df.values.tolist())
        logging.info("Job finalizado com sucesso")

        atualizar_log_sheets("SUCESSO", f"{len(df)} registros processados")

    except Exception:
        logging.exception("Erro fatal na execução do job")
        atualizar_log_sheets("ERRO", "Erro fatal na execução do job")
        raise

# ===============================
# EXECUÇÃO
# ===============================

PING_URL = "https://hc-ping.com/7b86705a-619f-4afd-9042-040164c95e2b"

if __name__ == "__main__":
    run_with_monitor(main, PING_URL)
