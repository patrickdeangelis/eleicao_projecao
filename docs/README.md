# Documentação do Projeto: Apuração Eleitoral TSE

Nesta pasta você encontra a documentação técnica e arquitetural para o desenvolvimento de soluções de apuração eleitoral em tempo real utilizando os dados oficiais do TSE:

- [Guia Completo de Apuração Eleitoral (TSE)](guia_apuracao_tse.md): Documento com especificações de endpoints da CDN, tabelas de códigos de cargos, dicionário completo de campos do JSON, arquitetura recomendada (worker + cache + SSE) e código de exemplo em Python e HTML/JS.
- [Ciência Estatística e Projeção em Tempo Real](modelo_estatistico_projecao_apuracao.md): Modelagem matemática e probabilística baseada em Inferência Bayesiana Sequencial (Dirichlet-Multinomial), Pós-Estratificação em 4 Níveis (Cidades > 100k, Interior Remanescente), Pacing de Rede e Simulação de Monte Carlo com implementação em Python.
- [Especificação Técnica do Sistema (SRS) - Dashboard Desktop](especificacoes_do_sistema.md): Especificação formal da aplicação desktop (arquitetura local desacoplada, requisitos RF/RNF, persistência SQLite com Time-Travel Replay, pilha PyWebView/FastAPI/ECharts ou PySide6, e contratos de dados).
- [Arquitetura Desacoplada e Modular do Sistema (SPETR)](arquitetura_de_modulos.md): Detalhamento da arquitetura em camadas (Clean Architecture/Hexagonal), barramento de eventos assíncrono (EventBus in-process), contratos com Python Protocols, árvore de diretórios e ciclo de vida da aplicação desktop.

