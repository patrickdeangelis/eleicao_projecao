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
- **Subestratificação do interior (MG Norte × Sul):** os 280 municípios do Norte de Minas (mesorregiões Noroeste, Norte de Minas, Jequitinhonha, Vale do Mucuri e Vale do Rio Doce, sem as cidades com mais de 100 mil eleitores) são baixados a cada 60 s; o Interior Sul sai da subtração ($\text{Sul} = \text{Interior} - \sum \text{Norte}$), só com arquivos do mesmo lote. Nas demais UFs, a versão subestratificada divide o estado em dois estratos (cidades grandes agrupadas e interior), então o cálculo nacional existe nas duas metodologias; a aba *Subestratos* tem um seletor de UF com o efeito da subestratificação em cada uma. Na versão subestratificada, as cidades grandes de MG também são agrupadas por região (Cidades Norte = Montes Claros, Governador Valadares, Ipatinga e Teófilo Otoni; Cidades Sul = as outras 15), e o estado fica em quatro estratos: cidades e interior do Norte, cidades e interior do Sul; a versão normal mantém cada cidade separada. O motor projeta as duas versões (normal e subestratificada) e o painel compara; a versão principal (padrão: subestratificada) define os números e a chamada e pode ser trocada na aba *Subestratos*. Lista gerada e validada no TSE por `scripts/gerar_subestratos.py`.
- **Aba *Modelos*:** 14 modelos lado a lado, em cards filtráveis por família, mais a evolução deles ao longo da apuração e uma tabela por UF com a projeção pela razão de crescimento (estratificação *Meu Modelo* por padrão, com seletor para a normal). **Monte Carlo:** Meu Modelo (o subestratificado, principal), Monte Carlo normal, Meu Modelo com choques regionais e Bayes puro (Dirichlet sem choques nem limite de concentração). **Estimadores:** parcial apurada, estimador direto, razão de crescimento (janelas de 5%, 15% e 30%), tendência temporal por estrato e Bayes hierárquico (encolhimento empírico para a média da UF). **Referência:** swing sobre uma eleição anterior (1º turno de 2026 para o 2º; 2022 para o 1º de 2026), resultado de eleição e nunca pesquisa, que depende do replay de referência preparado por `scripts/preparar_replay.py`. **Consenso e limites:** média, mediana e extremos dos modelos, e os limites matemáticos (melhor e pior caso). Tudo além do Meu Modelo e do Monte Carlo normal é leitura à parte: não entra no Monte Carlo, no intervalo nem na chamada. O mapa também ganhou o modo *Vantagem (crescimento)*.
- **Projeção extra por razão de crescimento:** para cada estrato e subestrato, votos ganhos por eleitor nas seções apuradas recentemente × eleitores que faltam. É só uma leitura à parte (aba *Crescimento*): não entra no Monte Carlo nem na chamada.
- **Proteção Total contra WAF do TSE:** Limite contínuo de 9 a 12 requisições por segundo com semáforo de concorrência (`asyncio.Semaphore(15)`) e cache condicional (`HTTP 304 / If-Modified-Since`), reduzindo o consumo de banda em mais de 85% e blindando o IP contra banimentos. Arquivos de município com 100% das seções apuradas deixam de ser pedidos (o lote reaproveita a última cópia; reconferência a cada 10 min). O teto do TSE é 100 req/s por IP, contando respostas 304.
- **Motor Vetorizado:** Motor estatístico em NumPy que executa 10.000 eleições completas em **~0,2 s com 2 candidatos e ~0,8 s com 13 candidatos**, em thread separada para não travar a API/SSE.
- **Incerteza Realista:** além da posterior Dirichlet (com concentração limitada), o modelo aplica choques correlacionados por UF e nacionais (σ = 0,06, calibrado no replay do 1º turno de 2026: o IC 95% passou a conter o resultado em 92% dos instantes, contra ~60% com os valores antigos) e incerteza de comparecimento sobre os votos restantes — um empate técnico com 10% apurado não é anunciado. Sem priors de pesquisa: cada estrato parte da média nacional observada.
- **Regra de Maioria Absoluta:** "vitória" significa > 50% dos votos válidos. No 1º turno o painel projeta *Segundo Turno* quando ninguém deve alcançar a maioria.
- **Arquitetura Desacoplada (Clean Architecture + Hexagonal):** O motor de cálculo não depende de banco ou rede; a comunicação é orquestrada por um barramento de eventos em memória (`EventBus`).
- **Persistência WAL & Time-Travel:** Banco de dados SQLite nativo configurado em modo WAL (*Write-Ahead Logging*), permitindo auditar qualquer ciclo passado sem travar o coletor.
- **Painel de apuração em tela única, com abas:** coluna fixa de candidatos (nome de urna, vice, coligação, apurado × projetado) com **seleção de quais aparecem nos gráficos**; faixa de status (situação, anel de seções apuradas, chance de 2º turno/vitória e **chance de virada**); abas *Visão geral* (corrida até 100% com projeção pontilhada, intervalos de projeção, curva de projeção, probabilidades), *Consolidado* (todos os candidatos com votos, % válidos, projeção, faixa provável e situação, mais os totais: eleitorado, comparecimento, abstenção, válidos, brancos, nulos e anulados), *Mapa* (Brasil por UF: líder, % apurado ou vantagem, com detalhe de cidades e interior da UF clicada), *Cenários*, *Apuração*, *Regiões*, *UFs* e *Exterior* (votos do exterior por país, com as cidades de cada país; as 186 cidades são baixadas a cada 2 minutos e não entram na projeção). Percentuais pequenos ganham mais casas decimais, para os candidatos nanicos não aparecerem como 0,0%. No 2º turno o painel mostra só o confronto direto. Gráficos em **Apache ECharts 6** embutido (`spetr/ui/assets/js/vendor/`, sem CDN), mapa com a malha oficial do IBGE (`spetr/ui/assets/geo/`), temas claro e escuro. `?estatico=1` desenha sem atualização ao vivo, `?tema=claro|escuro` força o tema e `?aba=mapa` abre uma aba.
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
2. **Replay de eleição real**: reproduz uma apuração que já aconteceu, na ordem e no horário em que o TSE recebeu cada urna (boletins de urna dos Dados Abertos), servida por um servidor local que imita a CDN do TSE. O painel ganha o botão **Controlar replay** (pausar, avançar, pular para 25%/50%/95%). Replays disponíveis: os que você preparou com `scripts/preparar_replay.py` (veja abaixo), como o 1º turno de 2026 e os dois turnos de 2022.

