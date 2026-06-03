import os
import time
import random
import logging
import numpy as np
import pandas as pd
import gspread

from functools import wraps
from sqlalchemy import create_engine
from google.oauth2.service_account import Credentials
from dotenv import load_dotenv


# ===============================
# LOGGING
# Registra eventos em arquivo .log com timestamp, nível e mensagem.
# Útil pra rastrear erros em ambientes on-premise sem acesso ao terminal.
# ===============================
logging.basicConfig(
    filename="treinamentos_hk.log",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)


# ===============================
# VARIÁVEIS DE AMBIENTE
# Carrega as credenciais do banco a partir de um arquivo .env local.
# Nunca deixe senhas hardcoded no código — use sempre variáveis de ambiente.
# ===============================
load_dotenv()


# ===============================
# CONFIGURAÇÕES GOOGLE SHEETS
# SERVICE_ACCOUNT_FILE: caminho para o JSON de credenciais da service account.
# SPREADSHEET_ID: ID da planilha (aparece na URL do Google Sheets).
# WORKSHEET_NAME: nome da aba onde os dados serão gravados.
# ===============================
SERVICE_ACCOUNT_FILE = "/app/credentials.json"
SPREADSHEET_ID = "1EjwXYDo05RSa5-FozTEYY8igRBxPgG78iy0yt57VsqY"
WORKSHEET_NAME = "Treinamentos"


# ===============================
# RETRY COM BACKOFF EXPONENCIAL
# Decorator que envolve qualquer função que chame a API do Google Sheets.
# Se vier erro 429 (quota excedida), ele aguarda e tenta de novo até
# max_retries vezes. O tempo de espera dobra a cada tentativa (exponencial)
# e tem um pequeno valor aleatório (jitter) pra evitar colisão quando
# múltiplas instâncias do script rodam ao mesmo tempo.
#
# Exemplo de delays com base_delay=2 e jitter entre 0 e 1s:
#   tentativa 1: ~2s
#   tentativa 2: ~4s
#   tentativa 3: ~8s
#   tentativa 4: ~16s
#   tentativa 5: ~32s
#
# Outros erros da API (ex: permissão negada, planilha não encontrada)
# sobem diretamente sem retry — não adianta tentar de novo nesses casos.
# ===============================
def retry_with_backoff(max_retries=5, base_delay=2):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except gspread.exceptions.APIError as e:
                    if e.response.status_code == 429:
                        # Calcula o tempo de espera: dobra a cada tentativa + jitter aleatório
                        delay = base_delay * (2 ** attempt) + random.uniform(0, 1)
                        logging.warning(
                            f"Quota atingida (429), tentativa {attempt + 1}/{max_retries}. "
                            f"Aguardando {delay:.1f}s antes de tentar novamente..."
                        )
                        time.sleep(delay)
                    else:
                        # Qualquer outro erro da API (403, 404, 500...) sobe imediatamente
                        raise
            # Se chegou aqui, esgotou todas as tentativas sem sucesso
            raise Exception(
                f"Máximo de tentativas atingido ({max_retries}). "
                f"Verifique a quota da API do Google Sheets."
            )
        return wrapper
    return decorator


# ===============================
# CONEXÃO SQL SERVER
# Usa SQLAlchemy como camada de conexão — exigido pelo pandas >= 2.0
# para pd.read_sql sem warnings. O pyodbc continua sendo o driver ODBC
# por baixo, mas o pandas agora recebe um engine SQLAlchemy em vez de
# uma conexão pyodbc direta.
# TrustServerCertificate=yes evita erro de certificado SSL em ambientes
# on-premise com certificado autoassinado.
# ===============================
def conectar_bd():
    usuario = os.getenv("DB_USER")
    senha = os.getenv("DB_PASSWORD")
    servidor = os.getenv("DB_SERVER")
    banco = os.getenv("DB_DATABASE")
    conn_str = (
        f"mssql+pyodbc://{usuario}:{senha}@{servidor}/{banco}"
        "?driver=ODBC+Driver+17+for+SQL+Server&TrustServerCertificate=yes"
    )
    return create_engine(conn_str)


