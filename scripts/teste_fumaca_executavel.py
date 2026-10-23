"""
Teste de fumaça do executável gerado pelo PyInstaller (usado no CI e útil localmente).

Abre o binário sem janela e sem iniciar coleta, espera a API subir e confere a tela inicial,
a lista de opções da sessão e os arquivos do painel. Falha (código 1) se o executável não
subir, abortar ou não servir esses arquivos dentro do prazo.

    python scripts/teste_fumaca_executavel.py dist/spetr
    python scripts/teste_fumaca_executavel.py dist/spetr.exe
    python scripts/teste_fumaca_executavel.py dist/SPETR.app/Contents/MacOS/spetr
"""
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

PRAZO_SEGUNDOS = 120


def porta_livre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def obter(url: str, timeout: float = 5.0):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return r.status, r.read()


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    binario = os.path.abspath(sys.argv[1])
    if not os.path.isfile(binario):
        print(f"[FALHA] executável não encontrado: {binario}")
        return 1

    porta = porta_livre()
    base = f"http://127.0.0.1:{porta}"
    pasta = tempfile.mkdtemp(prefix="spetr-fumaca-")
    log_path = os.path.join(pasta, "saida.log")
    cmd = [binario, "--headless", "--simulacoes", "2000", "--porta", str(porta),
           "--db", os.path.join(pasta, "fumaca.sqlite")]
    print("[INFO] executando:", " ".join(cmd))

    with open(log_path, "w", encoding="utf-8", errors="replace") as log:
        proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, cwd=pasta)
        ok = False
        try:
            inicio = time.monotonic()
            while time.monotonic() - inicio < PRAZO_SEGUNDOS:
                if proc.poll() is not None:
                    print(f"[FALHA] o executável encerrou com código {proc.returncode}")
                    break
                try:
                    _, corpo = obter(f"{base}/api/v1/sessao")
                    sessao = json.loads(corpo)
                except OSError:
                    sessao = None
                if sessao is not None:
                    assert sessao["ativa"] is False, "sem --modo, nenhuma sessão deveria estar ativa"
                    assert sessao["opcoes"]["padroes_reais"]["ano"] == "2026"
                    print(f"[OK] API respondendo ({time.monotonic() - inicio:.0f}s)")
                    for caminho in ("/inicio", "/static/js/app.js", "/static/js/inicio.js", "/static/js/charts.js",
                                    "/static/js/vendor/echarts.min.js", "/static/geo/brasil-ufs.json", "/static/css/style.css"):
                        status, _ = obter(base + caminho)
                        assert status == 200, f"{caminho} respondeu {status}"
                    print("[OK] tela inicial e arquivos do painel servidos")
                    ok = True
                    break
                time.sleep(2)
            else:
                print(f"[FALHA] API não respondeu em {PRAZO_SEGUNDOS}s")
        finally:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    proc.kill()

    if not ok:
        print("----- saída do executável -----")
        with open(log_path, encoding="utf-8", errors="replace") as f:
            print(f.read()[-6000:])
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
