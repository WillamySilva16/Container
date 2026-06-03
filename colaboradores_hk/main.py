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
    filename="colaboradores.log",
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
SPREADSHEET_ID = "1rM7urqd9tWaKAm_jTuaeVE4sTrY9Fxs7M6bR-ZTQDy8"
WORKSHEET_NAME = "ColaboradoresHK"

# ===============================
# PLANILHA DE LOG
# ===============================
LOG_SPREADSHEET_ID = "1Q1LjFhquJs6U0NccUo1HJzqzQ9TNlYl-7cdOFYRIMTA"
LOG_WORKSHEET_NAME = "API-COLABORADORESHK"

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

QUERY = """WITH RELFUNC_FIX AS (
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
            ws.update(range_name="A1", values=[["DATA", "STATUS", "MENSAGEM"]])

        agora = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        ws.append_row([agora, status, mensagem])

    except Exception as e:
        logging.error(
            f"Erro ao atualizar planilha de log: {str(e)}"
        )

# ===============================
# MAIN
# ===============================

def main():
    try:
        logging.info("========== INÍCIO DO PROCESSO ==========")

        # ================= SQL =================
        logging.info("[1/5] Conectando ao SQL Server")
        conn = conectar_bd()

        logging.info("[2/5] Executando query...")
        inicio_query = datetime.now()

        df = pd.read_sql_query(QUERY, conn)

        fim_query = datetime.now()
        tempo = (fim_query - inicio_query).total_seconds()

        conn.close()

        logging.info(
            f"Query executada | Linhas: {len(df)} "
            f"| Tempo: {tempo:.2f}s"
        )

        # ================= TRATAMENTO =================
        logging.info("[3/5] Tratando dados")

        logging.info(f"Colunas: {list(df.columns)}")
        logging.info(f"Tipos antes:\n{df.dtypes}")

        # Datas
        for col in df.select_dtypes(include=["datetime64[ns]"]).columns:
            df[col] = df[col].dt.strftime("%d/%m/%Y")

        logging.info("Conversão de datas concluída")

        # Limpeza
        df = df.replace([np.inf, -np.inf], "")
        df = df.fillna("")
        df = df.astype(str)

        logging.info("Tratamento de nulos e tipos concluído")
        logging.info(f"Tipos finais:\n{df.dtypes}")

        # ================= GOOGLE SHEETS =================
        logging.info("[4/5] Enviando para Google Sheets")

        gc = conectar_sheets()
        sh = gc.open_by_key(SPREADSHEET_ID)

        try:
            ws = sh.worksheet(WORKSHEET_NAME)
            logging.info("Aba encontrada")
        except gspread.exceptions.WorksheetNotFound:
            logging.info("Aba não encontrada → criando nova")
            ws = sh.add_worksheet(title=WORKSHEET_NAME, rows=1000, cols=18)

        logging.info(
            "Preparando envio | Linhas: "
            f"{len(df)} | Colunas: {len(df.columns)}"
        )

        colunas = df.columns.tolist()
        primeira_linha = ws.row_values(1)

        if primeira_linha != colunas:
            logging.info("Cabeçalho diferente → atualizando")
            ws.update(range_name="A1", values=[colunas])
        else:
            logging.info("Cabeçalho OK")

        existing_rows = len(ws.get_all_values())

        if existing_rows > 1:
            logging.info(
                "Limpando dados antigos | Linhas atuais: %s",
                existing_rows,
            )
            ws.batch_clear([f"A2:Q{existing_rows}"])
        logging.info("Enviando novos dados...")
        ws.update(range_name="A2", values=df.values.tolist())

        logging.info("Dados enviados com sucesso")

        logging.info("[5/5] Finalizando")
        logging.info("========== FIM DO PROCESSO ==========")

        atualizar_log_sheets("SUCESSO", f"{len(df)} registros processados")

    except Exception as e:
        logging.exception(f"Erro fatal: {str(e)}")
        atualizar_log_sheets("ERRO", str(e))
        raise

# ===============================
# EXECUÇÃO
# ===============================

PING_URL = "https://hc-ping.com/dac91945-a349-4250-96bb-14222441633e"

if __name__ == "__main__":
    run_with_monitor(main, PING_URL)