# ===============================
# QUERY SQL
# Busca os registros de ponto agrupados por data, empresa, base, cliente,
# local de serviço, área de supervisão, turno, funcionário e cargo.
# O LEFT JOIN com LIGAPOSTOLOCALAREASUPER garante que registros sem
# área de supervisão ainda apareçam no resultado (com NULL nessa coluna).
# ===============================
QUERY = """
SELECT
    PONTO.DATA AS DATA,
    COUNT(PONTO.COLABORADOR) AS QTDE,
    ENTEMP.NOMERESUMIDO AS EMPRESA,
    ENTBASE.NOMERESUMIDO AS BASEOPERACIONAL,
    ENTCLI.NOMERESUMIDO AS CLIENTE,
    ENTLOCAL.NOMERESUMIDO AS LOCALSERVICO,
    ENTAREASUPERVISAO.NOMECOMPLETO AS AREASUPERVISAO,
    TURNOTRABALHO.DESCRICAO AS TURNO,
    ENTFUNC.NOMERESUMIDO AS FUNCIONARIO,
    CARGO.DESCRICAO AS CARGO
FROM PONTO
INNER JOIN CARGOFUNCIONARIOS ON (
    CARGOFUNCIONARIOS.FUNCIONARIO = PONTO.COLABORADOR
    AND CARGOFUNCIONARIOS.DTINICIO <= PONTO.DATA
    AND (
        CARGOFUNCIONARIOS.DTFIM >= PONTO.DATA
        OR CARGOFUNCIONARIOS.DTFIM IS NULL
    )
)
INNER JOIN CARGO ON (
    CARGOFUNCIONARIOS.CARGO = CARGO.CARGO
)
INNER JOIN RELACAOENTIDADE AS RELFUNC ON (
    RELFUNC.RELACAOENTIDADE = CARGOFUNCIONARIOS.FUNCIONARIO
)
INNER JOIN ENTIDADE AS ENTFUNC ON (
    ENTFUNC.ENTIDADE = RELFUNC.PAPEL1
)
INNER JOIN VAGAITEMCONTRATO ON (
    VAGAITEMCONTRATO.VAGAITEMCONTRATO = PONTO.VAGAITEMCONTRATO
    AND VAGAITEMCONTRATO.ORIGEMVAGA = 7
)
INNER JOIN TURNOTRABALHO ON (
    VAGAITEMCONTRATO.TURNOTRABALHO = TURNOTRABALHO.TURNOTRABALHO
)
INNER JOIN POSTOLOCALSERVICO ON (
    POSTOLOCALSERVICO.POSTOLOCALSERVICO =
    VAGAITEMCONTRATO.POSTOLOCALSERVICO
)
INNER JOIN LOCALSERVICOEMP ON (
    LOCALSERVICOEMP.LOCALSERVICOEMP =
    POSTOLOCALSERVICO.LOCALSERVICOEMP
)
INNER JOIN RELACAOENTIDADE AS RELEMP ON (
    RELEMP.RELACAOENTIDADE = LOCALSERVICOEMP.EMPRESA
)
INNER JOIN ENTIDADE ENTEMP ON (
    ENTEMP.ENTIDADE = RELEMP.PAPEL1
)
INNER JOIN LOCALSERVICO ON (
    LOCALSERVICO.LOCALSERVICO = LOCALSERVICOEMP.LOCALSERVICO
)
INNER JOIN RELACAOENTIDADE AS RELBASE ON (
    RELBASE.RELACAOENTIDADE = LOCALSERVICO.BASEOPERACIONAL
)
INNER JOIN ENTIDADE AS ENTBASE ON (
    ENTBASE.ENTIDADE = RELBASE.PAPEL1
)
INNER JOIN RELACAOENTIDADE AS RELLOCAL ON (
    RELLOCAL.RELACAOENTIDADE = LOCALSERVICOEMP.LOCALSERVICO
)
INNER JOIN ENTIDADE AS ENTLOCAL ON (
    ENTLOCAL.ENTIDADE = RELLOCAL.PAPEL1
)
INNER JOIN RELACAOENTIDADE AS RELCLI ON (
    RELCLI.RELACAOENTIDADE = RELLOCAL.PAPEL2
)
INNER JOIN ENTIDADE AS ENTCLI ON (
    ENTCLI.ENTIDADE = RELCLI.PAPEL1
)
LEFT JOIN LIGAPOSTOLOCALAREASUPER
    INNER JOIN RELACAOENTIDADE AS RELAREASUPERVISAO ON (
        RELAREASUPERVISAO.RELACAOENTIDADE =
        LIGAPOSTOLOCALAREASUPER.AREASUPERVISAO
    )
    INNER JOIN ENTIDADE AS ENTAREASUPERVISAO ON (
        ENTAREASUPERVISAO.ENTIDADE = RELAREASUPERVISAO.PAPEL1
    )
ON (
    LIGAPOSTOLOCALAREASUPER.POSTOLOCALSERVICO =
    POSTOLOCALSERVICO.POSTOLOCALSERVICO
    AND LIGAPOSTOLOCALAREASUPER.TURNOTRABALHO =
    VAGAITEMCONTRATO.TURNOTRABALHO
    AND LIGAPOSTOLOCALAREASUPER.SITUACAO = 1
)
GROUP BY
    PONTO.DATA,
    ENTEMP.NOMERESUMIDO,
    ENTBASE.NOMERESUMIDO,
    ENTCLI.NOMERESUMIDO,
    ENTLOCAL.NOMERESUMIDO,
    ENTAREASUPERVISAO.NOMECOMPLETO,
    TURNOTRABALHO.DESCRICAO,
    ENTFUNC.NOMERESUMIDO,
    CARGO.DESCRICAO
"""


