import os
import pyodbc
import pandas as pd
import gspread
import logging
import numpy as np

from google.oauth2.service_account import Credentials
from dotenv import load_dotenv

# ===============================
# LOGGING
# ===============================
logging.basicConfig(
    filename="excedente.log",
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
SPREADSHEET_ID = "1EjwXYDo05RSa5-FozTEYY8igRBxPgG78iy0yt57VsqY"
WORKSHEET_NAME = "Excedente"

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

QUERY = (
    "SELECT "
    "PONTO.DATA AS DATA, "
    "COUNT(PONTO.COLABORADOR) AS QTDE, "
    "ENTEMP.NOMERESUMIDO AS EMPRESA, "
    "ENTBASE.NOMERESUMIDO AS BASEOPERACIONAL, "
    "ENTCLI.NOMERESUMIDO AS CLIENTE, "
    "ENTLOCAL.NOMERESUMIDO AS LOCALSERVICO, "
    "ENTAREASUPERVISAO.NOMECOMPLETO AS AREASUPERVISAO, "
    "TURNOTRABALHO.DESCRICAO AS TURNO, "
    "ENTFUNC.NOMERESUMIDO AS FUNCIONARIO, "
    "CARGO.DESCRICAO AS CARGO "
    "FROM PONTO "
    "INNER JOIN CARGOFUNCIONARIOS ON "
    "(CARGOFUNCIONARIOS.FUNCIONARIO = PONTO.COLABORADOR AND "
    "CARGOFUNCIONARIOS.DTINICIO <= PONTO.DATA AND "
    "(CARGOFUNCIONARIOS.DTFIM >= PONTO.DATA OR "
    "CARGOFUNCIONARIOS.DTFIM IS NULL)) "
    "INNER JOIN CARGO ON "
    "(CARGOFUNCIONARIOS.CARGO = CARGO.CARGO) "
    "INNER JOIN RELACAOENTIDADE AS RELFUNC ON "
    "(RELFUNC.RELACAOENTIDADE = CARGOFUNCIONARIOS.FUNCIONARIO) "
    "INNER JOIN ENTIDADE AS ENTFUNC ON "
    "(ENTFUNC.ENTIDADE = RELFUNC.PAPEL1) "
    "INNER JOIN VAGAITEMCONTRATO ON "
    "(VAGAITEMCONTRATO.VAGAITEMCONTRATO = PONTO.VAGAITEMCONTRATO "
    "AND VAGAITEMCONTRATO.ORIGEMVAGA = 6) "
    "INNER JOIN TURNOTRABALHO ON "
    "(VAGAITEMCONTRATO.TURNOTRABALHO = TURNOTRABALHO.TURNOTRABALHO) "
    "INNER JOIN POSTOLOCALSERVICO ON "
    "(POSTOLOCALSERVICO.POSTOLOCALSERVICO = "
    "VAGAITEMCONTRATO.POSTOLOCALSERVICO) "
    "INNER JOIN LOCALSERVICOEMP ON "
    "(LOCALSERVICOEMP.LOCALSERVICOEMP = "
    "POSTOLOCALSERVICO.LOCALSERVICOEMP) "
    "INNER JOIN RELACAOENTIDADE AS RELEMP ON "
    "(RELEMP.RELACAOENTIDADE = LOCALSERVICOEMP.EMPRESA) "
    "INNER JOIN ENTIDADE ENTEMP ON "
    "(ENTEMP.ENTIDADE = RELEMP.PAPEL1) "
    "INNER JOIN LOCALSERVICO ON "
    "(LOCALSERVICO.LOCALSERVICO = LOCALSERVICOEMP.LOCALSERVICO) "
    "INNER JOIN RELACAOENTIDADE AS RELBASE ON "
    "(RELBASE.RELACAOENTIDADE = LOCALSERVICO.BASEOPERACIONAL) "
    "INNER JOIN ENTIDADE AS ENTBASE ON "
    "(ENTBASE.ENTIDADE = RELBASE.PAPEL1) "
    "INNER JOIN RELACAOENTIDADE AS RELLOCAL ON "
    "(RELLOCAL.RELACAOENTIDADE = LOCALSERVICOEMP.LOCALSERVICO) "
    "INNER JOIN ENTIDADE AS ENTLOCAL ON "
    "(ENTLOCAL.ENTIDADE = RELLOCAL.PAPEL1) "
    "INNER JOIN RELACAOENTIDADE AS RELCLI ON "
    "(RELCLI.RELACAOENTIDADE = RELLOCAL.PAPEL2) "
    "INNER JOIN ENTIDADE AS ENTCLI ON "
    "(ENTCLI.ENTIDADE = RELCLI.PAPEL1) "
    "LEFT JOIN LIGAPOSTOLOCALAREASUPER "
    "INNER JOIN RELACAOENTIDADE AS RELAREASUPERVISAO ON "
    "(RELAREASUPERVISAO.RELACAOENTIDADE = "
    "LIGAPOSTOLOCALAREASUPER.AREASUPERVISAO) "
    "INNER JOIN ENTIDADE AS ENTAREASUPERVISAO ON "
    "(ENTAREASUPERVISAO.ENTIDADE = RELAREASUPERVISAO.PAPEL1) "
    "ON (LIGAPOSTOLOCALAREASUPER.POSTOLOCALSERVICO = "
    "POSTOLOCALSERVICO.POSTOLOCALSERVICO AND "
    "LIGAPOSTOLOCALAREASUPER.TURNOTRABALHO = "
    "VAGAITEMCONTRATO.TURNOTRABALHO AND "
    "LIGAPOSTOLOCALAREASUPER.SITUACAO = 1) "
    "GROUP BY "
    "PONTO.DATA, "
    "ENTEMP.NOMERESUMIDO, "
    "ENTBASE.NOMERESUMIDO, "
    "ENTCLI.NOMERESUMIDO, "
    "ENTLOCAL.NOMERESUMIDO, "
    "ENTAREASUPERVISAO.NOMECOMPLETO, "
    "TURNOTRABALHO.DESCRICAO, "
    "ENTFUNC.NOMERESUMIDO, "
    "CARGO.DESCRICAO"
)

# ===============================
# GOOGLE SHEETS
# ===============================
def conectar_sheets():
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE, scopes=scopes
    )
    return gspread.authorize(creds)

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
            ws.batch_clear([f"A2:J{existing_rows}"])

        # ✍️ Atualiza dados a partir da linha 2
        ws.update("A2", df.values.tolist())

        logging.info("Job finalizado com sucesso")

    except Exception:
        logging.exception("Erro fatal na execução do job")
        raise

# ===============================
# EXECUÇÃO
# ===============================

if __name__ == "__main__":
    main()
