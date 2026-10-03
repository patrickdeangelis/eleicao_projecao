# SPETR — Sistema de Projeção Eleitoral em Tempo Real

<p align="center">
  <strong>Motor Estatístico Bayesiano & Dashboard Desktop Decision Desk para Apuração Eleitoral (TSE)</strong>
</p>

---

## 📌 Visão Geral

O **SPETR** é uma solução completa e de grau profissional para projeção e acompanhamento de resultados eleitorais em tempo real, baseada em dados abertos oficiais do Tribunal Superior Eleitoral (TSE).

Diferente de placares tradicionais que apenas exibem a soma das urnas que já chegaram, o SPETR utiliza **Pós-Estratificação em 4 Níveis**, **Inferência Bayesiana Sequencial (Dirichlet-Multinomial)** e **10.000 simulações de Monte Carlo por ciclo** para projetar com precisão matemática o resultado final antes que a apuração atinja a totalização.

### Destaques e Diferenciais
- **Estratificação por Cidades > 100k + Subtração Vetorial:** Isola as ~154 maiores cidades do país e calcula o "Interior Remanescente" por álgebra vetorial ($\text{Interior} = \text{Total}_{\text{UF}} - \sum \text{Cidades}_{>100\text{k}}$). Isso elimina distorções intrarregionais (como o caso paraibano: João Pessoa ~54% x Campina Grande ~48.5% x Sertão ~75%).
- **Proteção Total contra WAF do TSE:** Limite contínuo de 9 a 12 requisições por segundo com semáforo de concorrência (`asyncio.Semaphore(15)`) e cache condicional (`HTTP 304 / If-Modified-Since`), reduzindo o consumo de banda em mais de 85% e blindando o IP contra banimentos.
- **Performance Sub-Milissegundo:** Motor estatístico vetorizado em C via NumPy que executa 10.000 eleições completas em **~128 ms** (< 1% de uso de CPU).
- **Arquitetura Desacoplada (Clean Architecture + Hexagonal):** O motor de cálculo não depende de banco ou rede; a comunicação é orquestrada por um barramento de eventos em memória (`EventBus`).
- **Persistência WAL & Time-Travel:** Banco de dados SQLite nativo configurado em modo WAL (*Write-Ahead Logging*), permitindo auditar qualquer ciclo passado sem travar o coletor.
- **Interface Desktop de Transmissão:** Dashboard estilo *Decision Desk* com animações a 60 FPS, Server-Sent Events (SSE), faixas visuais de incerteza (IC 95%), e *call decisions* automáticas (*Vitória Projetada* e *Matematicamente Eleito*).

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

### 3. Executando o Dashboard Desktop
```bash
# Modo com janela nativa desktop (PyWebView):
python3 main.py

# Ou modo servidor local (caso esteja em servidor sem display gráfico):
python3 main.py --headless --porta 48291
```
Abra o navegador em `http://127.0.0.1:48291`.

### 4. Modo Debug com Servidor Mock do TSE (Candidatos Fictícios e Controle ao Vivo)
Você pode subir um emulador local que simula a CDN oficial do TSE com candidatos e números fictícios:
```bash
# Terminal 1: Inicie o servidor mock da CDN do TSE
python3 scripts/mock_tse_server.py
```
* Abra `http://127.0.0.1:8080/` para acessar o **Painel de Controle** da apuração (pausar, avançar +5%, resetar, pular para 50%, etc.).

Em seguida, em outro terminal, inicie o SPETR conectado ao mock:
```bash
# Terminal 2: Conecte o SPETR ao servidor mock
python3 main.py --mock
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
- `test_tse_parser.py`: Robustez na conversão de números brasileiros com vírgulas e pontos.
- `test_full_pipeline_replay.py`: Teste de integração assíncrona ponta a ponta pelo `EventBus`.

---

## 📦 Gerando o Executável Standalone (Zero Dependências)

Para empacotar a aplicação em um executável único (`.exe`, `.AppImage` ou `.dmg`):

```bash
uv pip install pyinstaller
pyinstaller spetr.spec --clean
```

O binário final auto-contido será gerado na pasta `dist/spetr`.

---

## 📚 Documentação Técnica Completa

Toda a fundamentação teórica, matemática e de arquitetura está disponível na pasta [`docs/`](docs/):
1. [Guia de Apuração TSE](docs/guia_apuracao_tse.md): Protocolos de rede, CDN Akamai, dicionário de campos.
2. [Modelo Estatístico e Ciência](docs/modelo_estatistico_projecao_apuracao.md): Modelagem Bayesiana, amostragem estratificada de Cochran e equações.
3. [Especificações do Sistema (SRS)](docs/especificacoes_do_sistema.md): Requisitos funcionais (RF), não funcionais (RNF) e contratos.
4. [Arquitetura de Módulos](docs/arquitetura_de_modulos.md): Diagrama de sequência, Clean Architecture e contratos de código.