# ===============================
# CONEXÃO GOOGLE SHEETS
# Autentica usando a service account e retorna o client do gspread.
# O escopo 'spreadsheets' permite leitura e escrita em qualquer planilha
# que tenha sido compartilhada com o e-mail da service account.
# ===============================
def conectar_sheets():
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE, scopes=scopes
    )
    return gspread.authorize(creds)


# ===============================
# MAIN
# Orquestra todo o fluxo: banco → transformação → sheets.
# Cada chamada à API do Sheets está embrulhada em retry_with_backoff
# para lidar com o erro 429 (quota excedida) sem derrubar o job.
# ===============================
def main():
    try:
        logging.info("Iniciando processo")

        # --- EXTRAÇÃO ---
        logging.info("Conectando no SQL Server")
        engine = conectar_bd()

        logging.info("Executando query")
        # O engine SQLAlchemy elimina o UserWarning do pandas >= 2.0
        # que reclamava do uso de conexões pyodbc diretamente.
        # O 'with' garante que a conexão seja fechada ao sair do bloco.
        with engine.connect() as conn:
            df = pd.read_sql(QUERY, conn)

        logging.info(f"Registros retornados: {len(df)}")

        # --- TRANSFORMAÇÃO ---
        # Converte colunas datetime para string no formato padrão.
        # O Google Sheets não aceita objetos datetime nativos do pandas.
        for col in df.select_dtypes(include=["datetime64[ns]"]).columns:
            df[col] = df[col].dt.strftime("%Y-%m-%d %H:%M:%S")

        # Remove infinitos e NaN — o Sheets também não aceita esses valores.
        # fillna("") substitui NaN por string vazia.
        # astype(str) garante que tudo seja texto puro antes de enviar.
        df = df.replace([np.inf, -np.inf], "")
        df = df.fillna("")
        df = df.astype(str)

        # --- CARGA (GOOGLE SHEETS) ---
        logging.info("Conectando no Google Sheets")
        gc = conectar_sheets()

        # Abre a planilha pelo ID.
        # Embrulhado em retry pois essa chamada já faz uma leitura na API.
        @retry_with_backoff(max_retries=5, base_delay=2)
        def abrir_planilha():
            return gc.open_by_key(SPREADSHEET_ID)

        sh = abrir_planilha()

        # Tenta abrir a aba pelo nome. Se não existir, cria e adiciona o cabeçalho.
        # WorksheetNotFound não precisa de retry — é erro de lógica, não de quota.
        try:
            ws = sh.worksheet(WORKSHEET_NAME)
            logging.info("Aba encontrada no Sheets")
        except gspread.exceptions.WorksheetNotFound:
            logging.info("Aba não encontrada, criando nova")
            ws = sh.add_worksheet(title=WORKSHEET_NAME, rows=1000, cols=25)

            # Escreve o cabeçalho na primeira linha (só na criação da aba).
            # values primeiro, range_name segundo — nova assinatura do gspread >= 6.
            @retry_with_backoff(max_retries=5, base_delay=2)
            def escrever_cabecalho():
                ws.update([df.columns.tolist()], "A1")

            escrever_cabecalho()

        # Limpa os dados antigos antes de escrever os novos.
        # IMPORTANTE: não usamos get_all_values() aqui — essa leitura era
        # desnecessária e contribuía para estourar a quota.
        # Em vez disso, calculamos o range com base no tamanho do DataFrame
        # atual + uma margem de 100 linhas pra garantir que sobras de runs
        # anteriores com mais registros também sejam apagadas.
        @retry_with_backoff(max_retries=5, base_delay=2)
        def limpar_dados():
            end_row = len(df) + 100  # margem pra cobrir sobras do run anterior
            ws.batch_clear([f"A2:J{end_row}"])

        logging.info("Limpando dados antigos")
        limpar_dados()

        # Pausa entre o clear e o update pra dar respiro entre chamadas
        # à API e reduzir chance de acumular outro 429 logo em seguida.
        time.sleep(2)

        # Escreve os novos dados a partir da linha 2 (linha 1 = cabeçalho).
        # Nova assinatura do gspread >= 6: values primeiro, range_name segundo.
        @retry_with_backoff(max_retries=5, base_delay=2)
        def escrever_dados():
            ws.update(df.values.tolist(), "A2")

        logging.info("Escrevendo dados novos")
        escrever_dados()

        logging.info("Job finalizado com sucesso")

    except Exception:
        # Loga o traceback completo antes de propagar a exceção.
        # Assim o erro fica registrado no .log mesmo sem acesso ao terminal.
        logging.exception("Erro fatal na execução do job")
        raise


# ===============================
# EXECUÇÃO
# Garante que o main() só rode quando o script for chamado diretamente,
# não quando for importado como módulo em outro script.
# ===============================
if __name__ == "__main__":
    main()