No painel, **Trocar modo** volta à tela inicial sem reiniciar o app (por exemplo: rever um replay e passar para a coleta real quando a apuração começar). Para pular a tela inicial:

```bash
python3 main.py --modo real                          # coleta real direto
python3 main.py --modo real --eleicao 6257 --verificar-jws oficial
python3 main.py --modo replay --fonte 2026_1t --velocidade rapida   # replay do 1º turno de 2026
python3 main.py --modo real --ano 2022 --eleicao 545 --turno 2 --formato r   # eleição antiga (Dados Simplificados)
```

Na coleta real, quando todas as UFs chegam a 100% das seções o SPETR faz mais duas coletas de segurança (relendo também os municípios já concluídos) e **encerra a coleta**: o painel avisa "coleta encerrada" e deixa de baixar dados. No replay a coleta não para, para você poder voltar a 0%.

As cores dos candidatos seguem o partido: **PL sempre azul e PT sempre vermelho**; os demais usam a cor preferida do partido (ex.: Avante e Novo, laranja) quando está livre, ou a primeira cor livre.

Antes do primeiro voto apurado o painel mostra "Aguardando o início da apuração" (os arquivos do TSE já existem, zerados) e nada é projetado.

| Opção | Padrão | Descrição |
|---|---|---|
| `--modo` | tela inicial | `real` ou `replay`: inicia direto, sem a tela inicial |
| `--fonte` / `--velocidade` | — / `normal` | Replay a iniciar (ex.: `2026_1t`) e o ritmo dele |
| `--ano` | `2026` | Ciclo eleitoral (`ele{ano}`) |
| `--eleicao` | descoberta automática | Código da eleição no TSE; obrigatório no formato `r` |
| `--cargo` | `1` | Código do cargo (1 = Presidente) |
| `--turno` | `1` | Turno usado na descoberta automática |
| `--formato` | `u` (2024+) / `r` | `u` = Resultado Unificado EA20 (`/dados/…-u.json`); `r` = Dados Simplificados (`/dados-simplificados/…-r.json`) |
| `--ambiente` | `oficial` | Pasta de ambiente na CDN |
| `--verificar-jws` | desativado | Baixa os pares `.jws` e valida a assinatura Ed25519 com a chave `oficial` ou `desenvolvimento` do manual do TSE |
| `--db` | `spetr_eleicoes.sqlite` | Banco de histórico (cada pleito e execução ficam identificados) |

