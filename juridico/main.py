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

# ===============================
# IMPORT MONITOR
# ===============================
, "..")
    )
)

from monitor import run_with_monitor  # noqa: E402

# ===============================
# LOGGING
# ===============================
logging.basicConfig(
    filename="juridico.log",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)

# ===============================
# ENV
# ===============================
load_dotenv()
# ===============================
# GOOGLE SHEETS
# ===============================
SERVICE_ACCOUNT_FILE = "/app/credentials.json"
SPREADSHEET_ID = "1--mAnwlKWL1cWrCIK6BiV2sHNanO3Gl8XLifBlv3Rag"
WORKSHEET_NAME = "COLABORADORES"

LOG_SPREADSHEET_ID = "1Q1LjFhquJs6U0NccUo1HJzqzQ9TNlYl-7cdOFYRIMTA"
LOG_WORKSHEET_NAME = "API-JURIDICO"

# ===============================
# SQL CONNECTION
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

QUERY = """ WITH RELFUNC_FIX AS (
    SELECT *
    FROM (
        SELECT *,
               ROW_NUMBER() OVER (
                   PARTITION BY RELACAOENTIDADE
                   ORDER BY CODIGO DESC
               ) AS RN
        FROM RELACAOENTIDADE
        WHERE CODIGO IS NOT NULL
    ) X
    WHERE RN = 1
),

CARGO_FIX AS (
    SELECT *
    FROM (
        SELECT *,
               ROW_NUMBER() OVER (
                   PARTITION BY FUNCIONARIO
                   ORDER BY CARGOFUNCIONARIOS DESC
               ) AS RN
        FROM CARGOFUNCIONARIOS
    ) X
    WHERE RN = 1
),

ALOC_FIX AS (
    SELECT *
    FROM (
        SELECT *,
               ROW_NUMBER() OVER (
                   PARTITION BY COLABORADOR
                   ORDER BY
                        CASE WHEN DTFIM IS NULL THEN 1 ELSE 2 END,
                        DTFIM DESC
               ) AS RN
        FROM ALOCACAOMAODEOBRA
        WHERE SITALOCACAO = 1
    ) X
    WHERE RN = 1
),

AREA_FIX AS (
    SELECT *
    FROM (
        SELECT POSTOLOCALSERVICO, TURNOTRABALHO, AREASUPERVISAO,
               ROW_NUMBER() OVER (
                   PARTITION BY POSTOLOCALSERVICO, TURNOTRABALHO
                   ORDER BY DTINICIO DESC
               ) AS RN
        FROM LIGAPOSTOLOCALAREASUPER
        WHERE SITUACAO = 1
    ) X
    WHERE RN = 1
)

SELECT
    PF.CPF AS CPF,
    RELFUNC.CODIGO AS RE,
    ENTFUNC.NOMECOMPLETO AS NOME,
    ENTEMP.NOMERESUMIDO AS EMPRESA,

    CONVERT(VARCHAR(10), F.DTADMISSAO, 103) AS [DATA DE ADMISSÃO],
    CONVERT(VARCHAR(10), F.DTDEMISSAO, 103) AS [DATA DE DEMISSÃO],

    CARGO.DESCRICAO AS CARGO,

    ENTLOCAL.NOMERESUMIDO AS LOCAL_TRABALHO,

    ENTAREA.NOMERESUMIDO AS SUPERVISOR

FROM FUNCIONARIO F

INNER JOIN RELFUNC_FIX RELFUNC
    ON RELFUNC.RELACAOENTIDADE = F.FUNCIONARIO

INNER JOIN ENTIDADE ENTFUNC
    ON ENTFUNC.ENTIDADE = RELFUNC.PAPEL1

LEFT JOIN PESSOAFISICA PF
    ON PF.PESSOAFISICA = ENTFUNC.ENTIDADE

INNER JOIN RELACAOENTIDADE RELEMP
    ON RELEMP.RELACAOENTIDADE = RELFUNC.PAPEL2

INNER JOIN ENTIDADE ENTEMP
    ON ENTEMP.ENTIDADE = RELEMP.PAPEL1

INNER JOIN CARGO_FIX CF
    ON CF.FUNCIONARIO = F.FUNCIONARIO

INNER JOIN CARGO
    ON CARGO.CARGO = CF.CARGO

-- LOCAL
LEFT JOIN ALOC_FIX A
    ON A.COLABORADOR = F.FUNCIONARIO

LEFT JOIN VAGAITEMCONTRATO V
    ON V.VAGAITEMCONTRATO = A.VAGAITEMCONTRATO

LEFT JOIN POSTOLOCALSERVICO P
    ON P.POSTOLOCALSERVICO = V.POSTOLOCALSERVICO

LEFT JOIN LOCALSERVICOEMP LSE
    ON LSE.LOCALSERVICOEMP = P.LOCALSERVICOEMP

LEFT JOIN RELACAOENTIDADE RELLOCAL
    ON RELLOCAL.RELACAOENTIDADE = LSE.LOCALSERVICO

LEFT JOIN ENTIDADE ENTLOCAL
    ON ENTLOCAL.ENTIDADE = RELLOCAL.PAPEL1

-- SUPERVISOR
LEFT JOIN AREA_FIX AF
    ON AF.POSTOLOCALSERVICO = P.POSTOLOCALSERVICO
   AND AF.TURNOTRABALHO = V.TURNOTRABALHO

LEFT JOIN RELACAOENTIDADE RELAREA
    ON RELAREA.RELACAOENTIDADE = AF.AREASUPERVISAO

LEFT JOIN ENTIDADE ENTAREA
    ON ENTAREA.ENTIDADE = RELAREA.PAPEL1

ORDER BY F.DTADMISSAO, RELFUNC.CODIGO ASC
 """

