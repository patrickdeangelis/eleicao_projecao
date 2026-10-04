# SPETR — Sistema de Projeção Eleitoral em Tempo Real

<p align="center">
  <strong>Motor Estatístico Bayesiano & Dashboard Desktop Decision Desk para Apuração Eleitoral (TSE)</strong>
</p>

---

## 📌 Visão Geral

O **SPETR** é uma solução completa e de grau profissional para projeção e acompanhamento de resultados eleitorais em tempo real, baseada em dados abertos oficiais do Tribunal Superior Eleitoral (TSE).

Diferente de placares tradicionais que apenas exibem a soma das urnas que já chegaram, o SPETR utiliza **Pós-Estratificação em 4 Níveis**, **Inferência Bayesiana Sequencial (Dirichlet-Multinomial)** e **10.000 simulações de Monte Carlo por ciclo** para projetar com precisão matemática o resultado final antes que a apuração atinja a totalização.

### Destaques e Diferenciais
- **Estratificação por Cidades > 100k + Subtração Vetorial:** Isola os 221 municípios com ≥ 100 mil eleitores e as capitais (gerados do eleitorado oficial de 2026 por `scripts/gerar_metadados_eleitorado.py`) e calcula o "Interior Remanescente" por álgebra vetorial ($\text{Interior} = \text{Total}_{\text{UF}} - \sum \text{Cidades}_{>100\text{k}}$). Isso elimina distorções intrarregionais (como o caso paraibano: João Pessoa ~54% x Campina Grande ~48.5% x Sertão ~75%).
- **Proteção Total contra WAF do TSE:** Limite contínuo de 9 a 12 requisições por segundo com semáforo de concorrência (`asyncio.Semaphore(15)`) e cache condicional (`HTTP 304 / If-Modified-Since`), reduzindo o consumo de banda em mais de 85% e blindando o IP contra banimentos.
- **Motor Vetorizado:** Motor estatístico em NumPy que executa 10.000 eleições completas em **~0,2 s com 2 candidatos e ~0,8 s com 13 candidatos**, em thread separada para não travar a API/SSE.
- **Incerteza Realista:** além da posterior Dirichlet (com concentração limitada), o modelo aplica choques correlacionados por UF e nacionais e incerteza de comparecimento sobre os votos restantes — um empate técnico com 10% apurado não é anunciado.
- **Regra de Maioria Absoluta:** "vitória" significa > 50% dos votos válidos. No 1º turno o painel projeta *Segundo Turno* quando ninguém deve alcançar a maioria.
- **Arquitetura Desacoplada (Clean Architecture + Hexagonal):** O motor de cálculo não depende de banco ou rede; a comunicação é orquestrada por um barramento de eventos em memória (`EventBus`).
- **Persistência WAL & Time-Travel:** Banco de dados SQLite nativo configurado em modo WAL (*Write-Ahead Logging*), permitindo auditar qualquer ciclo passado sem travar o coletor.
- **Painel completo de apuração:** resultado real de todos os candidatos, curvas por atualização (apurado, projeção com IC 95%, probabilidades, ritmo), distribuições simuladas, "o que falta apurar", mapa das UFs, regiões, a heurística de estratos (capitais × cidades × interior) e tabela por UF — gráficos em **Apache ECharts 6** embutido no app (`spetr/ui/assets/js/vendor/`, sem CDN, funciona offline e no executável), nos temas claro e escuro. `?estatico=1` desenha sem stream (impressão) e `?tema=claro|escuro` força o tema.
- **Interface Desktop de Transmissão:** Dashboard estilo *Decision Desk* com animações a 60 FPS, Server-Sent Events (SSE), faixas visuais de incerteza (IC 95%), e *call decisions* automáticas (*Vitória Projetada*, *Segundo Turno Projetado* e *Matematicamente Eleito*). Chamadas estatísticas exigem ≥ 10% das seções e todas as UFs com dados.

---

## 🚀 Como Executar

### 1. Pré-requisitos
- Python 3.11+
- Virtualenv ou gerenciador `uv`