### Replay de uma eleição real (boletins de urna)
O servidor de resultados do TSE não guarda eleições antigas (2022 já saiu do ar). Os **boletins de urna** dos Dados Abertos trazem os votos de cada seção e o horário em que o TSE a recebeu (`DT_BU_RECEBIDO`), o que permite reproduzir a noite da apuração na ordem real. Prepare uma vez (2º turno: ~150 MB de download; 1º turno: alguns GB, pois traz todos os cargos):
```bash
python3 scripts/preparar_replay.py --ano 2022 --turno 2     # gera ~/.local/share/spetr/replay/2022_2t.json.gz (1,5 MB)
python3 scripts/preparar_replay.py --ano 2022 --turno 1
python3 scripts/preparar_replay.py --ano 2026 --turno 1     # ~5 GB de boletins; o replay final tem ~2 MB
```
Depois, na tela inicial, escolha **Replay de eleição real**. O relógio começa às 17h (Brasília) e anda alguns minutos da noite real a cada atualização; o painel recebe os arquivos no mesmo formato do TSE. O replay do 1º turno de 2026 fecha exatamente no resultado do TSE (Flávio Bolsonaro 47,03%, Lula 45,16%). No 2º turno de 2022, o IC 95% conteve o resultado final em 96% dos instantes e a vitória de Lula foi chamada com 88% das seções.

A tela inicial lista as eleições presidenciais por ano, com 2026 como padrão. Para 2022, a opção de dados reais usa o replay local dos boletins, porque os arquivos de resultados não permanecem disponíveis no servidor antigo do TSE.

### Replay de uma apuração gravada
`scripts/replay_apuracao.py` reprocessa uma execução gravada no banco e mede erro, cobertura do IC 95% e a primeira chamada, para a projeção principal e as extras (crescimento, estimador direto e swing; use `--ano` e `--turno` para escolher a referência do swing). `--dois` ensaia um 2º turno com os dados reais do 1º; `--desloca` aperta a disputa mantendo a ordem de apuração:
```bash
python3 scripts/replay_apuracao.py --execucao 74f16c746af0 --dois 22,13 --min-cobertura 0.85
python3 scripts/replay_apuracao.py --execucao 74f16c746af0 --dois 22,13 --desloca 0.022
```

### Atualizando os metadados de estratificação
Os arquivos `spetr/data/ufs_metadados.json`, `cidades_100k.json`, `municipios_meta.json` e `exterior_cidades.json` (cidades do exterior com país e continente) são gerados a partir do eleitorado oficial do TSE (use `--turno 1`; depois do 1º turno o arquivo do TSE traz os dois turnos):
```bash
curl -LO https://cdn.tse.jus.br/estatistica/sead/odsele/eleitorado_locais_votacao/eleitorado_local_votacao_2026.zip
unzip eleitorado_local_votacao_2026.zip -d eleitorado
python3 scripts/gerar_metadados_eleitorado.py eleitorado --config-mun docs/tse_oficial/mun-e021270-cm.json
```

A subestratificação de MG (`spetr/data/subestratos.json`) vem da API do IBGE e do arquivo de municípios do TSE (que traz o código IBGE). `--validar` confere cada URL numa eleição já publicada (≤ 5 req/s) e aborta se alguma não responder 200, porque muitos 404 podem bloquear o IP:
```bash
python3 scripts/gerar_subestratos.py --validar                     # padrão: MG, Norte = 5 mesorregiões, eleição 6257
```

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

O `spetr.spec` (PyInstaller) gera um executável único com Python, bibliotecas, painel, servidor de replay e metadados embutidos. Quem recebe o arquivo não precisa instalar nada: basta abrir.

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
