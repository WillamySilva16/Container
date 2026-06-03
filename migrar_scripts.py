"""
migrar_scripts.py
-----------------
Roda na raiz do projeto e corrige automaticamente todos os scripts Python:

  1. Remove o bloco sys.path.append(...) e qualquer lixo residual
  2. Troca SERVICE_ACCOUNT_FILE = "qualquer-coisa.json" por "/app/credentials.json"
  3. Troca o env_path + load_dotenv(env_path) por load_dotenv()
  4. Remove o import sys se não for mais usado

Uso:
    python migrar_scripts.py

Um backup .bak é criado antes de cada alteração.
"""

import os
import re
import shutil

IGNORAR_PASTAS = {"shared", "envs", ".git", "__pycache__", ".venv", "venv"}
IGNORAR_ARQUIVOS = {"migrar_scripts.py"}

# 1a. Remove bloco sys.path.append( ... ) completo
PATTERN_SYSPATH = re.compile(
    r"sys\.path\.append\(\s*\n?"
    r"(?:.*\n)*?.*?\)\s*\n?",
    re.MULTILINE,
)

# 1b. Remove lixo residual antes de "from monitor import"
# Captura linhas com ), strings, vírgulas que sobram do sys.path.append
PATTERN_SYSPATH_ANTES_MONITOR = re.compile(
    r'(?:^[ \t]*(?:[,\)"\']|os\.path\.).*\n){1,6}(?=from monitor import)',
    re.MULTILINE,
)

# 2. Troca SERVICE_ACCOUNT_FILE = "qualquer.json"
PATTERN_SA_FILE = re.compile(
    r'SERVICE_ACCOUNT_FILE\s*=\s*["\'][^"\']+\.json["\']'
)

# 3. Remove bloco BASE_DIR + env_path + load_dotenv(env_path)
PATTERN_ENV_BLOCK = re.compile(
    r"BASE_DIR\s*=.*\n"
    r"[ \t]*\n?"
    r"env_path\s*=\s*os\.path\.abspath\(\s*\n?"
    r"(?:.*\n)*?.*?\)\s*\n?"
    r"[ \t]*\n?"
    r"load_dotenv\(env_path\)\s*\n?",
    re.MULTILINE,
)

# 4. load_dotenv(env_path) solto (fallback)
PATTERN_LOAD_DOTENV = re.compile(r"load_dotenv\(env_path\)")

# 5. Remove "import sys" se não for mais usado
PATTERN_IMPORT_SYS = re.compile(r"^import sys\s*\n", re.MULTILINE)


def corrigir_arquivo(path: str) -> bool:
    with open(path, "r", encoding="utf-8") as f:
        original = f.read()

    texto = original

    # 1a. Remove sys.path.append completo
    texto = PATTERN_SYSPATH.sub("", texto)

    # 1b. Remove lixo residual antes de from monitor import
    texto = PATTERN_SYSPATH_ANTES_MONITOR.sub("", texto)

    # 2. Troca SERVICE_ACCOUNT_FILE
    texto = PATTERN_SA_FILE.sub(
        'SERVICE_ACCOUNT_FILE = "/app/credentials.json"', texto
    )

    # 3. Remove bloco BASE_DIR / env_path / load_dotenv(env_path)
    texto = PATTERN_ENV_BLOCK.sub("load_dotenv()\n", texto)

    # 4. Fallback load_dotenv(env_path) solto
    texto = PATTERN_LOAD_DOTENV.sub("load_dotenv()", texto)

    # 5. Remove import sys se não usado
    if "import sys" in texto:
        sem_import = re.sub(r"^import sys\s*\n", "", texto, flags=re.MULTILINE)
        if not re.search(r"\bsys\b", sem_import):
            texto = PATTERN_IMPORT_SYS.sub("", texto)

    # Remove linhas em branco excessivas
    texto = re.sub(r"\n{3,}", "\n\n", texto)

    if texto == original:
        return False

    shutil.copy2(path, path + ".bak")

    with open(path, "w", encoding="utf-8") as f:
        f.write(texto)

    return True


def encontrar_scripts(raiz: str):
    encontrados = []
    for dirpath, dirnames, filenames in os.walk(raiz):
        dirnames[:] = [d for d in dirnames if d not in IGNORAR_PASTAS]
        for filename in filenames:
            if filename.endswith(".py") and filename not in IGNORAR_ARQUIVOS:
                encontrados.append(os.path.join(dirpath, filename))
    return encontrados


def main():
    raiz = os.path.dirname(os.path.abspath(__file__))
    scripts = encontrar_scripts(raiz)

    print(f"\n🔍 {len(scripts)} scripts encontrados\n")

    alterados = []
    sem_alteracao = []

    for path in scripts:
        rel = os.path.relpath(path, raiz)
        try:
            if corrigir_arquivo(path):
                print(f"  ✅ Corrigido: {rel}")
                alterados.append(rel)
            else:
                print(f"  ⏭️  Sem alteração: {rel}")
                sem_alteracao.append(rel)
        except Exception as e:
            print(f"  ❌ Erro em {rel}: {e}")

    print(f"\n{'─'*50}")
    print(f"✅ Corrigidos:      {len(alterados)}")
    print(f"⏭️  Sem alteração:   {len(sem_alteracao)}")
    print(f"\nBackups salvos com extensão .bak")
    print("Revise os arquivos antes de subir o Docker!\n")


if __name__ == "__main__":
    main()