# ===============================
# GOOGLE AUTH
# ===============================

def conectar_sheets():
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE,
        scopes=scopes
    )
    return gspread.authorize(creds)

# ===============================
# LIMPEZA DF
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

        # ===============================
        # BANCO
        # ===============================
        with conectar_bd() as conn:
            df = pd.read_sql(QUERY, conn)

        logging.info(f"Registros: {len(df)}")

        # ===============================
        # DATA
        # ===============================
        for col in df.select_dtypes(include=["datetime64[ns]"]).columns:
            df[col] = df[col].astype(str).replace("NaT", "")

        # ===============================
        # LIMPEZA
        # ===============================
        df = limpar_dataframe(df)

        # ===============================
        # 🔥 LIMITA B → J (9 colunas)
        # ===============================
        df = df.iloc[:, :9]

        # ===============================
        # SHEETS
        # ===============================
        gc = retry(conectar_sheets)
        sh = retry(lambda: gc.open_by_key(SPREADSHEET_ID))

        try:
            ws = sh.worksheet(WORKSHEET_NAME)
        except gspread.exceptions.WorksheetNotFound:
            ws = sh.add_worksheet(title=WORKSHEET_NAME, rows=1000, cols=20)

        header = df.columns.tolist()

        # ===============================
        # CABEÇALHO (B1)
        # ===============================
        ws.update("B1", [header])

        # ===============================
        # 🔥 LIMPA SÓ B → J
        # ===============================
        num_rows = ws.row_count

        start_cell = "B2"
        end_cell = rowcol_to_a1(num_rows, 10)  # J ✅

        ws.batch_clear([f"{start_cell}:{end_cell}"])

        # ===============================
        # ESCREVE DADOS
        # ===============================
        if not df.empty:

            data = df.values.tolist()

            for i in range(0, len(data), 5000):
                ws.update(
                    f"B{2 + i}",
                    data[i:i+5000],
                    value_input_option="RAW"
                )

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

PING_URL = "https://hc-ping.com/9c19d48a-fa4c-494e-b710-3a5bff21ce34"

if __name__ == "__main__":
    run_with_monitor(main, PING_URL)
