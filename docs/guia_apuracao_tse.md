# Guia Completo: Construindo um App de Apuração Eleitoral em Tempo Real com Dados do TSE

Este documento apresenta a documentação técnica, especificações de endpoints, dicionário de dados e arquitetura recomendada para construir uma aplicação de acompanhamento da apuração dos votos das eleições brasileiras utilizando os dados oficiais disponibilizados pelo **Tribunal Superior Eleitoral (TSE)**.

---

## Sumário

1. [Visão Geral da Infraestrutura do TSE](#1-visão-geral-da-infraestrutura-do-tse)
2. [Estrutura e Anatomia dos Endpoints](#2-estrutura-e-anatomia-dos-endpoints)
3. [Tabela de Códigos de Cargos e Abrangências](#3-tabela-de-códigos-de-cargos-e-abrangências)
4. [Dicionário Completo dos Campos JSON](#4-dicionário-completo-dos-campos-json)
5. [Outros Arquivos Oficiais do TSE (Especificações EAxx e BUs)](#5-outros-arquivos-oficiais-do-tse-especificações-eaxx-e-bus)
6. [Arquitetura de Software Recomendada](#6-arquitetura-de-software-recomendada)
   - [6.1. Estratégia de Coleta em Larga Escala: A Regra das Cidades > 100k e Pacing Seguro](#61-estratégia-de-coleta-em-larga-escala-a-regra-das-cidades--100k-e-pacing-seguro)
7. [Exemplo Prático de Implementação](#7-exemplo-prático-de-implementação)
   - [7.1. Worker / Backend em Python](#71-worker--backend-em-python)
   - [7.2. Frontend Simples com HTML, CSS e JavaScript](#72-frontend-simples-com-html-css-e-javascript)
8. [Checklist e Boas Práticas para o Dia da Eleição](#8-checklist-e-boas-práticas-para-o-dia-da-eleição)

---

## 1. Visão Geral da Infraestrutura do TSE

Diferente de sistemas tradicionais que oferecem APIs REST dinâmicas conectadas diretamente a bancos de dados transacionais, o TSE emprega uma arquitetura baseada em **distribuição de arquivos estáticos via CDN (Content Delivery Network - Akamai)**.

### Características Principais:
* **Domínio Oficial de Divulgação:** `https://resultados.tse.jus.br`
* **Ambiente Oficial:** As requisições apontam para `/oficial/`.
* **Geração em Lote:** A cada atualização da totalização de votos transmitida pelos cartórios eleitorais, o núcleo do TSE processa os boletins de urna e gera novos arquivos compactos em formato JSON, enviando-os para os pontos de presença (PoPs) da CDN.
* **Cabeçalhos de Cache (`Cache-Control`):** Os arquivos possuem tempo de vida em cache (`max-age`) geralmente configurado entre **15 e 60 segundos**. Fazer requisições em intervalos menores do que o cache configurado apenas retornará a resposta já armazenada no cache da CDN, consumindo recursos à toa.
* **Política de Rate Limit e Bloqueios:**
  - O TSE permite no máximo **100 requisições por segundo por endereço IP**.
  - O disparo de requisições excessivas ou uma sequência contínua de erros **HTTP 404 (Not Found)** é tratado pelos firewalls (WAF) do TSE como tentativa de ataque ou varredura não autorizada, resultando no **bloqueio temporário do IP por 10 minutos**.

---

## 2. Estrutura e Anatomia dos Endpoints

Os arquivos de apuração são organizados em uma estrutura hierárquica baseada no ciclo eleitoral, no código do pleito e na abrangência geográfica.

### Padrão para "Dados Simplificados" (Totalização Rápida)
É o formato mais indicado para dashboards e apps de apuração em tempo real, pois consolida os totais de votos, percentuais e seções apuradas em um arquivo extremamente leve:

```text
https://resultados.tse.jus.br/oficial/ele{ANO}/{COD_PLEITO}/dados-simplificados/{UF}/{UF}-c{COD_CARGO}-e{COD_PLEITO_6_DIGITOS}-r.json
```

#### Parâmetros:
* `{ANO}`: Ano eleitoral com 4 dígitos (ex: `2022`, `2024`, `2026`).
* `{COD_PLEITO}`: Identificador numérico do pleito/turno atribuído pelo TSE (ex: `544` para 1º turno de 2022, `545` para 2º turno).
* `{COD_PLEITO_6_DIGITOS}`: O mesmo código do pleito, porém formatado com zeros à esquerda totalizando 6 dígitos (ex: `000544`, `000545`).
* `{UF}`: Sigla do estado em letras minúsculas (ex: `sp`, `rj`, `mg`, `ba`) ou `br` para disputas de âmbito nacional.
* `{COD_CARGO}`: Código do cargo com 4 dígitos (ex: `0001` para Presidente, `0003` para Governador).

### Exemplos de URLs Oficiais:

1. **Eleição Presidencial no Brasil (2º Turno 2022):**
   ```text
   https://resultados.tse.jus.br/oficial/ele2022/545/dados-simplificados/br/br-c0001-e000545-r.json
   ```

2. **Governador de São Paulo (2º Turno 2022):**
   ```text
   https://resultados.tse.jus.br/oficial/ele2022/547/dados-simplificados/sp/sp-c0003-e000547-r.json
   ```

3. **Eleições Municipais (Prefeito e Vereador):**
   Para municípios, o identificador da UF é concatenado ao código de 5 dígitos do município no TSE:
   ```text
   https://resultados.tse.jus.br/oficial/ele{ANO}/{COD_PLEITO}/dados-simplificados/{UF}/{UF}{COD_MUNICIPIO_5_DIGITOS}-c{COD_CARGO}-e{COD_PLEITO_6_DIGITOS}-r.json
   ```
   *Exemplo:* Para a capital São Paulo (Código TSE `71072`), o prefixo do arquivo é `sp71072-c0011-...`.

---

## 3. Tabela de Códigos de Cargos e Abrangências

| Código | Cargo em Disputa | Abrangência ({UF}) | Tipo de Eleição |
| :--- | :--- | :--- | :--- |
| `c0001` | Presidente da República | `br` | Geral / Federal |
| `c0003` | Governador | UF (`sp`, `rj`, etc.) | Geral / Estadual |
| `c0005` | Senador | UF | Geral / Estadual |
| `c0006` | Deputado Federal | UF | Geral / Proporcional |
| `c0007` | Deputado Estadual | UF | Geral / Proporcional |
| `c0008` | Deputado Distrital | `df` | Geral / Distrito Federal |
| `c0011` | Prefeito | UF + Cód. Município | Municipal / Majoritária |
| `c0013` | Vereador | UF + Cód. Município | Municipal / Proporcional |

---

## 4. Dicionário Completo dos Campos JSON

Os arquivos do TSE utilizam chaves curtas para reduzir a sobrecarga de transferência de dados pela rede:

### Metadados e Controle de Atualização
* `dg`: **Data de Geração** do snapshot (formato: `DD/MM/AAAA`).
* `hg`: **Hora de Geração** do snapshot (formato: `HH:MM:SS`). **Campo ideal para verificação de novas versões** (se `hg` não mudou, o conteúdo é idêntico).
* `f`: **Fase** da eleição (ex: `"O"` para Oficial, `"S"` para Simulado/Teste).
* `s`: Total de **Seções Eleitorais** existentes na circunscrição.
* `st`: Total de **Seções Totalizadas** (apuradas) até aquele instante.
* `pst`: **Percentual de Seções Apuradas** (formato string com vírgula ou ponto, ex: `"95.42"`).

### Eleitorado, Comparecimento e Abstenção
* `e`: Total de **Eleitores Aptos** a votar.
* `c`: Total de eleitores que **compareceram** às urnas.
* `pc`: **Percentual de comparecimento** sobre o eleitorado apto.
* `a`: Total de **abstenções** (eleitores que faltaram).
* `pa`: **Percentual de abstenção**.

### Estatísticas Globais de Votos
* `tv`: **Total de Votos** registrados (soma de nominais, brancos e nulos).
* `vnom`: Total de **Votos Nominais** (válidos creditados a candidatos).
* `vb`: Total de **Votos em Branco**.
* `pvb`: **Percentual de votos brancos**.
* `tvn`: Total de **Votos Nulos**.
* `ptvn`: **Percentual de votos nulos**.
* `van`: Total de votos anulados.
* `vansj`: Total de votos anulados *sub judice*.

### Lista de Candidatos (`cand`)
O array `cand` contém um objeto para cada candidato concorrente:
* `seq`: Número sequencial do candidato no banco de dados do TSE.
* `sqcand`: Identificador único de registro de candidatura.
* `n`: **Número do candidato na urna** (ex: `"13"`, `"22"`).
* `nm`: **Nome de urna** do candidato (ex: `"LULA"`, `"JAIR BOLSONARO"`).
* `nv`: **Nome do vice ou suplente** de chapa.
* `cc`: Sigla do **partido, federação partidária ou coligação**.
* `vap`: **Total de Votos Nominais** apurados para o candidato.
* `pvap`: **Percentual de votos válidos** obtidos (ex: `"50.90"`).
* `e`: Indicador de eleição (`"s"` = eleito matematicamente, `"n"` = não eleito / indefinido).
* `st`: **Situação** do candidato na apuração (ex: `"Eleito"`, `"2º turno"`, `"Não eleito"`, `"Suplente"`).
* `dvt`: Destinação do voto (ex: `"Válido"`).

---

## 5. Outros Arquivos Oficiais do TSE (Especificações EAxx e BUs)

Além do arquivo simplificado (`dados-simplificados`), o TSE distribui documentos técnicos identificados pela nomenclatura `TSE-EAxx`:

1. **`EA11` (Arquivo de Configuração de Eleições):**
   - Disponibilizado antes do pleito, contém a árvore completa de códigos de eleições vigentes, turnos, UFs participantes e cargos em disputa. Permite que seu app configure os seletores dinamicamente.
2. **`EA10` (Arquivo de Resultado de Eleitos):**
   - Gerado automaticamente pelo TSE à medida que as disputas atingem definição matemática definitiva.
3. **`EA20` (Arquivo de Resultados Unificados):**
   - Contém a totalização abrangente incluindo quocientes partidários e eleitorais.
4. **Boletins de Urna (`.bu`) e Assinaturas Digitais (`.jws`):**
   - Para auditoria profunda, o TSE publica o arquivo correspondente a cada urna individual do país acompanhado de sua assinatura digital no padrão JWS (JSON Web Signature), permitindo validar criptograficamente a autenticidade de cada seção.

---

## 6. Arquitetura de Software Recomendada

```
+-------------------------------------------------------------+
|            CDN Oficial do TSE (resultados.tse.jus.br)       |
+-------------------------------------------------------------+
                              |
                     Polling (15 a 30s)
                              v
+-------------------------------------------------------------+
|              SEU BACKEND WORKER (Python / Node.js)          |
|  - Valida se `hg` (hora de geração) mudou                   |
|  - Filtra e estrutura os dados necessários                  |
+-------------------------------------------------------------+
                              |
                              +------------------------+
                              |                        |
                              v                        v
             +--------------------+       +-----------------------+
             | Memória / Cache /  |       | Canal em Tempo Real   |
             | Redis              |       | (SSE ou WebSockets)   |
             +--------------------+       +-----------------------+
                              |                        |
                              +------------+-----------+
                                           |
                                           v
                       +---------------------------------------+
                       |           SEUS USUÁRIOS FINAIS         |
                       |  (App Mobile, Dashboard Web, React)   |
                       +---------------------------------------+
```

### 6.1. Estratégia de Coleta em Larga Escala: A Regra das Cidades > 100k e Pacing Seguro

Para alimentar modelos analíticos ou dashboards que exibem detalhes por cidade sem correr o risco de bloqueio de IP pelo TSE (limite de 100 req/s):

1. **Seleção Inteligente de Alvos (Regra dos 100 Mil Eleitores):**
   * O Brasil possui 5.570 municípios, mas apenas **~154 municípios possuem mais de 100 mil eleitores**.
   * Essas 154 cidades concentram **mais de 53% de todo o eleitorado do país**.
   * Ao coletar as **27 UFs consolidadas** + as **~154 cidades com > 100k eleitores**, o total é de apenas **~181 requisições por ciclo**.
   * O Interior de cada estado é obtido instantaneamente por subtração vetorial:
     $$\text{Interior Remanescente}(UF) = \text{Total}(UF) - \sum_{c \in \text{Cidades > 100k}} \text{Cidade}_c(UF)$$

2. **A Relação Ótima de Requisições por Segundo:**
   * Executando um ciclo a cada 20 segundos:
     $$\text{Taxa Média} = \frac{181 \text{ requisições}}{20 \text{ segundos}} \approx \mathbf{9,0 \text{ req/s}}$$
   * Esse volume consome **menos de 10% do teto do TSE**, eliminando o risco de sobrecarga.

3. **Pacing com Semáforo vs. Rajadas (*Thundering Herd*):**
   * **Nunca dispare os 181 requests no mesmo instante**, pois a taxa instantânea bateria 181 req/s, ativando o firewall (WAF) do TSE.
   * Utilize `asyncio.Semaphore(15)` em Python para criar um fluxo contínuo de 10 a 15 requisições por segundo.

4. **Economia Máxima com Cache Condicional (HTTP 304 Not Modified):**
   * Salve o cabeçalho `Last-Modified` ou `ETag` de cada resposta e envie no request seguinte via `If-Modified-Since`.
   * Se o arquivo ainda não foi recalculado pelo TSE, a CDN responde com status **`304 Not Modified`** em menos de 30ms com payload quase nulo (~100 bytes).

---

## 7. Exemplo Prático de Implementação

### 7.1. Worker / Backend em Python

O script a seguir consulta o endpoint, detecta atualizações pela hora de geração (`hg`) e mantém os dados atualizados em memória:

```python
import time
import requests

# Exemplo: Eleição Presidencial 2022 - 2º Turno
URL_TSE = "https://resultados.tse.jus.br/oficial/ele2022/545/dados-simplificados/br/br-c0001-e000545-r.json"

HEADERS = {
    "User-Agent": "ApuracaoEleicoesApp/1.0 (seuemail@exemplo.com)",
    "Accept": "application/json"
}

def extrair_dados_apuracao():
    ultima_hora_geracao = None

    print("Iniciando monitoramento da apuração do TSE...")

    while True:
        try:
            response = requests.get(URL_TSE, headers=HEADERS, timeout=10)

            if response.status_code == 200:
                payload = response.json()
                hora_atual = payload.get("hg")

                # Processa apenas quando houver novidade na apuração
                if hora_atual != ultima_hora_geracao:
                    ultima_hora_geracao = hora_atual

                    data_geracao = payload.get("dg")
                    urnas_apuradas = payload.get("pst")
                    secoes_totalizadas = payload.get("st")
                    total_secoes = payload.get("s")

                    print("\n" + "=" * 60)
                    print(f"ATUALIZAÇÃO: {data_geracao} às {hora_atual}")
                    print(f"Urnas Apuradas: {urnas_apuradas}% ({secoes_totalizadas}/{total_secoes} seções)")
                    print("-" * 60)

                    # Ordena candidatos pelos mais votados
                    candidatos = sorted(
                        payload.get("cand", []),
                        key=lambda x: int(x.get("vap", 0)),
                        reverse=True
                    )

                    for cand in candidatos:
                        nome = cand.get("nm")
                        partido = cand.get("cc")
                        votos = int(cand.get("vap", 0))
                        pct = cand.get("pvap")
                        eleito = " [ELEITO]" if cand.get("e") == "s" else ""

                        print(f"[{cand.get('n')}] {nome:<20} | {pct:>6}% | {votos:>10,} votos{eleito}")
                    
                    print("=" * 60)
                else:
                    # Sem alteração no arquivo do TSE
                    print(".", end="", flush=True)

            elif response.status_code == 404:
                print("\n[Aviso] Dados ainda não liberados ou URL incorreta (404).")
            else:
                print(f"\n[Aviso] Resposta HTTP inesperada: {response.status_code}")

        except requests.exceptions.RequestException as err:
            print(f"\n[Falha de Conexão] {err}")

        # Respeite o tempo de cache (15 a 30 segundos)
        time.sleep(20)

if __name__ == "__main__":
    extrair_dados_apuracao()
```

---

### 7.2. Frontend Simples com HTML, CSS e JavaScript

Interface responsiva com barras de progresso para exibir a apuração:

```html
<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Apuração Eleitoral em Tempo Real</title>
  <style>
    body {
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      background-color: #0f172a;
      color: #f8fafc;
      display: flex;
      justify-content: center;
      padding: 2rem;
      margin: 0;
    }
    .container {
      width: 100%;
      max-width: 600px;
      background: #1e293b;
      border-radius: 12px;
      padding: 24px;
      box-shadow: 0 4px 20px rgba(0,0,0,0.4);
    }
    .header {
      border-bottom: 1px solid #334155;
      padding-bottom: 16px;
      margin-bottom: 20px;
    }
    .progress-bar-bg {
      background: #334155;
      border-radius: 999px;
      height: 12px;
      overflow: hidden;
      margin-top: 8px;
    }
    .progress-bar-fill {
      background: #38bdf8;
      height: 100%;
      width: 0%;
      transition: width 0.6s ease;
    }
    .candidate-card {
      background: #334155;
      border-radius: 8px;
      padding: 16px;
      margin-bottom: 12px;
      display: flex;
      flex-direction: column;
      gap: 8px;
    }
    .candidate-info {
      display: flex;
      justify-content: space-between;
      font-weight: bold;
    }
    .votes-info {
      font-size: 0.9rem;
      color: #94a3b8;
    }
    .vote-bar-fill {
      background: #10b981;
      height: 8px;
      border-radius: 999px;
      transition: width 0.6s ease;
    }
  </style>
</head>
<body>

  <div class="container">
    <div class="header">
      <h2>Apuração Oficial - Presidencial</h2>
      <div id="status">Aguardando dados...</div>
      <div class="progress-bar-bg">
        <div id="urnas-progress" class="progress-bar-fill"></div>
      </div>
    </div>

    <div id="candidatos-lista"></div>
  </div>

  <script>
    // Substitua pela URL da sua API backend
    const API_URL = "/api/apuracao";

    async function atualizarApuracao() {
      try {
        const resp = await fetch(API_URL);
        const data = await resp.json();

        document.getElementById("status").innerText = 
          `Urnas apuradas: ${data.pst}% (${data.st} de ${data.s} seções) - Atualizado às ${data.hg}`;
        document.getElementById("urnas-progress").style.width = `${data.pst.replace(',', '.')}%`;

        const lista = document.getElementById("candidatos-lista");
        lista.innerHTML = "";

        // Ordenar candidatos por votos
        data.cand.sort((a, b) => parseInt(b.vap) - parseInt(a.vap));

        data.cand.forEach(c => {
          const card = document.createElement("div");
          card.className = "candidate-card";
          card.innerHTML = `
            <div class="candidate-info">
              <span>${c.nm} (${c.cc})</span>
              <span>${c.pvap}%</span>
            </div>
            <div class="progress-bar-bg">
              <div class="vote-bar-fill" style="width: ${c.pvap.replace(',', '.')}%"></div>
            </div>
            <div class="votes-info">${parseInt(c.vap).toLocaleString('pt-BR')} votos válidos</div>
          `;
          lista.appendChild(card);
        });

      } catch (err) {
        console.error("Erro ao carregar apuração:", err);
      }
    }

    // Polling a cada 20 segundos
    atualizarApuracao();
    setInterval(atualizarApuracao, 20000);
  </script>
</body>
</html>
```

---

## 8. Checklist e Boas Práticas para o Dia da Eleição

1. **Obtenha os Códigos de Eleição Previamente:**
   - O TSE publica as tabelas com os códigos de cada pleito semanas antes da votação na página [Informações Técnicas sobre a Divulgação de Resultados](https://www.tse.jus.br/eleicoes/informacoes-tecnicas-sobre-a-divulgacao-de-resultados).
   - Verifique o arquivo `EA11` (`config-eleicoes`) no início da semana eleitoral para validar os IDs dos pleitos de 1º e 2º turno.

2. **Participe dos Simulados Oficiais:**
   - Nos dias anteriores ao domingo de votação, o TSE realiza simulados de transmissão. Nesse período, os servidores distribuem dados de teste identificados pelo campo `"f": "S"`. É o momento ideal para testar se seus parsers, ordenações e telas estão sem bugs.

3. **Gerencie Erros 404 e Fail-Safe:**
   - Antes do início oficial da apuração (normalmente a partir das 17h, horário de Brasília), os arquivos de resultado podem retornar HTTP 404.
   - Seu worker deve capturar erros 404 sem desespero e sem disparar loops infinitos de retentativa imediata, aguardando o próximo ciclo de polling normal.

4. **Transparência e Conformidade Jurídica:**
   - As resoluções do TSE determinam que sistemas que divulgam resultados eleitorais devem deixar evidente a menção à fonte oficial: **"Fonte: Dados abertos do Tribunal Superior Eleitoral (TSE)"**.
   - Respeite a indicação de candidatos *sub judice*, alertando os usuários quando os votos de um candidato estiverem condicionados a recursos judiciais.
