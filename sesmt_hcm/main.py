import os
import time
import pyodbc
import pandas as pd
import gspread
import logging
import numpy as np

from google.oauth2.service_account import Credentials
from dotenv import load_dotenv
from datetime import datetime
from gspread.utils import rowcol_to_a1
from monitor import run_with_monitor  # type: ignore # noqa: E402

# ===============================
# LOGGING
# ===============================
logging.basicConfig(
    filename="sesmt.log",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)

# ===============================
# LOAD ENV
# ===============================
load_dotenv()
# ===============================
# CONFIG GOOGLE
# ===============================
SERVICE_ACCOUNT_FILE = "/app/credentials.json"
SPREADSHEET_ID = "1pSfcEqqYxhi2pqoB5YBAvXgc9eWGV_lmsZzjntch6xA"
WORKSHEET_NAME = "BASE ATIVOS"

# LOG
LOG_SPREADSHEET_ID = "1Q1LjFhquJs6U0NccUo1HJzqzQ9TNlYl-7cdOFYRIMTA"
LOG_WORKSHEET_NAME = "API-SESMT"

# ===============================
# SQL SERVER
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
    conn = pyodbc.connect(conn_str, timeout=30)
    conn.timeout = 60
    return conn

# ===============================
# QUERY
# ===============================


QUERY = """
SELECT DISTINCT
    FUNC.NUMCPF     AS CPF,
    FUNC.NUMCAD     AS RE,
    FUNC.NOMFUN     AS [NOME DO FUNCIONARIO],
    EMP.apeemp      AS [EMPRESA],
    FUNC.DATADM     AS [DATA DE ADMISSÃO],
    CAR.titred      AS CARGO,
    FUNC.sitafa     AS STATUS,
    SIT.dessit      AS [DESCRIÇÃO DO STATUS]
FROM r034fun FUNC
INNER JOIN R030EMP EMP
    ON FUNC.NUMEMP = EMP.NUMEMP
    INNER JOIN R010SIT SIT
    ON FUNC.sitafa = SIT.codsit
LEFT JOIN R024CAR CAR
    ON FUNC.CODCAR = CAR.CODCAR
WHERE EMP.apeemp IN (
        'XRS SERVICOS',
        'IESS I RXS',
        'RS SEGX VIGILANCIA LTDA',
        'RS VIGIA',
        'LION LOCACAO'
    )
ORDER BY FUNC.DATADM
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
# LIMPEZA
# ===============================


def limpar_dataframe(df):
    df = df.replace([np.inf, -np.inf], np.nan)
    df = df.fillna("")
    return df

# ===============================
# RETRY
# ===============================


def retry(func, tentativas=3, delay=5):
    for i in range(tentativas):
        try:
            return func()
        except Exception:
            if i == tentativas - 1:
                raise
            time.sleep(delay)

# ===============================
# WRITE CHUNK (AJUSTADO PRA COLUNA A)
# ===============================


def write_in_chunks(ws, df, chunk_size=5000):
    data = df.values.tolist()
    for i in range(0, len(data), chunk_size):
        ws.update(
            f"A{2+i}",
            data[i:i+chunk_size],
            value_input_option="RAW"
        )

# ===============================
# LOG SHEETS
# ===============================


def atualizar_log_sheets(status, mensagem):

    def _exec():
        gc = conectar_sheets()
        sh = gc.open_by_key(LOG_SPREADSHEET_ID)

        try:
            ws = sh.worksheet(LOG_WORKSHEET_NAME)
        except gspread.exceptions.WorksheetNotFound:
            ws = sh.add_worksheet(title=LOG_WORKSHEET_NAME, rows=1000, cols=5)
            ws.update("A1", [["DATA", "STATUS", "MENSAGEM"]])

        agora = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        ws.append_row([agora, status, mensagem])

    try:
        retry(_exec)
    except Exception as e:
        logging.error(f"Erro ao logar no sheets: {e}")

# ===============================
# MAIN
# ===============================


def main():

    start = datetime.now()

    try:
        logging.info("Iniciando processo")

        with conectar_bd() as conn:
            df = pd.read_sql(QUERY, conn)

        logging.info(f"Registros: {len(df)}")

        # DATETIME SAFE
        for col in df.select_dtypes(include=["datetime64[ns]"]).columns:
            df[col] = df[col].astype(str).replace("NaT", "")

        df = limpar_dataframe(df)

        gc = retry(conectar_sheets)
        sh = retry(lambda: gc.open_by_key(SPREADSHEET_ID))

        try:
            ws = sh.worksheet(WORKSHEET_NAME)
        except gspread.exceptions.WorksheetNotFound:
            ws = sh.add_worksheet(title=WORKSHEET_NAME, rows=1000, cols=20)

        header = df.columns.tolist()

        # ===============================
        # HEADER (SÓ NA PRIMEIRA VEZ)
        # ===============================
        existing_header = ws.get("A1")

        if not existing_header or not existing_header[0]:
            ws.update("A1", [header])

        # ===============================
        # LIMPAR DADOS (SEM MEXER NO HEADER)
        # ===============================
        num_rows = ws.row_count
        end_col = len(header)

        start_cell = "A2"
        end_cell = rowcol_to_a1(num_rows, end_col)

        ws.batch_clear([f"{start_cell}:{end_cell}"])

        # ===============================
        # WRITE
        # ===============================
        if not df.empty:
            write_in_chunks(ws, df)

        tempo = datetime.now() - start

        logging.info(f"Finalizado em {tempo}")

        atualizar_log_sheets(
            "SUCESSO",
            f"{len(df)} registros | tempo: {tempo}"
        )

    except Exception as e:
        logging.error("Erro geral", exc_info=True)

        atualizar_log_sheets(
            "ERRO",
            str(e)
        )

# ===============================
# EXECUÇÃO
# ===============================


PING_URL = "https://hc-ping.com/d9d27a5c-35a9-43ce-a2d9-df6b8d0080e5"

if __name__ == "__main__":
    run_with_monitor(main, PING_URL)
