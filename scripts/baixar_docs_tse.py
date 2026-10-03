"""
Script para download completo da documentação técnica oficial da divulgação de resultados do TSE.
"""
import os
import re
import httpx
from bs4 import BeautifulSoup
from urllib.parse import urljoin

DOCS_DIR = os.path.abspath("docs")
TSE_OFICIAL_DIR = os.path.join(DOCS_DIR, "tse_oficial")
os.makedirs(TSE_OFICIAL_DIR, exist_ok=True)

PAGE_URL = "https://www.tse.jus.br/eleicoes/informacoes-tecnicas-sobre-a-divulgacao-de-resultados?tab=ancora-1"

headers = {
    'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64; rv:130.0) Gecko/20100101 Firefox/130.0',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
    'Accept-Language': 'pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7',
    'Referer': PAGE_URL,
    'Sec-Fetch-Dest': 'document',
    'Sec-Fetch-Mode': 'navigate',
    'Sec-Fetch-Site': 'same-origin',
    'Sec-Fetch-User': '?1',
    'Upgrade-Insecure-Requests': '1',
}

# Lista de documentos oficiais a baixar
DOCS_TSE = [
    ("apresentacao-interessados-2026.pdf", "https://www.tse.jus.br/eleicoes/eleicoes-2026-content/arquivos/divulgacao-de-resultados/apresentacao-interessados-2026-pdf"),
    ("tse-instrucoes-para-download-dos-arquivos-da-divulgacao-2026.pdf", "https://www.tse.jus.br/eleicoes/eleicoes-2026-content/arquivos/divulgacao-de-resultados/tse-instrucoes-para-download-dos-arquivos-da-divulgacao-2026"),
    ("tse-ea10-arquivo-de-resultado-de-eleitos.pdf", "https://www.tse.jus.br/eleicoes/eleicoes-2026-content/arquivos/divulgacao-de-resultados/tse-ea10-arquivo-de-resultado-de-eleitos"),
    ("tse-ea11-arquivo-de-configuracao-de-eleicoes.pdf", "https://www.tse.jus.br/eleicoes/eleicoes-2026-content/arquivos/divulgacao-de-resultados/tse-ea11-arquivo-de-configuracao-de-eleicoes"),
    ("tse-ea12-arquivo-de-configuracao-de-municipios.pdf", "https://www.tse.jus.br/eleicoes/eleicoes-2026-content/arquivos/divulgacao-de-resultados/tse-ea12-arquivo-de-configuracao-de-municipios"),
    ("tse-ea14-arquivo-de-acompanhamento-brasil.pdf", "https://www.tse.jus.br/eleicoes/eleicoes-2026-content/arquivos/divulgacao-de-resultados/tse-ea14-arquivo-de-acompanhamento-brasil"),
    ("tse-ea15-arquivo-de-acompanhamento-uf.pdf", "https://www.tse.jus.br/eleicoes/eleicoes-2026-content/arquivos/divulgacao-de-resultados/tse-ea15-arquivo-de-acompanhamento-uf"),
    ("tse-ea16-arquivo-de-configuracao-de-secoes-eleitorais.pdf", "https://www.tse.jus.br/eleicoes/eleicoes-2026-content/arquivos/divulgacao-de-resultados/tse-ea16-arquivo-de-configuracao-de-secoes-eleitorais"),
    ("tse-ea18-arquivo-auxiliar-de-secao.pdf", "https://www.tse.jus.br/eleicoes/eleicoes-2026-content/arquivos/divulgacao-de-resultados/tse-ea18-arquivo-auxiliar-de-secao"),
    ("tse-ea20-arquivo-de-resultado-unificado.pdf", "https://www.tse.jus.br/eleicoes/eleicoes-2026-content/arquivos/divulgacao-de-resultados/tse-ea20-arquivo-de-resultado-unificado"),
    ("manual-verificacao-jws.pdf", "https://www.tse.jus.br/eleicoes/eleicoes-2026-content/arquivos/divulgacao-de-resultados/manual-verificacao-jws"),
    ("exemplos-de-arquivos-json.zip", "https://www.tse.jus.br/eleicoes/arquivos/exemplos-de-arquivos-json"),
    ("ele-c.json", "https://resultados-sim.tse.jus.br/simulado/simulado2026/comum/config/ele-c.json"),
    ("mun-e021270-cm.json", "https://resultados-sim.tse.jus.br/simulado/simulado2026/ele2026/21270/config/mun-e021270-cm.json"),
    ("br-e021270-ab.json", "https://resultados-sim.tse.jus.br/simulado/simulado2026/ele2026/21270/dados/br/br-e021270-ab.json"),
    ("br-c0001-e021270-u.json", "https://resultados-sim.tse.jus.br/simulado/simulado2026/ele2026/21270/dados/br/br-c0001-e021270-u.json"),
    ("ac-e021270-ab.json", "https://resultados-sim.tse.jus.br/simulado/simulado2026/ele2026/21270/dados/ac/ac-e021270-ab.json"),
    ("ac-c0003-e021272-u.json", "https://resultados-sim.tse.jus.br/simulado/simulado2026/ele2026/21272/dados/ac/ac-c0003-e021272-u.json"),
    ("ac01120-c0005-e021272-u.json", "https://resultados-sim.tse.jus.br/simulado/simulado2026/ele2026/21272/dados/ac/ac01120-c0005-e021272-u.json"),
]

def main():
    print("Iniciando sessão com o portal do TSE via HTTP/2...")
    with httpx.Client(http2=True, headers=headers, follow_redirects=True, timeout=30.0) as client:
        # 1. Abre a página inicial para carregar cookies e cabeçalhos de sessão
        r_init = client.get(PAGE_URL)
        print(f"Página TSE carregada: status {r_init.status_code}, tamanho {len(r_init.text)} bytes")

        # 2. Baixa cada documento oficial
        for filename, url in DOCS_TSE:
            dest_path = os.path.join(TSE_OFICIAL_DIR, filename)
            print(f"Baixando: {filename} de {url}...")
            try:
                # Tenta baixar direto ou com /@@download/file
                resp = client.get(url)
                if resp.status_code == 200 and len(resp.content) > 1000:
                    with open(dest_path, "wb") as f:
                        f.write(resp.content)
                    print(f"  -> Salvo com sucesso! ({len(resp.content):,} bytes)")
                else:
                    # Tenta com sufixo Plone @@download/file
                    alt_url = url.rstrip("/") + "/@@download/file"
                    resp_alt = client.get(alt_url)
                    if resp_alt.status_code == 200 and len(resp_alt.content) > 1000:
                        with open(dest_path, "wb") as f:
                            f.write(resp_alt.content)
                        print(f"  -> Salvo via @@download/file! ({len(resp_alt.content):,} bytes)")
                    else:
                        print(f"  -> Falha ({resp.status_code} / {resp_alt.status_code})")
            except Exception as e:
                print(f"  -> Erro ao baixar {filename}: {e}")

    # Remove arquivos corrompidos ou HTMLs de erro antigos
    for f in os.listdir(TSE_OFICIAL_DIR):
        fpath = os.path.join(TSE_OFICIAL_DIR, f)
        if f.endswith(".html") or "&t=" in f:
            try:
                os.remove(fpath)
            except Exception:
                pass

    print("\nDownload de todos os arquivos concluído com sucesso!")

if __name__ == "__main__":
    main()
