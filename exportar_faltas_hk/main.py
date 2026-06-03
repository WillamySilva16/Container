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
    filename="faltas_hk.log",
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
SPREADSHEET_ID = "1hkuiYGT8Nzaa-H3Hq-OLN_Fo5GKFuN5OwVYHbIBBL58"
WORKSHEET_NAME = "FALTAS_HK"

# ===============================
# PLANILHA DE LOG
# ===============================
LOG_SPREADSHEET_ID = "1Q1LjFhquJs6U0NccUo1HJzqzQ9TNlYl-7cdOFYRIMTA"
LOG_WORKSHEET_NAME = "API-FALTAS"

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
/* =========================================================
   FALTAS (INJUSTIFICADA / ABONADA)
========================================================= */
SELECT
    PONTO.DATA AS DATA,
    CASE
        WHEN COALESCE(PONTO.TPABONOPONTO, 1) = 1 THEN 'FALTA INJUSTIFICADA'
        WHEN PONTO.TPABONOPONTO IN (2, 3) THEN 'FALTA ABONADA'
    END AS TIPO_OCORRENCIA,
    ENTEMP.NOMERESUMIDO        AS EMPRESA,
    ENTBASE.NOMERESUMIDO       AS BASEOPERACIONAL,
    ENTCLI.NOMERESUMIDO        AS CLIENTE,
    ENTLOCAL.NOMERESUMIDO      AS LOCALSERVICO,
    ENTAREASUPERVISAO.NOMECOMPLETO AS AREASUPERVISAO,
    TURNOTRABALHO.DESCRICAO    AS TURNO,
    ENTFUNC.NOMERESUMIDO       AS FUNCIONARIO,
    RELFUNC.CODIGO             AS RE_FUNCIONARIO,
    CARGO.DESCRICAO            AS CARGO,
    1 AS QTDE
FROM PONTO
INNER JOIN RELACAOENTIDADE RELFUNC
    ON RELFUNC.RELACAOENTIDADE = PONTO.COLABORADOR
INNER JOIN ENTIDADE ENTFUNC
    ON ENTFUNC.ENTIDADE = RELFUNC.PAPEL1
INNER JOIN CARGOFUNCIONARIOS
    ON CARGOFUNCIONARIOS.FUNCIONARIO = PONTO.COLABORADOR
   AND CARGOFUNCIONARIOS.DTINICIO <= PONTO.DATA
   AND (CARGOFUNCIONARIOS.DTFIM >= PONTO.DATA
        OR CARGOFUNCIONARIOS.DTFIM IS NULL)
INNER JOIN VAGAITEMCONTRATO
    ON PONTO.VAGAITEMCONTRATO = VAGAITEMCONTRATO.VAGAITEMCONTRATO
INNER JOIN TURNOTRABALHO
    ON VAGAITEMCONTRATO.TURNOTRABALHO = TURNOTRABALHO.TURNOTRABALHO
INNER JOIN CARGO
    ON CARGOFUNCIONARIOS.CARGO = CARGO.CARGO
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
LEFT JOIN LIGAPOSTOLOCALAREASUPER
    INNER JOIN RELACAOENTIDADE RELAREASUPERVISAO
        ON RELAREASUPERVISAO.RELACAOENTIDADE = (
            LIGAPOSTOLOCALAREASUPER.AREASUPERVISAO)
    INNER JOIN ENTIDADE ENTAREASUPERVISAO
        ON ENTAREASUPERVISAO.ENTIDADE = (
            RELAREASUPERVISAO.PAPEL1)
    ON LIGAPOSTOLOCALAREASUPER.POSTOLOCALSERVICO = (
        POSTOLOCALSERVICO.POSTOLOCALSERVICO)
   AND LIGAPOSTOLOCALAREASUPER.TURNOTRABALHO = (
       VAGAITEMCONTRATO.TURNOTRABALHO)
   AND LIGAPOSTOLOCALAREASUPER.SITUACAO = 1
WHERE
    PONTO.SITMOBRAHOJE = 9
    AND COALESCE(PONTO.TPABONOPONTO, 1) IN (1, 2, 3)

UNION ALL

/* =========================================================
   SUSPENSÃO
========================================================= */
SELECT
    PONTO.DATA AS DATA,
    'SUSPENSÃO' AS TIPO_OCORRENCIA,
    ENTEMP.NOMERESUMIDO        AS EMPRESA,
    ENTBASE.NOMERESUMIDO       AS BASEOPERACIONAL,
    ENTCLI.NOMERESUMIDO        AS CLIENTE,
    ENTLOCAL.NOMERESUMIDO      AS LOCALSERVICO,
    ENTAREASUPERVISAO.NOMECOMPLETO AS AREASUPERVISAO,
    TURNOTRABALHO.DESCRICAO    AS TURNO,
    ENTFUNC.NOMERESUMIDO       AS FUNCIONARIO,
    RELFUNC.CODIGO             AS RE_FUNCIONARIO,
    CARGO.DESCRICAO            AS CARGO,
    1 AS QTDE
FROM SITMAODEOBRAFUNC
INNER JOIN FUNCIONARIO
    ON FUNCIONARIO.FUNCIONARIO = SITMAODEOBRAFUNC.FUNCIONARIO
