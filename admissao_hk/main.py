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
    filename="admissao_hk.log",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)

# ===============================
# LOAD ENV
# ===============================
load_dotenv()
# ===============================
# CONFIGURAÇÕES GOOGLE - API PRINCIPAL
# ===============================
SERVICE_ACCOUNT_FILE = "/app/credentials.json"
SPREADSHEET_ID = "1fj1fcLazJ7bU5tODc9MGcA4khvBpTaIqPInTIJSL7jE"
WORKSHEET_NAME = "COLABORADORES_HK"

# ===============================
# PLANILHA DE LOG
# ===============================
LOG_SPREADSHEET_ID = "1Q1LjFhquJs6U0NccUo1HJzqzQ9TNlYl-7cdOFYRIMTA"
LOG_WORKSHEET_NAME = "API-ADMISSAO-HK"

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
SELECT
    PF.CPF AS CPF,
    ENTFUNC.NOMECOMPLETO AS NOME,
    RELFUNC.CODIGO AS RE,
    ENTEMP.NOMECOMPLETO AS EMPRESA,
    CONVERT(VARCHAR(10), FUNC.DTADMISSAO, 103) AS [DATA DE ADMISSÃO],
    CARGO.DESCRICAO AS CARGO,
    CONVERT(VARCHAR(10), PF.DTNASCIMENTO, 103) AS [DATA DE NASCIMENTO],
    HS.SALARIO AS SALARIO

FROM FUNCIONARIO FUNC

INNER JOIN RELACAOENTIDADE RELFUNC
    ON RELFUNC.RELACAOENTIDADE = FUNC.FUNCIONARIO

INNER JOIN ENTIDADE ENTFUNC
    ON ENTFUNC.ENTIDADE = RELFUNC.PAPEL1

LEFT JOIN PESSOAFISICA PF
    ON PF.PESSOAFISICA = ENTFUNC.ENTIDADE

INNER JOIN RELACAOENTIDADE RELEMP
    ON RELEMP.RELACAOENTIDADE = RELFUNC.PAPEL2

INNER JOIN ENTIDADE ENTEMP
    ON ENTEMP.ENTIDADE = RELEMP.PAPEL1

INNER JOIN CARGOFUNCIONARIOS CF
    ON CF.CARGOFUNCIONARIOS = (
        SELECT MAX(CF2.CARGOFUNCIONARIOS)
        FROM CARGOFUNCIONARIOS CF2
        WHERE CF2.FUNCIONARIO = FUNC.FUNCIONARIO
    )

INNER JOIN CARGO
    ON CF.CARGO = CARGO.CARGO

LEFT JOIN HISTORICOSALARIAL HS
    ON HS.FUNCIONARIO = FUNC.FUNCIONARIO
    AND HS.DTFIM IS NULL
    AND HS.SITUACAO = 1

WHERE FUNC.DTDEMISSAO IS NULL
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
# LIMPEZA DE DADOS (IMPORTANTE)
# ===============================
def limpar_dataframe(df):

    # remove infinito
    df = df.replace([np.inf, -np.inf], np.nan)

    # troca NaN por vazio
    df = df.fillna("")

    return df

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

            ws = sh.add_worksheet(
                title=LOG_WORKSHEET_NAME,
                rows=1000,
                cols=5
            )

            ws.update(
                "A1",
                [["DATA", "STATUS", "MENSAGEM"]]
            )

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

        print("🔌 Conectando no SQL Server...")

        with conectar_bd() as conn:

            print("📥 Executando query...")

            df = pd.read_sql(QUERY, conn)

        logging.info(f"Registros retornados: {len(df)}")

        print(f"📊 Registros retornados: {len(df)}")

        # ===============================
        # CONVERTE DATETIME
        # ===============================

        for col in df.select_dtypes(include=["datetime64[ns]"]).columns:

            df[col] = df[col].dt.strftime("%Y-%m-%d %H:%M:%S")

        # ===============================
        # LIMPEZA DE DADOS
        # ===============================

        df = limpar_dataframe(df)

        # ===============================
        # GOOGLE SHEETS
        # ===============================

        print("📄 Conectando no Google Sheets...")

        gc = conectar_sheets()

        sh = gc.open_by_key(SPREADSHEET_ID)

        try:

            ws = sh.worksheet(WORKSHEET_NAME)

        except gspread.exceptions.WorksheetNotFound:

            ws = sh.add_worksheet(
                title=WORKSHEET_NAME,
                rows=1000,
                cols=20
            )

            ws.update(
                "A1",
                [df.columns.tolist()]
            )

        existing_rows = len(ws.get_all_values())

        if existing_rows > 1:

            ws.batch_clear([f"C2:J{existing_rows}"])

        ws.update("C2", df.values.tolist())

        logging.info("Job finalizado com sucesso")

        print("✅ Planilha atualizada com sucesso!")

        atualizar_log_sheets(
            "SUCESSO",
            f"{len(df)} registros processados"
        )

    except Exception:

        logging.error(
            "Erro fatal na execução do job",
            exc_info=True
        )

        atualizar_log_sheets(
            "ERRO",
            "Falha na execução. Verificar arquivo de log."
        )

        print("❌ Erro na execução. Verifique o log.")

# ===============================
# EXECUÇÃO
# ===============================

PING_URL = "https://hc-ping.com/f4a8c34c-225f-44ac-b284-b3ba03a4bea1"

if __name__ == "__main__":
    run_with_monitor(main, PING_URL)
