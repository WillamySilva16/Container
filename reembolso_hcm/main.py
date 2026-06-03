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
    filename="reembolso_folhahcm.log",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)

# ===============================
# LOAD ENV (POR SCRIPT)
# ===============================
load_dotenv()
# ===============================
# CONFIGURAÇÕES GOOGLE
# ===============================
SERVICE_ACCOUNT_FILE = "/app/credentials.json"
SPREADSHEET_ID = "1vY7o5j5_DJkd7l1JtROH2mo7XpVm8XfGDoO_-QOppKs"
WORKSHEET_NAME = "API-REEMBOLSO"

# ===============================
# PLANILHA DE LOG
# ===============================
LOG_SPREADSHEET_ID = "1Q1LjFhquJs6U0NccUo1HJzqzQ9TNlYl-7cdOFYRIMTA"
LOG_WORKSHEET_NAME = "API-REEMBOLSO-HCM"

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
    FUNC.NUMEMP     AS EMPRESA,
    EMP.apeemp      AS [NOME DA EMPRESA],
    FUNC.NUMCAD     AS RE,
    FUNC.NOMFUN     AS [NOME DO FUNCIONARIO],
    SAL.salbas      AS [SALARIO BASE],
    FUNC.DATADM     AS [DATA DE ADMISSÃO],
    FUNC.SITAFA     AS [CODIGO DA SITUACAO],
    SIT.dessit      AS [DESCRICAO DA SITUACAO],
    FUNC.CODCAR     AS [CODIGO DO CARGO],
    CAR.titred      AS CARGO,
    FUNC.TIPSEX     AS SEXO,
    FUNC.DATNAS     AS [DATA DE NASCIMENTO],
    FUNC.NUMCPF     AS CPF,
    FUNC.CODBAN     AS [CODIGO DO BANCO],
    BAN.nomban      AS [NOME DO BANCO],
    FUNC.CODAGE     AS AGENCIA,
    FUNC.CONBAN     AS CONTA,
    FUNC.DIGBAN     AS DIGITO,
    FUNC.TPCTBA     AS [TIPO DE CONTA],
    FUNC.VALSAL     AS [ULTIMO SALARIO]
FROM r034fun FUNC
INNER JOIN R030EMP EMP
    ON FUNC.NUMEMP = EMP.NUMEMP
LEFT JOIN R046IDP SAL
    ON FUNC.NUMEMP = SAL.NUMEMP
   AND FUNC.NUMCAD = SAL.NUMCAD
LEFT JOIN R024CAR CAR
    ON FUNC.CODCAR = CAR.CODCAR
LEFT JOIN R010SIT SIT
    ON FUNC.SITAFA = SIT.CODSIT
LEFT JOIN R012BAN BAN
    ON FUNC.CODBAN = BAN.CODBAN
WHERE FUNC.NUMEMP IN (3, 4, 5, 6, 12)
ORDER BY
    FUNC.NUMEMP,
    FUNC.NUMCAD;
"""

# ===============================
# GOOGLE SHEETS
# ===============================
def conectar_sheets():
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE,
        scopes=scopes)
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
# ==============================

def main():
    try:
        logging.info("Iniciando processo")

        logging.info("Conectando no SQL Server")
        conn = conectar_bd()

        logging.info("Executando query")
        df = pd.read_sql(QUERY, conn)
        conn.close()

        logging.info(f"Registros retornados: {len(df)}")

        # Converter datetime para string
        for col in df.select_dtypes(include=["datetime64[ns]"]).columns:
            df[col] = df[col].dt.strftime("%Y-%m-%d %H:%M:%S")

        # FIX definitivo para Google Sheets (NaN / Inf)
        df = df.replace([np.inf, -np.inf], "")
        df = df.fillna("")
        df = df.astype(str)

        logging.info("Conectando no Google Sheets")
        gc = conectar_sheets()
        sh = gc.open_by_key(SPREADSHEET_ID)

        try:
            ws = sh.worksheet(WORKSHEET_NAME)
            logging.info("Aba encontrada no Sheets")
        except gspread.exceptions.WorksheetNotFound:
            logging.info("Aba não encontrada, criando nova")
            ws = sh.add_worksheet(title=WORKSHEET_NAME, rows=1000, cols=25)
            # cria cabeçalho na primeira vez
            ws.update("A1", [df.columns.tolist()])

        # 🔎 Quantas linhas existem hoje
        existing_rows = len(ws.get_all_values())

        # 🧹 Limpa somente os dados (mantém header)
        if existing_rows > 1:
            ws.batch_clear([f"A2:T{existing_rows}"])

        # ✍️ Atualiza dados a partir da linha 2
        ws.update("A2", df.values.tolist())

        logging.info("Job finalizado com sucesso")

        atualizar_log_sheets("SUCESSO", f"{len(df)} registros atualizados")

    except Exception:
        logging.exception("Erro fatal na execução do job", exc_info=True)
        atualizar_log_sheets(
            "ERRO",
            "Falha na execução. Verificar arquivo de log."
        )
        raise

# ===============================
# EXECUÇÃO
# ===============================

PING_URL = "https://hc-ping.com/6eddc9a7-82a5-4588-ae62-16dc40908dd0"

if __name__ == "__main__":
    run_with_monitor(main, PING_URL)