### 2. Instalação das Dependências
```bash
# Com uv (recomendado, ultra-rápido):
uv venv .venv
source .venv/bin/activate
uv pip install -r requirements.txt

# Ou com pip tradicional:
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3. Executando
```bash
python3 main.py                       # janela desktop, abre a tela inicial
python3 main.py --headless            # sem janela: acesse http://127.0.0.1:48291
```

A **tela inicial** pergunta como acompanhar a apuração:

1. **Coleta real** (padrão): baixa os arquivos oficiais do TSE. Ano, turno e código da eleição vêm pré-preenchidos (o código é descoberto pelo `ele-c.json` do TSE); as opções avançadas permitem trocar a URL da CDN, o ambiente e ativar a verificação JWS.
2. **Simular resultados**: sobe um servidor local que imita a CDN do TSE (candidatos fictícios sobre o eleitorado real de 2026), com cenário de 1º ou 2º turno, velocidade e % inicial. O painel ganha o botão **Controlar simulação** (pausar, avançar, pular para 50%/95%).

No painel, **Trocar modo** volta à tela inicial sem reiniciar o app (por exemplo: simular agora e passar para a coleta real quando a apuração começar). Para pular a tela inicial:

```bash
python3 main.py --modo real                          # coleta real direto
python3 main.py --modo real --eleicao 6257 --verificar-jws oficial
python3 main.py --modo simulado --cenario 1t --velocidade rapida
python3 main.py --modo real --ano 2022 --eleicao 545 --turno 2 --formato r   # eleição antiga (Dados Simplificados)
```

Antes do primeiro voto apurado o painel mostra "Aguardando o início da apuração" (os arquivos do TSE já existem, zerados) e nada é projetado.

| Opção | Padrão | Descrição |
|---|---|---|
| `--modo` | tela inicial | `real` ou `simulado`: inicia direto, sem a tela inicial |
| `--cenario` / `--velocidade` | `1t` / `normal` | Opções do modo simulado |
| `--ano` | `2026` | Ciclo eleitoral (`ele{ano}`) |
| `--eleicao` | descoberta automática | Código da eleição no TSE; obrigatório no formato `r` |
| `--cargo` | `1` | Código do cargo (1 = Presidente) |
| `--turno` | `1` | Turno usado na descoberta automática |
| `--formato` | `u` (2024+) / `r` | `u` = Resultado Unificado EA20 (`/dados/…-u.json`); `r` = Dados Simplificados (`/dados-simplificados/…-r.json`) |
| `--ambiente` | `oficial` | Pasta de ambiente na CDN |
| `--verificar-jws` | desativado | Baixa os pares `.jws` e valida a assinatura Ed25519 com a chave `oficial` ou `desenvolvimento` do manual do TSE |
| `--db` | `spetr_eleicoes.sqlite` | Banco de histórico (cada pleito e execução ficam identificados) |

### 4. Simulador isolado (opcional)
O mesmo simulador da tela inicial pode rodar como processo separado, para testar o coletor de rede contra outro servidor:
```bash
python3 scripts/mock_tse_server.py --cenario 1t --velocidade normal   # terminal 1 (painel em http://127.0.0.1:8080/)
python3 main.py --mock                                                 # terminal 2: coleta "real" apontando para :8080
```

### Atualizando os metadados de estratificação
Os arquivos `spetr/data/ufs_metadados.json`, `cidades_100k.json` e `municipios_meta.json` são gerados a partir do eleitorado oficial do TSE:
```bash
curl -LO https://cdn.tse.jus.br/estatistica/sead/odsele/eleitorado_locais_votacao/eleitorado_local_votacao_2026.zip
unzip eleitorado_local_votacao_2026.zip -d eleitorado
python3 scripts/gerar_metadados_eleitorado.py eleitorado --config-mun docs/tse_oficial/mun-e021270-cm.json
```

### 5. Executando o Replay Histórico de 2022
Para ver a projeção estatística convergindo em tempo real com dados da eleição presidencial de 2022:
```bash
python3 scripts/simular_apuracao_2022.py
```
Acesse `http://127.0.0.1:48291` para assistir à curva de probabilidade e às faixas de incerteza se estreitarem ao vivo.


---

## 🧪 Testes Automatizados

A suíte de testes valida cada componente de forma estritamente isolada:
```bash
pytest -v
```

Cobertura dos testes:
- `test_vector_subtraction.py`: Prova matemática da decomposição do interior (caso Paraíba).
- `test_bayesian_dirichlet.py`: Atualização de parâmetros $\boldsymbol{\alpha}_{\text{post}}$ e amostragem estocástica.
- `test_monte_carlo.py`: Performance de 10.000 iterações em < 200 ms e regras de Call Decision.
- `test_tse_parser.py`: Conversão de números brasileiros e exclusão de votos anulados (`dvt`) usando o JSON oficial do simulado 2026.
- `test_correcoes_auditoria.py`: URLs 2026 e descoberta via `ele-c.json`, regra de maioria absoluta, calibração da incerteza, UFs sem dados, consistência do Interior, pacing nas retentativas, JWS, histórico por execução e migração do banco.
- `test_full_pipeline_replay.py`: Teste de integração assíncrona ponta a ponta pelo `EventBus`.

