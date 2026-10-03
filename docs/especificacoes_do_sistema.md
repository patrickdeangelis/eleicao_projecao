# Especificação Técnica de Requisitos e Arquitetura do Sistema (SRS)
## Sistema de Projeção Eleitoral em Tempo Real (SPETR) - Desktop Dashboard

**Versão:** 1.1.0  
**Data:** Outubro de 2026  
**Status:** Aprovado para Implementação  
**Classificação:** Especificação de Engenharia de Software e Modelagem Estatística

---

## Sumário

1. [Visão Geral e Objetivos do Sistema](#1-visão-geral-e-objetivos-do-sistema)
2. [Requisitos Funcionais (RF)](#2-requisitos-funcionais-rf)
3. [Requisitos Não Funcionais (RNF)](#3-requisitos-não-funcionais-rnf)
4. [Arquitetura de Componentes do Sistema Desktop](#4-arquitetura-de-componentes-do-sistema)
   - [4.1. Pilha Tecnológica Desktop Recomendada](#41-pilha-tecnológica-desktop-recomendada)
5. [Especificação dos Contratos de Dados](#5-especificação-dos-contratos-de-dados)
6. [Especificação dos Endpoints da API Interna](#6-especificação-dos-endpoints-da-api-interna)
7. [Estratégia de Rede e Controle de Pacing](#7-estratégia-de-rede-e-controle-de-pacing)
8. [Plano de Validação e Testes Pré-Eleição](#8-plano-de-validação-e-testes-pré-eleição)
9. [Empacotamento Standalone e Matriz de Build Multiplataforma](#9-empacotamento-standalone-e-matriz-de-build-multiplataforma)

---

## 1. Visão Geral e Objetivos do Sistema

### 1.1. Propósito
O **Sistema de Projeção Eleitoral em Tempo Real (SPETR)** é uma **aplicação desktop analítica de alta performance** voltada para mesas de apuração, analistas de dados e operadores que necessitam acompanhar e antecipar o resultado de eleições majoritárias (presidenciais e governamentais) a partir das parciais divulgadas em formato JSON pela CDN do Tribunal Superior Eleitoral (TSE).

A aplicação roda **localmente na estação de trabalho do usuário**, executando em segundo plano a coleta escalonada, a decomposição em 4 níveis (Cidades > 100k, Interior, UF e Brasil) e a simulação de Monte Carlo, exibindo em uma interface gráfica desktop rica, fluida e responsiva (60 FPS) a projeção probabilística do resultado com apenas **10% a 15% das urnas apuradas**.

### 1.2. Metas de Desempenho e Precisão
1. **Convergência Antecipada:** Apresentar projeção estatística estável (erro médio < 1,5 p.p. em relação ao resultado final) com apenas 15% das urnas nacionais apuradas.
2. **Segurança do IP do Usuário:** Como o aplicativo roda na máquina local do analista (utilizando a internet residencial ou corporativa), a taxa de saída é mantida estritamente entre **9 e 12 requisições por segundo**, consumindo menos de 12% do teto do TSE (100 req/s) e eliminando qualquer risco de ban de IP do usuário.
3. **Fluidez de Interface (60 FPS):** A interface desktop nunca deve travar ou sofrer engasgos (*UI freezing*) durante as requisições de rede ou as 10.000 iterações do cálculo estocástico.
4. **Persistência Local e Replay:** Todos os snapshots coletados a cada 20 segundos são salvos em banco de dados local leve (SQLite / DuckDB), permitindo retroceder no tempo (*Time-Travel Replay*) para auditar o momento exato de cada virada matemática.

---

## 2. Requisitos Funcionais (RF)

| ID | Nome | Descrição | Prioridade |
| :--- | :--- | :--- | :---: |
| **RF-01** | Carga Prévia de Metadados | Carregar previamente o cadastro de eleitores aptos e histórico eleitoral das 27 UFs e de todas as cidades com > 100k eleitores a partir de arquivo local embutido. | **Crítica** |
| **RF-02** | Coletor Desktop com Pacing | O worker local em segundo plano deve consultar de forma não-bloqueante as 27 UFs e as ~154 cidades com > 100k eleitores a cada 15 a 20 segundos (`asyncio.Semaphore(15)`). | **Crítica** |
| **RF-03** | Otimização HTTP 304 | O coletor deve enviar cabeçalhos `If-Modified-Since` e `If-None-Match` baseados nos metadados da última resposta, ignorando arquivos inalterados (status 304). | **Alta** |
| **RF-04** | Subtração Vetorial do Interior | Computar o estrato "Interior Remanescente" para cada UF subtraindo os totais das cidades > 100k do total consolidado estadual. | **Crítica** |
| **RF-05** | Cálculo da Taxa de Comparecimento | Recalcular dinamicamente a taxa de comparecimento e os votos válidos restantes ($\hat{V}_k^{\text{rem}}$) para cada um dos 181 estratos. | **Alta** |
| **RF-06** | Inferência Bayesiana Sequencial | Atualizar analiticamente os parâmetros da distribuição conjugada Dirichlet-Multinomial com os votos nominais apurados em cada estrato. | **Crítica** |
| **RF-07** | Simulação de Monte Carlo | Executar 10.000 iterações estocásticas vetorizadas via NumPy a cada novo lote, simulando o preenchimento de todos os votos faltantes do país. | **Crítica** |
| **RF-08** | Painel Desktop Nacional | Exibir em tempo real: Placar Oficial do TSE, Projeção Estatística Média, Intervalo de Credibilidade de 95% [P2.5, P97.5] e Probabilidade Matemática de Vitória. | **Crítica** |
| **RF-09** | Painel Detalhado por Estado | Permitir ao usuário selecionar qualquer UF e inspecionar a abertura da apuração e projeção por cidade > 100k (ex: João Pessoa vs. Campina Grande vs. Resto da PB). | **Alta** |
| **RF-10** | Gráfico de Convergência Temporal | Renderizar gráfico de linha em tempo real mostrando a evolução da apuração bruta comparada à projeção estatística e sua faixa de incerteza (IC 95%). | **Alta** |
| **RF-11** | Modo Time-Travel (Replay) | Permitir ao usuário arrastar uma barra de tempo para rever o estado da apuração e da projeção em qualquer minuto passado da eleição. | **Média** |
| **RF-12** | Emissão de Alerta (Call Decision) | Destacar visualmente e sonoramente na interface quando um candidato atingir $P(\text{Vitória}) \ge 99.5\%$ e o IC 95% descolar acima de 50,00%. | **Média** |
| **RF-13** | Empacotamento Auto-Contido | O sistema deve ser distribuído como binário executável único e auto-contido para cada sistema operacional (Windows `.exe`, Linux `.AppImage`, macOS `.app`), sem exigir instalação prévia de Python ou dependências. | **Crítica** |

---

## 3. Requisitos Não Funcionais (RNF)

| ID | Categoria | Descrição |
| :--- | :--- | :--- |
| **RNF-01** | **Segurança de Rede Local** | O coletor nunca deve gerar rajadas (*bursts*) superiores a 15 req/s instantâneas, protegendo a conexão de internet da máquina do usuário contra bloqueios de IP do WAF do TSE. |
| **RNF-02** | **Desacoplamento de Threads** | O Coletor de Rede e o Motor de Monte Carlo devem rodar em threads/processos separados da Thread de Interface Gráfica (UI Thread), comunicando-se por fila de eventos ou sinais. |
| **RNF-03** | **Performance e Tempo de Ciclo** | A coleta completa e a simulação de 10.000 iterações devem ser concluídas em menos de 2,5 segundos, com consumo de CPU inferior a 25% em processadores quad-core modernos. |
| **RNF-04** | **Persistência Local Embutida** | Utilizar banco de dados embutido local (SQLite em modo WAL ou DuckDB) sem necessidade de instalação de servidores externos de banco de dados. |
| **RNF-05** | **Portabilidade Desktop** | A aplicação deve ser compatível nativamente com os principais sistemas operacionais desktop (Linux, Windows 10/11 e macOS). |
| **RNF-06** | **Tolerância a Quedas de Conexão** | Se a conexão de internet do usuário oscilar temporariamente, a interface deve exibir um indicador discreto de reconexão e manter na tela o último estado válido sem travar. |
| **RNF-07** | **Zero Dependências Externas** | O executável final gerado deve embutir o interpretador Python, NumPy, SQLite, bibliotecas de rede e todos os arquivos estáticos, permitindo execução imediata via duplo-clique. |

---

## 4. Arquitetura de Componentes do Sistema

```
                     +─────────────────────────────────────────────────────────────+
                     |                CDN TSE (resultados.tse.jus.br)               |
                     +─────────────────────────────────────────────────────────────+
                                                    │
                                   HTTP/2 Paced (9 a 12 req/s contínuas)
                                   Cabeçalhos: If-Modified-Since / If-None-Match
                                                    │
                                                    v
+═══════════════════════════════════════════════════════════════════════════════════════════════════+
║                             ESTAÇÃO DE TRABALHO LOCAL (DESKTOP APP)                               ║
║                                                                                                   ║
║  +─────────────────────────────────────────────────────────────────────────────────────────────+  ║
║  |                           THREAD DE BACKGROUND (WORKER ANALÍTICO)                           |  ║
║  |                                                                                             |  ║
║  |   +──────────────────────────────+                +──────────────────────────────────────+  |  ║
║  |   |  Coletor Paced (httpx async) |                |  Decompositor Vetorial               |  |  ║
║  |   |  - 27 Totais Estaduais (UFs) | ─────────────> |  Interior_UF = Total_UF - Σ Cidades  |  |  ║
║  |   |  - ~154 Cidades > 100k       |                |  Matriz de 181 Estratos              |  |  ║
║  |   +──────────────────────────────+                +──────────────────────────────────────+  |  ║
║  |                                                                   │                         |  ║
║  |                                                                   v                         |  ║
║  |   +──────────────────────────────+                +──────────────────────────────────────+  |  ║
║  |   |  Motor Dirichlet-Multinomial | ─────────────> |  Simulador Monte Carlo (NumPy C-API) |  |  ║
║  |   |  α_post = α_prior + V_obs    |                |  10.000 Amostragens de Votos Restantes|  |  ║
║  |   +──────────────────────────────+                +──────────────────────────────────────+  |  ║
║  +─────────────────────────────────────────────────────────────────────────────────────────────+  ║
║                                              │                                                    ║
║                                 Barramento Local (In-Process / IPC)                                ║
║                                              │                                                    ║
║                        +─────────────────────┴─────────────────────+                              ║
║                        │                                           │                              ║
║                        v                                           v                              ║
║       +──────────────────────────────────+        +──────────────────────────────────+            ║
║       |  BANCO LOCAL EMBUTIDO (SQLite)   |        |  INTERFACE DESKTOP (GUI 60 FPS)  |            ║
║       |  - Tabela: snapshots_apuracao    |        |  - Painel Geral Brasil           |            ║
║       |  - Tabela: projecoes_historico   |        |  - Drill-down Estadual e Cidades |            ║
║       |  - Permite Time-Travel Replay    |        |  - Curvas ECharts / Densidades   |            ║
║       +──────────────────────────────────+        +──────────────────────────────────+            ║
+═══════════════════════════════════════════════════════════════════════════════════════════════════+
```

### 4.1. Pilha Tecnológica Desktop Recomendada
A arquitetura desktop suporta duas abordagens de implementação:

1. **Abordagem Híbrida de Alta Estética (Recomendada: PyWebView + FastAPI Local + Apache ECharts):**
   * **Visual:** Qualidade de estúdio de televisão (*Decision Desk*), com gráficos de densidade com gradientes, mapas coropléticos interativos do Brasil e das UFs, barras de progresso com animação suave via CSS/Tailwind.
   * **Execução:** O backend FastAPI roda em porta efêmera em `localhost` gerenciando o worker assíncrono; a janela desktop é renderizada nativamente pelo motor webview do sistema operacional (WebKit no Linux/macOS, WebView2 no Windows), sem sobrecarga de um navegador aberto.
2. **Abordagem Nativa Clássica (PySide6 / Qt):**
   * **Visual:** Componentes nativos Qt6 com integração direta de `QtCharts` ou `PyQtGraph`.
   * **Vantagens:** Empacotamento direto em binário único sem dependência de webview.

---

## 5. Especificação dos Contratos de Dados

### 5.1. Modelo do Estrato Eleitoral (Configuração Prévia)
```json
{
  "codigo_ibge": "2504009",
  "codigo_tse": "20516",
  "nome": "Campina Grande",
  "uf": "PB",
  "tipo": "CIDADE_POLO",
  "eleitores_aptos": 290450,
  "secoes_totais": 894,
  "comparecimento_historico": 0.8120,
  "priors": {
    "candidato_a": 0.4850,
    "candidato_b": 0.5150
  },
  "peso_prior": 500.0
}
```

### 5.2. Payload do Evento de Projeção (SSE Stream / API Output)
```json
{
  "timestamp": "2026-10-04T18:24:32-03:00",
  "ciclo_id": 48,
  "apuracao_oficial": {
    "secoes_totalizadas": 142050,
    "secoes_totais": 472075,
    "percentual_apurado": 30.09,
    "votos_validos_computados": 35210400,
    "placar_bruto": {
      "candidato_a": { "votos": 16513677, "pct": 46.90 },
      "candidato_b": { "votos": 18696723, "pct": 53.10 }
    }
  },
  "projecao_estatistica": {
    "metodologia": "Bayesian Stratified Dirichlet-Multinomial (10k MC)",
    "votos_validos_finais_esperados": 118450000,
    "candidatos": {
      "candidato_a": {
        "numero": "13",
        "nome": "CANDIDATO A",
        "projecao_media_pct": 52.48,
        "intervalo_credibilidade_95": [51.30, 53.65],
        "votos_finais_estimados": 62162560,
        "probabilidade_vitoria": 99.82
      },
      "candidato_b": {
        "numero": "22",
        "nome": "CANDIDATO B",
        "projecao_media_pct": 47.52,
        "intervalo_credibilidade_95": [46.35, 48.70],
        "votos_finais_estimados": 56287440,
        "probabilidade_vitoria": 0.18
      }
    },
    "call_decision": {
      "status": "CHAMADA_CONFIRMADA",
      "vencedor_projetado": "candidato_a",
      "motivo": "P(Vitória) >= 99.5% e limite inferior do IC 95% estritamente superior a 50.0%"
    }
  }
}
```

---

## 6. Especificação dos Endpoints da API Interna

A aplicação backend deve expor as seguintes rotas HTTP/REST e streaming:

### 1. `GET /api/v1/projecao/nacional`
* **Descrição:** Retorna o último snapshot consolidado da projeção presidencial do país.
* **Formato de Resposta:** `application/json` (conforme Seção 5.2).
* **Cache:** `Cache-Control: public, max-age=5`.

### 2. `GET /api/v1/projecao/estados/{uf}`
* **Descrição:** Retorna a projeção detalhada para a eleição presidencial ou de governador em uma UF específica, exibindo a decomposição da Capital, das Cidades > 100k e do Interior Remanescente.
* **Exemplo:** `/api/v1/projecao/estados/pb`
* **Formato de Resposta:** `application/json` com abertura por estrato local.

### 3. `GET /api/v1/projecao/stream`
* **Descrição:** Canal Server-Sent Events (SSE) contínuo.
* **Headers:** `Content-Type: text/event-stream`, `Connection: keep-alive`, `Cache-Control: no-cache`.
* **Comportamento:** Dispara um evento do tipo `projecao_update` a cada ciclo computado onde `hg` (hora de geração) ou os totais de votos sofrerem alteração.

### 4. `GET /api/v1/historico/convergencia`
* **Descrição:** Retorna a série histórica minuto a minuto da apuração bruta comparada à projeção estatística para renderização de gráficos de evolução temporal.

---

## 7. Estratégia de Rede e Controle de Pacing

### 7.1. Matriz de Coleta em Dois Ritmos (Tiered Polling)
Para garantir atualização sem sobrecarregar a CDN:

1. **Camada 1 (Macro e Capitais - 55 Alvos):**
   * Alvos: 27 consolidados de UF + 27 arquivos de Capitais + 1 Consolidado Nacional.
   * Frequência: **A cada 15 segundos**.
   * Pacing: ~3,6 requisições por segundo.
2. **Camada 2 (Pólos Regionais > 100k - ~125 Cidades Restantes):**
   * Alvos: Todas as cidades não-capitais com eleitorado $\ge 100.000$.
   * Frequência: **A cada 30 segundos**.
   * Pacing: ~4,2 requisições por segundo.

**Taxa Média Total:** $\approx \mathbf{7,8 \text{ a } 9,5 \text{ requisições/segundo}}$ contínuas.

### 7.2. Algoritmo de Pacing Seguro
O coletor deve utilizar controle de taxa em nível de socket:
```python
SEMAFORO_CONCORRENCIA = asyncio.Semaphore(15)  # Máximo de 15 conexões ativas
TIMEOUT_REQUISICAO = 6.0  # Segundos
INTERVALO_ENTRE_DISPAROS = 0.04  # 40 milissegundos de delay entre chamadas
```

---

## 8. Plano de Validação e Testes Pré-Eleição

1. **Simulado de Conexão com Dados Oficiais (`f="S"`):**
   * Durante a semana anterior ao pleito, o TSE transmite pacotes de teste no ambiente oficial com flag `"f": "S"`. O sistema deve ser executado por 4 horas ininterruptas monitorando latência, consumo de memória e ausência de bloqueios de IP.
2. **Teste de Replay Histórico (Eleição 2022 2º Turno):**
   * O sistema deve ser alimentado por um mock player que reproduz minuto a minuto os dados reais da eleição de 2022.
   * O teste será considerado **aprovado** se o modelo estabilizar a projeção de Lula (50,9%) com intervalo [50,1%, 51,8%] antes das 18h15 (horário em que a contagem bruta do TSE ainda marcava vitória provisória de Bolsonaro).
3. **Teste de Estresse da API (Conexões SSE):**
   * Executar teste com Locust ou k6 simulando 3.000 clientes conectados ao canal `/api/v1/projecao/stream` com consumo de CPU do servidor web mantido abaixo de 40%.

---

## 9. Empacotamento Standalone e Matriz de Build Multiplataforma

Para garantir que o usuário final execute a aplicação sem necessidade de instalar interpretador Python, compiladores ou dependências de pacotes via `pip`:

### 9.1. Estratégia de Empacotamento com PyInstaller
O empacotamento deve consolidar o interpretador Python embutido, a biblioteca NumPy compilada em C, o SQLite nativo e a árvore de arquivos estáticos (HTML/CSS/JS/Tailwind/ECharts):

```bash
# Comando de compilação em arquivo único sem terminal
pyinstaller --noconfirm --onedir --windowed \
    --name "SPETR_Apuracao" \
    --add-data "ui/dist:ui/dist" \
    --add-data "data/priors.json:data" \
    --icon "assets/icon.png" \
    main.py
```

* **Modo `--onedir` vs. `--onefile`:** 
  * Recomenda-se empacotar em diretório de distribuição (`--onedir`) zipado ou instalador (`InnoSetup` para Windows, `.dmg` para Mac, `.AppImage` para Linux), pois inicializa em menos de 1 segundo (evitando a descompactação temporária de 40 MB em `/tmp` a cada abertura).

### 9.2. Matriz de Build Automática (GitHub Actions CI/CD)
Como bibliotecas com extensões C (como NumPy e SQLite) exigem compilação nativa no sistema operacional de destino, a geração dos 3 executáveis deve ser automatizada via pipeline de CI/CD:

```yaml
# .github/workflows/release.yml
name: Build Multiplataforma

on:
  push:
    tags:
      - 'v*'

jobs:
  build:
    strategy:
      matrix:
        os: [ubuntu-latest, windows-latest, macos-latest]
        include:
          - os: ubuntu-latest
            artifact_name: spetr-linux
            asset_name: SPETR-Linux-x86_64.AppImage
          - os: windows-latest
            artifact_name: spetr-windows
            asset_name: SPETR-Windows-x64.exe
          - os: macos-latest
            artifact_name: spetr-macos
            asset_name: SPETR-macOS-Universal.dmg

    runs-on: ${{ matrix.os }}

    steps:
      - uses: actions/checkout@v4

      - name: Configurar Python 3.11
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'
          cache: 'pip'

      - name: Instalar Dependências
        run: |
          pip install -r requirements.txt
          pip install pyinstaller

      - name: Compilar Binário Nativo
        run: pyinstaller --noconfirm spetr.spec

      - name: Publicar Release
        uses: softprops/action-gh-release@v1
        with:
          files: dist/${{ matrix.asset_name }}
```

Com esse fluxo, o usuário final baixa o arquivo compilado nativamente para sua plataforma, executa com um duplo clique e o sistema inicia imediatamente em janela própria.