INNER JOIN PONTO
    ON PONTO.COLABORADOR = SITMAODEOBRAFUNC.FUNCIONARIO
   AND PONTO.DATA BETWEEN SITMAODEOBRAFUNC.DTINICIO
       AND COALESCE(SITMAODEOBRAFUNC.DTFIM, CAST('9999-01-01' AS DATE))
INNER JOIN RELACAOENTIDADE RELFUNC
    ON RELFUNC.RELACAOENTIDADE = FUNCIONARIO.FUNCIONARIO
INNER JOIN ENTIDADE ENTFUNC
    ON ENTFUNC.ENTIDADE = RELFUNC.PAPEL1
INNER JOIN CARGOFUNCIONARIOS
    ON CARGOFUNCIONARIOS.FUNCIONARIO = FUNCIONARIO.FUNCIONARIO
   AND CARGOFUNCIONARIOS.DTINICIO <= PONTO.DATA
   AND (CARGOFUNCIONARIOS.DTFIM >= PONTO.DATA
        OR CARGOFUNCIONARIOS.DTFIM IS NULL)
INNER JOIN CARGO
    ON CARGOFUNCIONARIOS.CARGO = CARGO.CARGO
INNER JOIN VAGAITEMCONTRATO
    ON VAGAITEMCONTRATO.VAGAITEMCONTRATO = PONTO.VAGAITEMCONTRATO
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
LEFT JOIN LIGAPOSTOLOCALAREASUPER
    INNER JOIN RELACAOENTIDADE RELAREASUPERVISAO
        ON RELAREASUPERVISAO.RELACAOENTIDADE = (
            LIGAPOSTOLOCALAREASUPER.AREASUPERVISAO)
    INNER JOIN ENTIDADE ENTAREASUPERVISAO
        ON ENTAREASUPERVISAO.ENTIDADE = (
            RELAREASUPERVISAO.PAPEL1)
    ON LIGAPOSTOLOCALAREASUPER.POSTOLOCALSERVICO = (
        POSTOLOCALSERVICO.POSTOLOCALSERVICO)
   AND LIGAPOSTOLOCALAREASUPER.TURNOTRABALHO = (
       VAGAITEMCONTRATO.TURNOTRABALHO)
   AND LIGAPOSTOLOCALAREASUPER.SITUACAO = 1
WHERE
    SITMAODEOBRAFUNC.SITUACAOMOBRATEMP = 7
    AND SITMAODEOBRAFUNC.SITUACAO = 1;
"""

# ===============================
# GOOGLE SHEETS
# ===============================

def conectar_sheets():
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE, scopes=scopes)
    return gspread.authorize(creds)

# ===============================
# FUNÇÃO DE LOG NO SHEETS
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
        logging.error("Erro ao atualizar planilha de log", exc_info=True)
        print("Erro ao atualizar planilha de log:", e)
        raise

# ===============================
# MAIN
# ===============================

def main():
    atualizar_log_sheets("INICIO", "Processo iniciado")
    try:
        logging.info("Iniciando processo")
        print("🔌 Conectando no SQL Server...")

        # 🔐 Conexão segura (fecha automaticamente)
        with conectar_bd() as conn:
            print("📥 Executando query...")
            df = pd.read_sql(QUERY, conn)

        logging.info(f"Registros retornados: {len(df)}")
        print(f"📊 Registros retornados: {len(df)}")

        # Converte datetime para string
        for col in df.select_dtypes(include=["datetime64[ns]"]).columns:
            df[col] = df[col].dt.strftime("%Y-%m-%d %H:%M:%S")

        # Remove NaN e Inf
        df = df.replace([np.inf, -np.inf], "")
        df = df.fillna("")
        df = df.astype(str)

        print("📄 Conectando no Google Sheets...")
        gc = conectar_sheets()
        sh = gc.open_by_key(SPREADSHEET_ID)

        try:
            ws = sh.worksheet(WORKSHEET_NAME)
        except gspread.exceptions.WorksheetNotFound:
            ws = sh.add_worksheet(title=WORKSHEET_NAME, rows=1000, cols=df.shape[1]+2)  # noqa: E501
            ws.update("A1", [df.columns.tolist()])

        existing_rows = len(ws.get_all_values())

        # Batch clear dinâmico
        last_col = chr(65 + df.shape[1] - 1)  # Coluna final baseado no DF
        if existing_rows > 1:
            ws.batch_clear([f"A2:{last_col}{existing_rows}"])

        # Atualiza dados
        ws.update("A2", df.values.tolist())

        logging.info("Job finalizado com sucesso")
        print("✅ Planilha atualizada com sucesso!")

        atualizar_log_sheets("SUCESSO", f"{len(df)} registros processados")

    except Exception as e:
        logging.error("Erro fatal na execução do job", exc_info=True)
        atualizar_log_sheets("ERRO", f"Falha na execução: {e}")
        print("❌ Erro na execução. Verifique o log.")
        raise  # garante que o Healthcheck veja falha

# ===============================
# EXECUÇÃO MONITORADA
# ===============================

PING_URL = "https://hc-ping.com/7be0fc13-3855-45e5-b0fe-d2f349a320bb"

if __name__ == "__main__":
    run_with_monitor(main, PING_URL)
