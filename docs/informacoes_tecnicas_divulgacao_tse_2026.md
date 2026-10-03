# Informações Técnicas sobre a Divulgação de Resultados 2026 (TSE Oficial)

> **Fonte Original:** [Portal do TSE](https://www.tse.jus.br/eleicoes/informacoes-tecnicas-sobre-a-divulgacao-de-resultados?tab=ancora-1)
> **Data da Versão:** Eleições Gerais de 2026 / Audiência Pública
> **Arquivos Oficiais Baixados:** Disponíveis localmente na pasta [](tse_oficial/)

## Índice de Arquivos Oficiais Baixados

| Arquivo | Descrição | Link Local |
|---|---|---|
| `apresentacao-interessados-2026.pdf` | Apresentação oficial da audiência técnica do TSE com entidades | [Ver PDF](tse_oficial/apresentacao-interessados-2026.pdf) |
| `tse-instrucoes-para-download-dos-arquivos-da-divulgacao-2026.pdf` | Instruções operacionais para download dos arquivos de divulgação | [Ver PDF](tse_oficial/tse-instrucoes-para-download-dos-arquivos-da-divulgacao-2026.pdf) |
| `tse-ea10-arquivo-de-resultado-de-eleitos.pdf` | Especificação técnica do arquivo de resultado de eleitos (EA10) | [Ver PDF](tse_oficial/tse-ea10-arquivo-de-resultado-de-eleitos.pdf) |
| `tse-ea11-arquivo-de-configuracao-de-eleicoes.pdf` | Especificação técnica do arquivo de configuração de eleições (EA11) | [Ver PDF](tse_oficial/tse-ea11-arquivo-de-configuracao-de-eleicoes.pdf) |
| `tse-ea12-arquivo-de-configuracao-de-municipios.pdf` | Especificação do arquivo de configuração de municípios (EA12) | [Ver PDF](tse_oficial/tse-ea12-arquivo-de-configuracao-de-municipios.pdf) |
| `tse-ea14-arquivo-de-acompanhamento-brasil.pdf` | Especificação do arquivo de acompanhamento nacional Brasil (EA14) | [Ver PDF](tse_oficial/tse-ea14-arquivo-de-acompanhamento-brasil.pdf) |
| `tse-ea15-arquivo-de-acompanhamento-uf.pdf` | Especificação do arquivo de acompanhamento por UF (EA15) | [Ver PDF](tse_oficial/tse-ea15-arquivo-de-acompanhamento-uf.pdf) |
| `tse-ea16-arquivo-de-configuracao-de-secoes-eleitorais.pdf` | Especificação de configuração de seções eleitorais (EA16) | [Ver PDF](tse_oficial/tse-ea16-arquivo-de-configuracao-de-secoes-eleitorais.pdf) |
| `tse-ea18-arquivo-auxiliar-de-secao.pdf` | Especificação do arquivo auxiliar de seção (EA18) | [Ver PDF](tse_oficial/tse-ea18-arquivo-auxiliar-de-secao.pdf) |
| `tse-ea20-arquivo-de-resultado-unificado.pdf` | Especificação do novo formato unificado de resultado (EA20) | [Ver PDF](tse_oficial/tse-ea20-arquivo-de-resultado-unificado.pdf) |
| `manual-verificacao-jws.pdf` | Manual de verificação de assinatura digital JWS dos arquivos | [Ver PDF](tse_oficial/manual-verificacao-jws.pdf) |
| `exemplos-de-arquivos-json.zip` | Pacote ZIP oficial com payloads JSON de exemplo de cada tipo (2.04 MB) | [Arquivo ZIP](tse_oficial/exemplos-de-arquivos-json.zip) |
| `ele-c.json` | JSON oficial do simulado: configuração das eleições | [Ver JSON](tse_oficial/ele-c.json) |
| `mun-e021270-cm.json` | JSON oficial do simulado: configuração de municípios | [Ver JSON](tse_oficial/mun-e021270-cm.json) |
| `br-c0001-e021270-u.json` | JSON oficial do simulado: resultado unificado Presidencial BR | [Ver JSON](tse_oficial/br-c0001-e021270-u.json) |


## Informações técnicas sobre a divulgação de resultados 2026

* Informações
* Simulados
* FAQ
* Documentos

### Informações para as Eleições 2026

Nesta página, são disponibilizadas informações técnicas e outros documentos sobre as definições do modelo de distribuição e os padrões tecnológicos e de segurança exigidos para a divulgação dos resultados.

Entidades interessadas em divulgar os resultados da eleição de 2026 devem observar as diretrizes dos artigos 264 a 269 da Resolução de Atos Gerais nº 23.751 , de 26 de fevereiro de 2026.

Ambiente Oficial Para as entidades que desenvolverem solução própria para a divulgação, o acesso aos arquivos deverá ser realizado com os parâmetros seguintes:

* url: https://resultados.tse.jus.br
* ambiente: oficial
* códigos das eleições: 04/10/2026 - Pleito 3220 - (1º Turno) 6257 - Eleição Geral Federal 6259 - Eleições Gerais Estaduais 2026 6261 - Eleição Conselho Distrital 2026

* 04/10/2026 - Pleito 3220 - (1º Turno) 6257 - Eleição Geral Federal 6259 - Eleições Gerais Estaduais 2026 6261 - Eleição Conselho Distrital 2026

* 6257 - Eleição Geral Federal
* 6259 - Eleições Gerais Estaduais 2026
* 6261 - Eleição Conselho Distrital 2026

A Justiça Eleitoral está em plena fase de julgamento dos registros de candidaturas, só após encerramento dessa fase, haverá a lista completa dos candidatos. Portanto, nesse momento, não hã uma relação definitiva dos candidatos que concorrerão em outubro para divulgação no site de resultados. Outras atualizações podem ser acompanhadas também pelo Portal de Dados Abertos do TSE https://dadosabertos.tse.jus.br/

Será permitido um máximo de 100 requisições por IP por segundo . Caso esse limite seja ultrapassado, poderá haver um bloqueio de 10 minutos . Se uma nova tentativa for feita antes do término, o tempo de bloqueio será reiniciado.

Múltiplos erros 404 podem provocar o bloqueio temporário do endereço IP pelo servidor, como medida de segurança. Portanto, assegurar a correta construção das URLs é essencial.

Para evitar esses problemas, é importante que o código do município no nome do arquivo esteja corretamente formatado com 5 dígitos, sem omitir os zeros à esquerda.

Por fim, o arquivo de eleitos é gerado somente após a totalização final da primeira UF.

Aplicativo Resultados

* Para Android
* Para IOS
* Resultados versão Web

Audiência Técnica sobre a Divulgação dos Resultados das Eleições Gerais de 2026

O Tribunal Superior Eleitoral (TSE) realizou, no dia 6 de julho de 2026 , 15h, a Audiência Técnica sobre a Divulgação dos Resultados das Eleições Gerais de 2026 , destinada às instituições, empresas e demais entidades interessadas em receber e divulgar os resultados oficiais das eleições.

Durante o encontro, foram apresentadas as diretrizes do modelo de distribuição dos dados eleitorais, bem como os requisitos tecnológicos, operacionais e de segurança que deverão ser observados pelas entidades participantes.

Resolução: https://www.tse.jus.br/legislacao/compilada/res/2026/resolucao-no-23-751-de-26-de-fevereiro-de-2026

Art. 266. Até 10 de julho de 2026, o Tribunal Superior Eleitoral realizará audiência com as entidades interessadas em divulgar os resultados da eleição, para apresentar as definições do modelo de distribuição e os padrões tecnológicos e de segurança exigidos para a divulgação dos resultados.

* Audiência realizada em 06/07/2026 ( apresentação em pdf - gravação ).
* As dúvidas técnicas foram respondidas no FAQ.

Acompanhe este site do TSE para consultar o cronograma, documentos e demais atualizações.

Outras solicitações ou dúvidas devem ser registradas por meio do formulário: https://30308800.tse.jus.br/

Orientações para preenchimento:

* No campo Descrição , informe o assunto como “Resultados - Divulgação” , seguido de uma descrição detalhada da solicitação.
* Em caso de reabertura de chamado , informe o número do chamado anteriormente atendido para facilitar o acompanhamento.

Simulados

Os testes simulados permitiram que as entidades interessadas na divulgação de resultados validassem suas soluções.

1ª semana: 15, 16 e 17 de setembro de 2026 , das 9h às 12h e das 14h às 17h ; 2ª semana: 22, 23 e 24 de setembro de 2026 , das 9h às 12h e das 14h às 17h; 3ª semana de testes (semana extra): 28 e 29 de setembro de 2026, das 15h às 17h.

A abrangência do simulado compreende todo o País, onde serão gerados arquivos para todos os cargos em disputa (Presidente, Governador, Senador, Deputado Federal, Deputado Distrital, Deputado Estadual e Conselheiro Distrital).

Além da simulação da totalização dos votos, os cenários disponibilizados contemplarão diversas situações eleitorais específicas, com o objetivo de permitir a validação completa das soluções de divulgação de resultados.

Seções anuladas

Serão disponibilizados cenários contendo seções anuladas nas seguintes unidades da federação: AL, BA, MA e outras.

Entre os municípios contemplados estão Salvador (BA), Belo Horizonte (MG), Rio de Janeiro (RJ), Porto Alegre (RS), Boa Vista (RR) e São Paulo (SP) , além de diversos municípios do interior.

Seções não instaladas

* BA : Ibirapuã (Zona 153) - 1 seção não instalada.

Destinações de votos diferenciadas

Partidos com destinação "Anulado sub judice"

* Deputado Federal : AM (Partido 90) BA (Partidos 69 e 84)

* Deputado Federal : AM (Partido 90) BA (Partidos 69 e 84)

* AM (Partido 90)
* BA (Partidos 69 e 84)

Candidatos com destinação "Anulado"

* Presidente : BR Governador : AM, MS e SP Senador : AP, RO, RR e outras Deputado Federal : BA Deputado Estadual : RO

* Presidente : BR
* Governador : AM, MS e SP
* Senador : AP, RO, RR e outras
* Deputado Federal : BA
* Deputado Estadual : RO

Candidatos com destinação "Anulado sub judice"

* Cenários distribuídos em diversos cargos e unidades da federação.

* Cenários distribuídos em diversos cargos e unidades da federação.

Candidatos com destinação "Válido (legenda)"

* Deputado Federal : AC, SC e RR Deputado Estadual : RR

* Deputado Federal : AC, SC e RR
* Deputado Estadual : RR

Votos nulos técnicos

* Deputado Federal : AM Deputado Estadual : AC e BA

* Deputado Federal : AM
* Deputado Estadual : AC e BA

Candidatos substituídos

* Governador (MA) : CANDIDATO 9931 → CANDIDATO 9999 Senador (AC) : CANDIDATO 9366 → CANDIDATO 9998 Deputado Estadual (AC) : CANDIDATO 9840 → CANDIDATO 9997

* Governador (MA) : CANDIDATO 9931 → CANDIDATO 9999
* Senador (AC) : CANDIDATO 9366 → CANDIDATO 9998
* Deputado Estadual (AC) : CANDIDATO 9840 → CANDIDATO 9997

Eleição matematicamente definida

Os cenários contemplarão situações em que a eleição esteja matematicamente definida antes da totalização completa dos votos.

1º Turno - Governador: RR

2º Turno - Governador: MG, PI, SP e outras

Eleição sem atribuição de eleito

Os cenários também incluirão casos nos quais não haverá atribuição de candidato eleito.

Governador: AP

Senador: AM,  AP, DF, ES e outras

O acesso aos resultados continuará sendo realizado por meio de arquivos JSON, conforme a documentação disponibilizada na aba Documentos.

No início do período de testes, todos os arquivos estarão disponíveis com zero votos , simulando o momento anterior ao início da totalização.

Ao longo do período, serão gerados arquivos contendo votação, simulando o andamento da totalização .

Próximo ao horário do fim do teste, espera-se que todos os arquivos apresentem 100% das seções totalizadas .

Ao final, será gerado um arquivo com a totalização final contendo a indicação dos candidatos eleitos .

Será permitido um máximo de 100 requisições por IP por segundo . Caso esse limite seja ultrapassado, poderá haver um bloqueio de 10 minutos . Se uma nova tentativa for feita antes do término, o tempo de bloqueio será reiniciado.

Múltiplos erros 404 podem provocar o bloqueio temporário do endereço IP pelo servidor, como medida de segurança. Portanto, assegurar a correta construção das URLs é essencial.

Para evitar esses problemas, é importante que o código do município no nome do arquivo esteja corretamente formatado com 5 dígitos, sem omitir os zeros à esquerda, quando aplicável.

Por fim, o arquivo de eleitos estará disponível somente após a totalização final da primeira UF.

Quanto aos códigos do ambiente de produção, serão publicados oportunamente.

O acesso aos arquivos será realizado com os seguintes parâmetros:

* url: https://resultados-sim.tse.jus.br/simulado
* ambiente: simulado2026
* códigos das eleições: Pleito 17801 21270 - Eleição Ordinária Federal 21272 - Eleição Ordinária Estadual 21274 - Eleição Ordinária Municipal

* 21270 - Eleição Ordinária Federal
* 21272 - Eleição Ordinária Estadual
* 21274 - Eleição Ordinária Municipal

Exemplos de URLs:

* Arquivo de configuração das eleições: https://resultados-sim.tse.jus.br/simulado/simulado2026/comum/config/ele-c.json
* Acompanhamento da totalização do Brasil: https://resultados-sim.tse.jus.br/simulado/simulado2026/ele2026/21270/dados/br/br-e021270-ab.json
* Acompanhamento da totalização da UF (AC): https://resultados-sim.tse.jus.br/simulado/simulado2026/ele2026/21270/dados/ac/ac-e021270-ab.json
* Resultado de Presidente da República (Brasil): https://resultados-sim.tse.jus.br/simulado/simulado2026/ele2026/21270/dados/br/br-c0001-e021270-u.json
* Resultado de Governador (AC): https://resultados-sim.tse.jus.br/simulado/simulado2026/ele2026/21272/dados/ac/ac-c0003-e021272-u.json
* Resultado de Senador por município (Acrelândia/AC): https://resultados-sim.tse.jus.br/simulado/simulado2026/ele2026/21272/dados/ac/ac01120-c0005-e021272-u.json
* Arquivo de configuração de municípios: https://resultados-sim.tse.jus.br/simulado/simulado2026/ele2026/21270/config/mun-e021270-cm.json

URL do Resultados (simulado) para validação dos dados:

https://resultados-sim.tse.jus.br/simulado/simulado2026/app/index.html

Eventuais dúvidas ou bloqueios durante o simulado devem ser registrados por meio do formulário, para que seja considerado igualmente a criticidade e o impacto de cada solicitação.

#### Informações Gerais

Sim. A apresentação e o link da gravação da audiência foram disponibilizados aqui no site.

Não. Os resultados das eleições são disponibilizados publicamente pela Justiça Eleitoral. Os interessados podem desenvolver e utilizar soluções próprias de divulgação, observadas as orientações técnicas, a documentação disponibilizada, os limites de acesso da plataforma e as disposições da Resolução TSE nº 23.751, de 26 de fevereiro de 2026.

Não. Cada consumidor pode utilizar os arquivos e informações de seu interesse, observadas as regras de divulgação e as estruturas definidas na documentação técnica.

O modelo de dados será bastante semelhante ao utilizado na eleição anterior. Recomenda-se consultar a documentação disponibilizada para verificar eventuais ajustes e particularidades desta eleição.

Os documentos atualmente publicados já estão vigentes e devem ser considerados como referência. Caso seja identificada a necessidade de ajustes ou complementações, novas versões poderão ser disponibilizadas oportunamente.

Não. Não há previsão de alteração no uso do campo vag em relação ao modelo atualmente documentado.

O IDG é um identificador único atribuído a cada arquivo gerado, independentemente do seu tipo. Cada geração recebe um IDG próprio, utilizado para sua identificação inequívoca no sistema. Assim, arquivos distintos recebem identificadores distintos, ainda que tenham sido gerados no mesmo processamento ou carga.

O valor de [ambiente] será oficial .

Os valores de [ciclo] , e<ELEICAO> e p<PLEITO> poderão ser obtidos por meio do arquivo de configuração de eleições ele-c.json.

O arquivo EA10 permanece conforme especificado na documentação vigente.

Quanto ao cargo de Senador, embora nas Eleições Gerais de 2026 cada eleitor possa votar em dois candidatos, trata-se de um único cargo com duas vagas em disputa. Dessa forma, os eleitos são divulgados normalmente por meio do registro do cargo Senador no arquivo de eleitos.

Em relação ao cargo de Presidente da República, não há previsão de disponibilização de um arquivo EA10 específico e a informação pode ser obtida diretamente a partir da totalização nacional disponível no arquivo EA20 de abrangência Brasil.

Não há previsão de alteração da estrutura dos arquivos além do que já está definido na documentação publicada. Eventuais mudanças serão comunicadas por meio de atualização da documentação oficial no site.

Não necessariamente.

Os arquivos EA10 passam a ser gerados após a ocorrência da primeira totalização final de uma UF e são atualizados à medida que novas totalizações finais ocorram em outras UFs.

Além disso, podem existir situações em que a atribuição de eleitos para determinado cargo não seja possível imediatamente, em razão de pendências judiciais envolvendo candidatos. Nesses casos, o arquivo poderá existir mesmo sem a definição dos eleitos para todos os cargos ou abrangências.

Sim. Caso seja realizada uma requisição para um arquivo EA10 que ainda não tenha sido gerado, a resposta esperada será HTTP 404 (Not Found) .

Para os fins de totalização e geração dos arquivos, o cargo de Presidente da República segue as regras de Eleição Federal, enquanto os cargos de Governador, Senador, Deputado Federal e Deputado Estadual/Distrital seguem as regras de Eleição Estadual.

Eleição Estadual (Governador, Senador, Deputado Federal e Deputado Estadual/Distrital)

* Arquivo de abrangência municipal: and=f quando snt=0 ;
* Arquivo de abrangência estadual: and=f quando houver totalização final;
* Arquivo de abrangência federal: and=f quando houver totalização final em todas as UFs do país.

Eleição Federal (Presidente da República)

* Arquivo de abrangência municipal: and=f quando snt=0 ;
* Arquivo de abrangência estadual: and=f quando snt=0 ;
* Arquivo de abrangência federal: and=f quando houver totalização final.

Os arquivos são atualizados conforme a evolução do processo de totalização de cada abrangência e divulgação dos resultados.

Os consumidores devem observar os limites de acesso estabelecidos para o serviço e no simulado verificaremos as possibilidades de intervalo de polling recomendado.

Sim. A CDN suporta os mecanismos padrão do protocolo HTTP, incluindo ETag e Last-Modified. Quando utilizadas validações condicionais, a CDN poderá retornar HTTP 304 (Not Modified) para arquivos que não sofreram alterações, evitando a retransmissão do conteúdo do arquivo. As requisições que resultarem em HTTP 304 também são contabilizadas para fins de rate limit.

Não necessariamente. Os boletins de urna são utilizados no processo de totalização que gera os arquivos JSON de divulgação. A disponibilização de um tipo de arquivo em relação ao outro será de acordo com a sincronização da CDN.

Não está prevista a disponibilização de arquivos de índice para identificação de atualizações.

Para os arquivos auxiliares da seção, o arquivo de configuração de seções eleitorais ( EA16 ) disponibiliza os atributos da e ha , que informam, respectivamente, a data e a hora de geração do arquivo auxiliar da seção. Esses atributos são disponibilizados para seções principais após a geração do respectivo arquivo auxiliar e podem ser utilizados para identificar a chegada dos arquivos de urna da seção eleitoral.

Sim. Os arquivos de acompanhamento podem ser utilizados para esse fim. O EA14 permite identificar atualizações nas UFs, enquanto o EA15 possibilita acompanhar as atualizações dos municípios de uma determinada UF.

As datas e horas de totalização presentes nesses arquivos constituem um forte indicativo de atualização dos respectivos arquivos EA20. Como os arquivos são gerados em paralelo e posteriormente sincronizados e distribuídos pela CDN, podem ocorrer diferenças no momento em que cada arquivo passa a refletir os dados atualizados.

A infraestrutura da CDN será dimensionada para suportar o volume esperado de acessos durante a divulgação dos resultados e utilizará os recursos de disponibilidade, distribuição e resiliência oferecidos pela plataforma.

O limite é de 100 requisições por segundo por IP .

Caso esse limite seja excedido, poderá ocorrer bloqueio por 10 minutos , renovado enquanto persistir a condição que originou o bloqueio.

Não. Não está prevista a utilização de whitelist de IP para acesso aos arquivos de divulgação.

Não há um limiar divulgado. Requisições para endereços incorretos que resultem em HTTP 404 podem ocasionar bloqueio.

Recomenda-se atenção à construção das URLs, uma vez que não é possível listar os arquivos diretamente na infraestrutura de disponibilização.

Estão previstos simulados para o mês de setembro de 2026, permitindo que as entidades interessadas na divulgação de resultados validem suas soluções.

Informações adicionais sobre cronograma, disponibilização dos arquivos de teste e orientações operacionais serão divulgadas oportunamente.

As políticas e restrições de acesso da plataforma deverão ser observadas também durante os simulados, salvo orientação em contrário.

Não há previsão da necessidade de realização de cadastro, basta seguir às orientações da audiência, além, das constantes na aba Documentos do site, para a construção da sua solução, e seguir as regras da resolução.

Não. As URLs de acesso e demais informações operacionais serão divulgadas oportunamente.

Está sendo avaliada a disponibilização de arquivos de exemplo. O modelo de dados para 2026 permanece bastante semelhante ao modelo de dados de 2024. Recomenda-se, entretanto, a leitura da documentação vigente para identificação de eventuais ajustes e novos atributos.

Os documentos para informar e instruir as entidades interessadas em divulgar o resultado das Eleições 2026 estão disponibilizados abaixo.

Orientações sobre o processo de divulgação:

Instruções para download dos arquivos da divulgação

Especificações de arquivos JSON de resultados da divulgação:

* EA10 – Arquivo de resultado de eleitos
* EA11 – Arquivo de configuração de eleições
* EA12 – Arquivo de configuração de municípios
* EA14 – Arquivo de acompanhamento Brasil
* EA15 – Arquivo de acompanhamento UF
* EA16 – Arquivo de configuração de seções eleitorais
* EA18 – Arquivo auxilar de seção
* EA20 – Arquivo de resultado unificado

Outros arquivos

* Manual de verificação dos arquivos jws
* Audiência realizada em 06/07/2026 ( apresentação em pdf ).
