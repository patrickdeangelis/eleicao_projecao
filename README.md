# SPETR — Sistema de Projeção Eleitoral em Tempo Real

## Como rodar no modo desktop

### Pré-requisitos
- Python 3.11 ou superior
- No Linux, GTK e WebKitGTK instalados no sistema (necessários para a janela nativa). No Windows é usado o WebView2 (Edge) e no macOS o WebKit, que já vêm no sistema.

### Instalação
```bash
python3 -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### Execução
```bash
python3 main.py
```

A janela desktop abre na tela inicial, onde você escolhe a eleição (coleta real do TSE ou replay de uma apuração já gravada).

### Executável
Para abrir sem instalar nada, gere o executável e execute:
```bash
.venv/bin/python -m PyInstaller spetr.spec --clean --noconfirm
./dist/spetr
```

## Hospedagem (servidor público)

```bash
docker build -t eleicao-projecao .
docker run -p 8000:8000 -v spetr-data:/data eleicao-projecao                      # coleta real 2026, 2º turno
docker run -p 8000:8000 eleicao-projecao --modo real --ano 2026 --turno 1          # outro turno
```

`--publico` (já no `ENTRYPOINT`) deixa o painel somente leitura: `/sessao/iniciar`, `/sessao/parar` e `/projecao/versao` respondem 403 e `/docs` é desativado. A coleta começa sozinha ao subir. Use `--host 0.0.0.0` fora de contêiner para aceitar conexões externas. O histórico fica em `/data` (SQLite).