---

## 📦 Gerando o Executável Standalone

O `spetr.spec` (PyInstaller) gera um executável único com Python, bibliotecas, painel, simulador e metadados embutidos. Quem recebe o arquivo não precisa instalar nada: basta abrir.

```bash
uv pip install pyinstaller                                   # dentro do .venv do projeto
.venv/bin/python -m PyInstaller spetr.spec --clean --noconfirm   # ~1 min; resultado em dist/spetr (≈ 67 MB no Linux)
./dist/spetr                                                 # tela inicial; ou ./dist/spetr --modo real
```

> **Use sempre o Python do `.venv`** (`.venv/bin/python -m PyInstaller`), não o comando `pyinstaller` solto: ele pode ser o do Python do sistema. No Fedora, o NumPy do sistema usa FlexiBLAS e o executável aborta ao abrir com `flexiblas Failed to load the BLAS fallback library`. O `spetr.spec` detecta esse caso e interrompe o build com a instrução correta.

- **Um build por sistema:** o PyInstaller não faz compilação cruzada. O workflow `.github/workflows/executaveis.yml` gera tudo no GitHub Actions:
  - **Manual:** aba *Actions* → *Executáveis* → *Run workflow*; os arquivos ficam em *Artifacts* da execução (30 dias).
  - **Versão:** `git tag v1.2.0 && git push origin v1.2.0` também cria uma *Release* com os arquivos anexados.
  - Gera `spetr-windows-x64.zip` (`spetr.exe`), `spetr-macos-arm64.zip` e `spetr-macos-x64.zip` (`SPETR.app`) e `spetr-linux-x64.tar.gz` (Ubuntu 22.04, glibc 2.35: roda em distros dessa geração em diante). Cada executável passa pelo teste de fumaça `scripts/teste_fumaca_executavel.py` antes de ser publicado.
- **macOS:** o spec gera `SPETR.app` (duplo-clique, sem Terminal; logs em `~/Library/Application Support/SPETR/spetr.log`). Sem assinatura/notarização da Apple, o macOS bloqueia na primeira abertura: clique com o botão direito → *Abrir*, ou libere em *Ajustes → Privacidade e Segurança*.
- **Windows sem console:** `SPETR_SEM_CONSOLE=1` antes do PyInstaller gera um `.exe` sem terminal (logs em `%APPDATA%\SPETR\spetr.log`).
- **Janela:** Linux usa GTK/WebKitGTK do sistema (o spec embute só o tema Adwaita e o idioma pt_BR); Windows usa o WebView2 (Edge), já presente no Windows 10/11; macOS usa o WebKit nativo. Sem janela disponível, o app abre o navegador padrão.
- **Banco de histórico:** no executável fica na pasta de dados do usuário (`~/.local/share/spetr`, `%APPDATA%\SPETR` ou `~/Library/Application Support/SPETR`); use `--db` para outro local.
- **Console:** `console=True` no spec mantém o terminal com os logs da coleta. Para esconder no Windows, troque para `console=False`.
- **Tamanho:** o spec exclui pacotes que entram por acidente (testes, Qt, temas de ícones do sistema). Se o build crescer muito, confira `build/spetr/warn-spetr.txt` e a lista `excludes`.

---

## 📚 Documentação Técnica Completa

Toda a fundamentação teórica, matemática e de arquitetura está disponível na pasta [`docs/`](docs/):
1. [Guia de Apuração TSE](docs/guia_apuracao_tse.md): Protocolos de rede, CDN Akamai, dicionário de campos.
2. [Modelo Estatístico e Ciência](docs/modelo_estatistico_projecao_apuracao.md): Modelagem Bayesiana, amostragem estratificada de Cochran e equações.
3. [Especificações do Sistema (SRS)](docs/especificacoes_do_sistema.md): Requisitos funcionais (RF), não funcionais (RNF) e contratos.
4. [Arquitetura de Módulos](docs/arquitetura_de_modulos.md): Diagrama de sequência, Clean Architecture e contratos de código.
