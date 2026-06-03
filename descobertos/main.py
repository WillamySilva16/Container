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

from monitor import run_with_monitor  # noqa: E402

# ===============================
# LOGGING
# ===============================
logging.basicConfig(
    filename="descobertos.log",
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
SPREADSHEET_ID = "1xfT2Yyqh-JjQKPJPBEfxPvmoH9zw7IlYq773dKSOLgo"
WORKSHEET_NAME = "postos_descobertos"

LOG_SPREADSHEET_ID = "1Q1LjFhquJs6U0NccUo1HJzqzQ9TNlYl-7cdOFYRIMTA"
LOG_WORKSHEET_NAME = "API-DESCOBERTOS"

# ===============================
# SQL
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

QUERY = """
SELECT
PONTOVAGA.DATA,
ENTEMP.NOMERESUMIDO AS EMPRESA,
ENTBASE.NOMERESUMIDO AS BASEOPERACIONAL,
ENTCLI.NOMERESUMIDO AS CLIENTE,
ENTLOCAL.NOMERESUMIDO AS LOCALSERVICO,
ENTAREASUPERVISAO.NOMECOMPLETO AS AREASUPERVISAO,
TURNOTRABALHO.DESCRICAO AS TURNO,

ENTFUNC.NOMERESUMIDO AS FUNCIONARIO,
CARGO.DESCRICAO AS CARGO_FUNCIONARIO,

CARGO_VAGA.DESCRICAO AS CARGO_VAGA

FROM PONTOVAGA

INNER JOIN VAGAITEMCONTRATO
    ON VAGAITEMCONTRATO.VAGAITEMCONTRATO = PONTOVAGA.VAGAITEMCONTRATO

LEFT JOIN CARGO CARGO_VAGA
    ON CARGO_VAGA.CARGO = VAGAITEMCONTRATO.CARGO

INNER JOIN TURNOTRABALHO
    ON VAGAITEMCONTRATO.TURNOTRABALHO = TURNOTRABALHO.TURNOTRABALHO

INNER JOIN POSTOLOCALSERVICO
    ON POSTOLOCALSERVICO.POSTOLOCALSERVICO = VAGAITEMCONTRATO.POSTOLOCALSERVICO

INNER JOIN LOCALSERVICOEMP
    ON LOCALSERVICOEMP.LOCALSERVICOEMP = POSTOLOCALSERVICO.LOCALSERVICOEMP

INNER JOIN RELACAOENTIDADE RELEMP
    ON RELEMP.RELACAOENTIDADE = LOCALSERVICOEMP.EMPRESA

INNER JOIN ENTIDADE ENTEMP
    ON ENTEMP.ENTIDADE = RELEMP.PAPEL1

INNER JOIN LOCALSERVICO
    ON LOCALSERVICO.LOCALSERVICO = LOCALSERVICOEMP.LOCALSERVICO

INNER JOIN RELACAOENTIDADE RELBASE
    ON RELBASE.RELACAOENTIDADE = LOCALSERVICO.BASEOPERACIONAL

INNER JOIN ENTIDADE ENTBASE
    ON ENTBASE.ENTIDADE = RELBASE.PAPEL1

INNER JOIN RELACAOENTIDADE RELLOCAL
    ON RELLOCAL.RELACAOENTIDADE = LOCALSERVICOEMP.LOCALSERVICO

INNER JOIN ENTIDADE ENTLOCAL
    ON ENTLOCAL.ENTIDADE = RELLOCAL.PAPEL1

INNER JOIN RELACAOENTIDADE RELCLI
    ON RELCLI.RELACAOENTIDADE = RELLOCAL.PAPEL2

INNER JOIN ENTIDADE ENTCLI
    ON ENTCLI.ENTIDADE = RELCLI.PAPEL1

LEFT JOIN ALOCACAOMAODEOBRA
    ON ALOCACAOMAODEOBRA.VAGAITEMCONTRATO = VAGAITEMCONTRATO.VAGAITEMCONTRATO
    AND ALOCACAOMAODEOBRA.DTFIM IS NULL
    AND ALOCACAOMAODEOBRA.SITALOCACAO = 1

LEFT JOIN FUNCIONARIO
    ON FUNCIONARIO.FUNCIONARIO = ALOCACAOMAODEOBRA.COLABORADOR

LEFT JOIN RELACAOENTIDADE RELFUNC
    ON RELFUNC.RELACAOENTIDADE = FUNCIONARIO.FUNCIONARIO

LEFT JOIN ENTIDADE ENTFUNC
    ON ENTFUNC.ENTIDADE = RELFUNC.PAPEL1

LEFT JOIN CARGOFUNCIONARIOS
    ON CARGOFUNCIONARIOS.CARGOFUNCIONARIOS = (
        SELECT MAX(CF.CARGOFUNCIONARIOS)
        FROM CARGOFUNCIONARIOS CF
        WHERE CF.FUNCIONARIO = FUNCIONARIO.FUNCIONARIO
    )

LEFT JOIN CARGO
    ON CARGO.CARGO = CARGOFUNCIONARIOS.CARGO

LEFT JOIN LIGAPOSTOLOCALAREASUPER
INNER JOIN RELACAOENTIDADE AS RELAREASUPERVISAO
 ON RELAREASUPERVISAO.RELACAOENTIDADE = LIGAPOSTOLOCALAREASUPER.AREASUPERVISAO
INNER JOIN ENTIDADE AS ENTAREASUPERVISAO
        ON ENTAREASUPERVISAO.ENTIDADE=RELAREASUPERVISAO.PAPEL1
ON (
    LIGAPOSTOLOCALAREASUPER.POSTOLOCALSERVICO=POSTOLOCALSERVICO.POSTOLOCALSERVICO
    AND LIGAPOSTOLOCALAREASUPER.TURNOTRABALHO=VAGAITEMCONTRATO.TURNOTRABALHO
    AND LIGAPOSTOLOCALAREASUPER.SITUACAO=1
)

WHERE
PONTOVAGA.SITUACAOCOBERTA = 0
AND PONTOVAGA.DATA >= '2026-01-01'
AND PONTOVAGA.DATA <= CAST(GETDATE() AS DATE)

ORDER BY
PONTOVAGA.DATA
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
# WRITE COM AUTO-RESIZE
# ===============================
def write_in_chunks(ws, df, chunk_size=5000):

    data = df.values.tolist()

    total_rows_needed = len(data) + 1
    total_cols_needed = len(df.columns)

    # 🔥 AJUSTA TAMANHO AUTOMATICAMENTE
    if ws.row_count < total_rows_needed:
        ws.add_rows(total_rows_needed - ws.row_count)

    if ws.col_count < total_cols_needed:
        ws.add_cols(total_cols_needed - ws.col_count)

    # 🔥 ESCREVE EM PARTES
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
            # 🔥 já cria grande
            ws = sh.add_worksheet(title=WORKSHEET_NAME, rows=200000, cols=50)

        header = df.columns.tolist()

        # HEADER (só primeira vez)
        existing_header = ws.get("A1")

        if not existing_header or not existing_header[0]:
            ws.update("A1", [header])

        # LIMPAR DADOS (mantém header)
        num_rows = ws.row_count
        end_col = len(header)

        ws.batch_clear([f"A2:{rowcol_to_a1(num_rows, end_col)}"])

        # WRITE
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
# EXEC
# ===============================
PING_URL = "https://hc-ping.com/0c655192-805f-4bc6-b78f-f97621af9f2a"

if __name__ == "__main__":
    run_with_monitor(main, PING_URL)
