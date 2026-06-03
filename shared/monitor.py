import requests
import traceback

def run_with_monitor(main_function, ping_url):
    ping_ok = ping_url
    ping_fail = ping_url + "/fail"

    try:
        main_function()
        print("✅ Execução finalizada com sucesso")
        requests.get(ping_ok, timeout=10)

    except Exception:
        erro = traceback.format_exc()
        print("❌ ERRO NA EXECUÇÃO:\n", erro)

        try:
            requests.post(ping_fail, data=erro.encode("utf-8"), timeout=10)
        except Exception:
            pass

        raise