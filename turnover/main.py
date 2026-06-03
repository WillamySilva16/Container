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
    filename="turnover.log",
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
SPREADSHEET_ID = "1JXxtdS6LNQkCdhf7iAg8DGT1I2X_jgTalBPsD31aD-I"
WORKSHEET_NAME = "CONSOLIDADO"

# ===============================
# PLANILHA DE LOG
# ===============================
LOG_SPREADSHEET_ID = "1Q1LjFhquJs6U0NccUo1HJzqzQ9TNlYl-7cdOFYRIMTA"
LOG_WORKSHEET_NAME = "API-TURNOVER"

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
WITH RELFUNC_FIX AS (
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

REL_FIX AS (
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

AREA_FIX AS (
    SELECT *
    FROM (
        SELECT *,
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
    RELFUNC.CODIGO AS RE,

    CASE
        WHEN F.DTDEMISSAO IS NULL THEN 'ADMISSAO'
        ELSE 'DEMISSAO'
    END AS TIPO,

    F.DTADMISSAO,
    F.DTDEMISSAO,

    F.DTPRIMEIROPERIODOEXPERIENCIA,
    COALESCE(
        F.DTSEGUNDOPERIODOEXPERIENCIA,
        F.DTPRIMEIROPERIODOEXPERIENCIA
    ) AS DT_FIM_EXPERIENCIA,

    CASE
        WHEN F.DTPRIMEIROPERIODOEXPERIENCIA IS NOT NULL
         AND GETDATE() BETWEEN F.DTPRIMEIROPERIODOEXPERIENCIA
                          AND COALESCE(
                              F.DTSEGUNDOPERIODOEXPERIENCIA,
                              F.DTPRIMEIROPERIODOEXPERIENCIA
                          )
        THEN 'SIM' ELSE 'NÃO'
    END AS EM_EXPERIENCIA,

    ENTEMP.NOMERESUMIDO AS EMPRESA,
    ENTBASE.NOMERESUMIDO AS BASEOPERACIONAL,
    ENTCLI.NOMERESUMIDO AS CLIENTE,
    ENTLOCAL.NOMERESUMIDO AS LOCALSERVICO,
    ENTAREA.NOMERESUMIDO AS AREASUPERVISAO,
    T.DESCRICAO AS TURNO,
    ENTFUNC.NOMERESUMIDO AS FUNCIONARIO,
    CARGO.DESCRICAO AS CARGO,

    D.DESCRICAO AS TIPO_DEMISSAO

FROM FUNCIONARIO F

INNER JOIN RELFUNC_FIX RELFUNC
    ON RELFUNC.RELACAOENTIDADE = F.FUNCIONARIO

INNER JOIN ENTIDADE ENTFUNC
    ON ENTFUNC.ENTIDADE = RELFUNC.PAPEL1

INNER JOIN CARGO_FIX CF
    ON CF.FUNCIONARIO = F.FUNCIONARIO

INNER JOIN CARGO
    ON CF.CARGO = CARGO.CARGO

INNER JOIN REL_FIX RELEMP
    ON RELEMP.RELACAOENTIDADE = RELFUNC.PAPEL2

INNER JOIN ENTIDADE ENTEMP
    ON ENTEMP.ENTIDADE = RELEMP.PAPEL1

LEFT JOIN DOMINIO D
    ON D.CHAVE = F.CAUSARESCISAO
   AND D.TIPODOMINIO = 268
   AND D.SITUACAO = 1

LEFT JOIN ALOC_FIX A
    ON A.COLABORADOR = F.FUNCIONARIO

LEFT JOIN VAGAITEMCONTRATO V
    ON A.VAGAITEMCONTRATO = V.VAGAITEMCONTRATO

LEFT JOIN TURNOTRABALHO T
    ON V.TURNOTRABALHO = T.TURNOTRABALHO

LEFT JOIN POSTOLOCALSERVICO P
    ON P.POSTOLOCALSERVICO = V.POSTOLOCALSERVICO

LEFT JOIN LOCALSERVICOEMP LSE
    ON LSE.LOCALSERVICOEMP = P.LOCALSERVICOEMP

LEFT JOIN LOCALSERVICO LS
    ON LS.LOCALSERVICO = LSE.LOCALSERVICO

LEFT JOIN REL_FIX RELBASE
    ON RELBASE.RELACAOENTIDADE = LS.BASEOPERACIONAL

LEFT JOIN ENTIDADE ENTBASE
    ON ENTBASE.ENTIDADE = RELBASE.PAPEL1

LEFT JOIN REL_FIX RELLOCAL
    ON RELLOCAL.RELACAOENTIDADE = LSE.LOCALSERVICO

LEFT JOIN ENTIDADE ENTLOCAL
    ON ENTLOCAL.ENTIDADE = RELLOCAL.PAPEL1

LEFT JOIN REL_FIX RELCLI
    ON RELCLI.RELACAOENTIDADE = RELLOCAL.PAPEL2

LEFT JOIN ENTIDADE ENTCLI
    ON ENTCLI.ENTIDADE = RELCLI.PAPEL1

LEFT JOIN AREA_FIX LPA
    ON LPA.POSTOLOCALSERVICO = P.POSTOLOCALSERVICO
   AND LPA.TURNOTRABALHO = V.TURNOTRABALHO

LEFT JOIN REL_FIX RELAREA
    ON RELAREA.RELACAOENTIDADE = LPA.AREASUPERVISAO

LEFT JOIN ENTIDADE ENTAREA
    ON ENTAREA.ENTIDADE = RELAREA.PAPEL1

WHERE
    ISNULL(D.DESCRICAO, '') NOT IN (
        'TRANSFERENCIA P/ OUTRA FILIAL',
        'TRANSFERENCIA P/ OUTRA EMPRESA'
    )
    AND (
        F.DTADMISSAO >= '2025-01-01'
        OR F.DTDEMISSAO >= '2025-01-01'
    )
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

        # ===============================
        # GARANTE CABEÇALHO
        # ===============================
        header = df.columns.tolist()
        first_row = ws.row_values(1)

        if first_row != header:
            ws.update("A1", [header])

        # ===============================
        # LIMPA APENAS OS DADOS (LINHA 2+)
        # ===============================
        num_rows = len(ws.get_all_values())
        num_cols = len(header)

        if num_rows > 1:
            from gspread.utils import rowcol_to_a1

            start = rowcol_to_a1(2, 1)  # A2
            end = rowcol_to_a1(num_rows, num_cols)

            ws.batch_clear([f"{start}:{end}"])

        # ===============================
        # ESCREVE DADOS
        # ===============================
        if not df.empty:
            ws.update("A2", df.values.tolist())

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

PING_URL = "https://hc-ping.com/98c783e3-a273-4720-87c0-4750e10c529f"

if __name__ == "__main__":
    run_with_monitor(main, PING_URL)
