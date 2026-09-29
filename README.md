# Pipeline Pokédex — arquitetura medalhão (MongoDB → PostgreSQL)

Pipeline ETL que extrai a PokéAPI e o conjunto de batalhas `pokemon_app` (arquivos `pokemon.csv` e `combats.csv`), preserva o dado bruto em MongoDB (bronze), concilia e modela as duas fontes em um esquema estrela no PostgreSQL (silver) e publica agregados no grão de cada pergunta de negócio (gold).

O código-fonte (Python e SQL) não contém comentários, por decisão do grupo: toda a explicação do projeto está concentrada neste README e no `RELATORIO.md`. A seção 9 relaciona cada instrução de `sql/consultas.sql` à análise que ela responde.

## Sumário

1. Estrutura do repositório
2. Execução
3. Bronze — MongoDB
4. Silver — esquema estrela
5. As seis decisões de modelagem
6. Conciliação de chaves
7. Gold — agregados publicados
8. Análise proposta pelo grupo
9. Mapa de `consultas.sql`
10. Idempotência por camada
11. Decisões não especificadas pelo enunciado
12. Bibliotecas (R11)
13. Perguntas não previstas — exemplos sobre o silver

---

## 1. Estrutura do repositório

```
.
├── extrair.py               fontes → bronze (MongoDB), sem transformar
├── carregar.py              bronze → silver (PostgreSQL), concilia e modela
├── publicar.py              silver → gold, agregação inteiramente no banco
├── gerar_relatorio.py       executa sql/consultas.sql e preenche o RELATORIO.md
├── sql/
│   ├── controle.sql         schema controle: registro das execuções
│   ├── silver.sql           DDL do esquema estrela (PK, FK, CHECK)
│   ├── gold.sql             DDL das tabelas agregadas
│   ├── gold_carga.sql       INSERT INTO gold.* SELECT ... FROM silver.*
│   └── consultas.sql        as oito análises finais
├── conciliacao.csv          relatório de conciliação por registro (gerado pelo carregar.py)
├── conciliacao_resumo.md    resumo da conciliação (gerado pelo carregar.py)
├── RELATORIO.modelo.md      modelo do relatório, com marcadores de resultado
├── RELATORIO.md             resultados e interpretação das oito análises
├── docker-compose.yml       MongoDB 7 e PostgreSQL 16
└── requirements.txt
```

`dados_brutos/` (cache das respostas HTTP) é criado pelo `extrair.py` e está no `.gitignore`.

## 2. Execução

### 2.1 Bancos

Opção com contêineres (usada pelo grupo):

```bash
docker compose up -d
```

Sobe o MongoDB em `localhost:27017` e o PostgreSQL em `localhost:5432` (usuário, senha e banco `pokedex`). Os volumes nomeados preservam os dados entre reinicializações; `docker compose down -v` apaga tudo e devolve os dois bancos ao estado vazio.

Opção com a máquina virtual da disciplina ou instalação local: basta que os dois serviços estejam ativos e que as variáveis de ambiente abaixo apontem para eles. No PostgreSQL é necessário um banco e um usuário com permissão de criar schemas:

```sql
CREATE USER pokedex WITH PASSWORD 'pokedex';
CREATE DATABASE pokedex OWNER pokedex;
```

| Variável | Padrão | Uso |
|---|---|---|
| `MONGO_URI` | `mongodb://localhost:27017` | extrair, carregar |
| `MONGO_DB` | `pokedex_bronze` | extrair, carregar |
| `PG_DSN` | `postgresql://pokedex:pokedex@localhost:5432/pokedex` | carregar, publicar, gerar_relatorio |
| `CACHE_DIR` | `./dados_brutos` | extrair |

### 2.2 Ambiente Python

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2.3 Ordem de execução

```bash
python extrair.py        # fontes → bronze   (primeira vez: ~1.600 requisições, alguns minutos)
python carregar.py       # bronze → silver   (não usa rede)
python publicar.py       # silver → gold
python gerar_relatorio.py
psql "$PG_DSN" -f sql/consultas.sql
```

Cada script imprime, ao final, a contagem de documentos ou linhas por coleção ou tabela. A segunda execução de `extrair.py` informa `Requisições HTTP realizadas nesta execução: 0`.

O histórico das cargas fica em `controle.execucao`:

```sql
SELECT etapa, tabela, linhas, executado_em FROM controle.execucao ORDER BY id_execucao DESC;
```

## 3. Bronze — MongoDB

Banco `pokedex_bronze`, cinco coleções:

| Coleção | `_id` | Documentos esperados |
|---|---|---|
| `pokemon` | `pokemon/{id}` | uma forma por documento: as 721 formas padrão e todas as formas de `varieties[]` (inclui formas posteriores à geração VI, como as regionais; o silver usa apenas as que o CSV referencia) |
| `especies` | `especie/{id}` | 721 |
| `tipos` | `tipo/{id}` | 21 (os 18 reais, `stellar`, `unknown` e `shadow`) |
| `pokemon_csv` | `pokemon_csv/{#}` | 800 |
| `combates` | `combate/{linha}` | 50.000 |

### 3.1 Por que um banco de documentos nesta camada

A camada bronze precisa guardar a resposta exatamente como a fonte entregou. O JSON da PokéAPI tem características que um esquema relacional não comporta sem transformação:

- **Listas de objetos aninhados de tamanho variável.** `stats[]` é uma lista de objetos `{base_stat, effort, stat: {name, url}}`; `types[]` traz `{slot, type: {name, url}}`; `abilities[]` traz `{ability, is_hidden, slot}`. Em tabela relacional cada uma dessas listas exigiria uma tabela filha e uma chave de ligação, isto é, exatamente o achatamento que a camada proíbe.
- **Profundidade arbitrária.** `sprites` contém `versions → generation-i → red-blue → front_default`, com chaves que variam por geração e jogo; `damage_relations` contém seis listas de referências a tipos; `species` em `/pokemon-species/` contém `flavor_text_entries[]` com centenas de entradas multilíngues e `varieties[]` com referências às formas.
- **Esquema heterogêneo entre documentos.** Formas alternativas (ids acima de 10000) não possuem documento de espécie; `habitat` e `shape` podem ser `null`; `base_experience` é nulo em algumas formas; a quantidade de tipos, habilidades e variedades muda de um documento para outro. Um banco de documentos aceita cada resposta com a forma que ela tem.
- **Evolução da fonte.** Campos novos que a PokéAPI venha a acrescentar entram no bronze sem alteração de esquema; o silver decide o que usar.

Uma coluna `JSONB` no PostgreSQL também armazenaria o documento, mas colocaria bronze e silver no mesmo banco e não é o que a arquitetura exigida prescreve. O MongoDB oferece ainda o `_id` como chave natural, o que reduz a idempotência a um upsert.

### 3.2 Regras aplicadas

- **Sem transformação.** O documento é o JSON da resposta (`json.loads` do corpo) acrescido de campos de linhagem prefixados por `_`. As linhas do CSV são gravadas com os nomes de coluna originais (`#`, `Type 1`, `Sp. Atk`...) e todos os valores como texto, como o módulo `csv` os lê.
- **Linhagem.** Todo documento tem `_fonte` (`pokeapi` ou `pokemon_app_csv`), `_url` (URL consultada), `_arquivo` (caminho do cache em disco) e `_ingerido_em`. Os documentos do CSV têm também `_linha`.
- **`_ingerido_em`** é o instante em que a resposta foi obtida da fonte, lido da data de modificação do arquivo de cache. Assim, reexecutar o script não altera o valor: o dado não foi obtido de novo.
- **Cache em disco antes do MongoDB.** `dados_brutos/{pokemon,especies,tipos,listas,csv}/`. A rede só é usada quando o arquivo não existe; o arquivo é gravado primeiro com sufixo `.parcial` e renomeado, para que uma interrupção não deixe cache corrompido. Intervalo de 0,1 s entre requisições e novas tentativas com espera exponencial para HTTP 429 e 5xx.
- **Upsert por `_id`.** A escrita usa `ReplaceOne(filtro_por_id, documento, upsert=True)` em lotes. O grupo optou por substituição em vez de `update_one` com `$set` porque o cabeçalho do CSV contém `Sp. Atk` e `Sp. Def`: dentro de `$set`, o ponto é interpretado como caminho de subdocumento, o que gravaria `{"Sp": {" Atk": ...}}` — uma transformação. Na substituição o nome do campo é preservado. O efeito sobre a idempotência é o mesmo.

## 4. Silver — esquema estrela

### 4.1 Grão (RS1)

> **Cada linha de `silver.fato_confronto` representa a participação de um Pokémon (um registro do `pokemon.csv`) em um combate do `combats.csv`, vista do lado desse Pokémon: contra quem lutou, se atacou primeiro e se venceu.**

Cada combate gera exatamente duas linhas; a fato tem 100.000 linhas para 50.000 combates. A chave primária é `(id_combate, atacou_primeiro)`.

### 4.2 Diagrama

```
                                   ┌──────────────────────────┐
                                   │     silver.dim_geracao   │
                                   │  sk_geracao (PK)         │
                                   │  numero_geracao, nome,   │
                                   │  regiao                  │
                                   └──────────▲───────────────┘
                                   sk_geracao │ sk_geracao_oponente
┌──────────────────────────┐       ┌──────────┴───────────────┐       ┌──────────────────────────┐
│    silver.dim_pokemon    │       │  silver.fato_confronto   │       │     silver.dim_tipo      │
│  sk_pokemon (PK)         │◄──────┤ id_combate      (PK)     ├──────►│  sk_tipo (PK)            │
│  numero_csv, numero_     │ sk_   │ atacou_primeiro (PK)     │ sk_   │  id_tipo_pokeapi,        │
│  pokedex, id_pokeapi,    │ poke- │ sk_pokemon, sk_oponente  │ tipo_ │  nome_tipo, nome_tipo_pt │
│  nome, especie, tipos,   │ mon   │ sk_tipo_primario/_secund.│ primá-│                          │
│  geração, raridade,      │ sk_   │ sk_tipo_oponente_prim./  │ rio,  │  -2 = Sem segundo tipo   │
│  habitat, cor, forma,    │ opo-  │   _secundario            │ ... 4 │                          │
│  hp ... velocidade,      │ nente │ sk_geracao, sk_geracao_  │ papéis│                          │
│  total_status            │       │   oponente               │       │                          │
│  -1 = Não informado      │       │ venceu (0/1)             │       └───────────▲──────────────┘
└──────────────────────────┘       │ diferenca_velocidade     │                   │ sk_tipo_atacante
                                   │ diferenca_total_status   │                   │ sk_tipo_defensor
                                   └──────────────────────────┘       ┌───────────┴──────────────┐
                                                                      │ silver.efetividade_tipo  │
                                                                      │ (324 linhas)             │
                                                                      │ multiplicador 0/0,5/1/2  │
                                                                      └──────────────────────────┘
```

Todas as dimensões ligam-se diretamente à fato (RS2). A `dim_pokemon` não referencia `dim_tipo` nem `dim_geracao`: os nomes do tipo e da geração são repetidos nela como texto, de forma desnormalizada, o que evita o floco de neve e permite responder às análises 1 e 2 sem junção. `efetividade_tipo` é uma tabela de referência entre dois papéis de `dim_tipo`, fora do esquema estrela, como na estrutura sugerida.

### 4.3 Tabelas

| Tabela | Linhas | Conteúdo |
|---|---:|---|
| `dim_geracao` | 6 | geração, nome (`Geração I`) e região (`Kanto` ... `Kalos`) |
| `dim_tipo` | 19 | 18 tipos (nome em inglês, como no CSV, e em português) e o membro especial `-2` |
| `dim_pokemon` | 800 | um registro do CSV por linha: chaves naturais (`numero_csv`, `numero_pokedex`, `id_pokeapi`), nome, espécie, categoria da forma, situação da conciliação, tipos, geração, raridade, habitat, cor, forma corporal, taxa de crescimento, grupos de ovo, taxa de captura, felicidade base, experiência base, altura, peso, quantidade de habilidades e os seis atributos de status com o total |
| `efetividade_tipo` | 324 | multiplicador de cada tipo atacante contra cada tipo defensor |
| `fato_confronto` | 100.000 | participações em combate |

Requisitos atendidos:

- **RS3.** Toda dimensão tem chave substituta inteira gerada pelo PostgreSQL (`GENERATED BY DEFAULT AS IDENTITY`). `numero_csv`, `numero_pokedex`, `id_pokeapi` e `id_tipo_pokeapi` são atributos, nunca chaves.
- **RS4.** Nenhuma chave estrangeira da fato é nula (`NOT NULL` em todas). A ausência é representada por membros especiais (seção 4.4).
- **RS5.** `PRIMARY KEY` em todas as tabelas, `FOREIGN KEY` em todas as chaves da fato e da `efetividade_tipo`, e `CHECK` em `venceu`, `atacou_primeiro`, `multiplicador`, `categoria_raridade` e `categoria_forma`. O `carregar.py` ainda confere, dentro da transação, se a fato tem 2 × 50.000 linhas, 50.000 combates distintos e 50.000 vitórias; se não tiver, a transação é desfeita.
- **RS6.** As métricas de batalha são colunas numéricas da fato: `venceu` (0/1), `atacou_primeiro` (0/1), `diferenca_velocidade` e `diferenca_total_status`. Taxa de vitórias é `AVG(venceu)`.
- **RS7.** `efetividade_tipo` materializa `damage_relations`; a análise 6 é obtida por junção da fato com essa tabela.
- **RS8.** Nenhuma análise usa o bronze, a API ou os CSV.

### 4.4 Membros especiais

Os problemas 2 e 3 da seção 1.4 do enunciado aparecem como nulo, mas são coisas diferentes, e o modelo os distingue:

| Situação | Natureza | Onde | Representação |
|---|---|---|---|
| Registro `#63` sem nome | **dado ausente**: o Pokémon existe, o nome não foi registrado | `dim_pokemon` | membro especial `sk_pokemon = -1`, nome `Não informado (registro #63)`, `status_conciliacao = sem_nome` |
| Pokémon com um só tipo | **não se aplica**: não existe segundo tipo | `dim_tipo` (papéis `sk_tipo_secundario` e `sk_tipo_oponente_secundario`) | membro especial `sk_tipo = -2`, `Sem segundo tipo` |
| Habitat das espécies a partir da geração IV | **não se aplica**: o conceito não existe nesses jogos | atributo `dim_pokemon.habitat` | texto `Não se aplica` |
| Atributos da PokéAPI do registro `#63` e de eventuais não conciliados | **dado ausente** | atributos da `dim_pokemon` | texto `Não informado`; atributos numéricos ficam nulos (não são chaves) |

Convenção de chaves: `-1` para ausência, `-2` para inaplicabilidade.

O membro `-1` mantém os atributos que o CSV fornece para a linha 63 (tipo Lutador, geração I, status). Só a identidade é desconhecida; descartar os atributos conhecidos seria perder informação e tiraria os combates dessa linha das análises de tipo e velocidade. Os combates do registro 63 permanecem todos na fato: entram 50.000 combates e permanecem 50.000.

A `dim_tipo` não tem membro `-1` porque nenhum tipo está ausente nas fontes: todos os registros do CSV têm tipo primário. Se aparecer um tipo desconhecido, o `carregar.py` interrompe a carga em vez de mascarar o problema. A `dim_geracao` não tem membro especial porque a geração é conhecida para todos os registros.

## 5. As seis decisões de modelagem

### Decisão 1 — Grão da tabela fato: uma linha por participação

**Escolha.** Duas linhas por combate, uma do ponto de vista de cada Pokémon.

**Justificativa.** Todas as análises de batalha perguntam "como se sai um Pokémon (ou tipo, ou faixa) quando luta". No grão por participação isso é sempre `AVG(venceu)` agrupado por uma coluna do próprio participante. No grão por combate, cada Pokémon aparece ora em `First_pokemon`, ora em `Second_pokemon`, e toda análise precisaria de `UNION ALL` das duas colunas ou de expressões condicionais, com risco de contar um combate duas vezes ou esquecer um dos lados. A análise 7 mostra a diferença: a célula (A, B) é simplesmente `AVG(venceu)` das linhas com `sk_tipo_primario = A` e `sk_tipo_oponente_primario = B`, e as células (A, B) e (B, A) somam 1 por construção.

**Custo.** O dobro de linhas (100.000). Quem quiser contar combates, e não participações, usa `COUNT(DISTINCT id_combate)`. Uma consequência que precisa ser lembrada na leitura: a taxa de vitórias média de toda a fato é exatamente 0,5, e a taxa de um agrupamento deve ser comparada a 0,5.

### Decisão 2 — Comparação entre os lados: diferença gravada na fato

**Escolha.** `diferenca_velocidade = velocidade do participante − velocidade do oponente` e `diferenca_total_status` gravadas na fato durante a carga.

**Justificativa.** Calcular em consulta exigiria juntar a fato com a `dim_pokemon` duas vezes (participante e oponente) em toda consulta sobre velocidade. Como o grão é por participação, a diferença gravada já está orientada ao participante: a linha do lado mais rápido tem diferença positiva e a do lado mais lento, negativa, e a mesma coluna responde "o mais rápido vence?" sem `CASE`. A diferença de total de status foi incluída para perguntas não previstas (por exemplo, "o Pokémon com mais status vence?").

**Custo.** Duas colunas `SMALLINT` em 100.000 linhas (cerca de 400 kB) e a necessidade de recarregar a fato se os status mudarem. Como a carga sempre repovoa a fato inteira, esse custo não existe na prática.

### Decisão 3 — Efetividade de tipos: tabela `efetividade_tipo` tipo × tipo, e multiplicador efetivo por junção

**Escolha.** Tabela de 324 linhas `(sk_tipo_atacante, sk_tipo_defensor, multiplicador)`, preenchida a partir das listas `double_damage_to`, `half_damage_to` e `no_damage_to` de cada tipo, com 1 para os pares não listados. As listas `_from` são usadas apenas para conferir a consistência. O multiplicador efetivo de um confronto é obtido por duas junções:

```sql
e1.multiplicador * COALESCE(e2.multiplicador, 1)
```

em que `e1` é o par tipo primário do participante × tipo primário do oponente, e `e2` o par tipo primário do participante × tipo secundário do oponente.

Quando o oponente tem um só tipo, `sk_tipo_oponente_secundario = -2` não encontra par na tabela e o `COALESCE` devolve 1.

**Critério da análise 6.** O grupo adotou **os dois tipos do defensor**, portanto seis valores possíveis (0; 0,25; 0,5; 1; 2; 4). O atacante é representado pelo **tipo primário** do participante, porque os dados não registram golpes. A análise 7 usa a mesma tabela no critério tipo a tipo (quatro valores), que é o que a matriz pede.

**Justificativa.** A tabela é o dado da fonte, sem nenhuma escolha analítica embutida, e serve às duas análises com critérios diferentes. Gravar o multiplicador como coluna da fato fixaria um único critério (primário × primário ou primário × ambos) e duplicaria em 100.000 linhas uma informação que tem 324. Uma dimensão de confronto com todas as combinações de tipo atacante e par de tipos defensor teria milhares de linhas e só adiantaria o produto.

**Custo.** Duas junções a mais nas consultas sobre efetividade. No pipeline elas ocorrem uma vez, no `publicar.py`.

### Decisão 4 — Oponente: dimensão papel

**Escolha.** A `dim_pokemon` é referenciada duas vezes pela fato (`sk_pokemon` e `sk_oponente`). O mesmo padrão vale para `dim_tipo` (quatro papéis: primário e secundário do participante e do oponente) e `dim_geracao` (dois papéis). Não foram criadas visões por papel; nas consultas, cada papel é um alias (`JOIN silver.dim_pokemon AS oponente ON oponente.sk_pokemon = f.sk_oponente`).

**Justificativa.** O oponente é a mesma entidade em outro papel; uma segunda tabela de Pokémon duplicaria o cadastro e poderia divergir dele. Os tipos e a geração do oponente foram gravados na fato como chaves próprias, e não apenas alcançáveis via `sk_oponente`, porque a análise 7 cruza tipo contra tipo e a análise 6 cruza tipo contra os dois tipos do oponente: com as chaves na fato, essas análises juntam a fato diretamente a `dim_tipo`/`efetividade_tipo`, sem passar pela `dim_pokemon`.

**Custo.** Seis colunas inteiras a mais na fato e a obrigação de manter coerência entre `sk_oponente` e os tipos do oponente, garantida porque todas vêm do mesmo registro durante a carga.

### Decisão 5 — Atributos de status: na dimensão, com as diferenças na fato

**Escolha.** HP, Ataque, Defesa, Ataque Especial, Defesa Especial, Velocidade e o total ficam na `dim_pokemon`. A fato guarda apenas as diferenças da decisão 2.

**Justificativa.** Os status descrevem o Pokémon e não mudam de combate para combate: são atributos de cadastro. Na dimensão, a análise 2 é uma média direta sobre ~800 linhas, sem a dupla contagem que ocorreria na fato (cada Pokémon aparece em ~125 participações e a média ficaria ponderada pelo número de combates). O que é próprio do combate é a comparação entre os dois lados, e é isso que a fato guarda.

**Custo.** Uma pergunta como "média de ataque dos vencedores" exige junção com a `dim_pokemon`. Como é uma junção pela chave primária, o custo é baixo.

Os status vêm do **CSV**, e não da PokéAPI. O programa que simulou as batalhas usou os números do CSV; os valores atuais da PokéAPI refletem ajustes feitos em jogos posteriores à geração VI. Para interpretar as batalhas, o dado relevante é o que o simulador viu. As divergências entre as duas fontes ficam registradas por registro na coluna `divergencias` do `conciliacao.csv`.

### Decisão 6 — Categoria de raridade: derivada na carga

**Escolha.** Coluna `categoria_raridade` na `dim_pokemon`, com os valores `Mítico`, `Lendário`, `Bebê`, `Comum` e `Não informado`, derivada dos indicadores `is_mythical`, `is_legendary` e `is_baby` da espécie, nessa ordem de precedência. O indicador `Legendary` do CSV é mantido em `lendario_csv` para auditoria (no CSV, míticos também são marcados como lendários).

**Justificativa.** A regra fica escrita em um único lugar e todas as consultas usam o mesmo rótulo. Deixá-la em `CASE` repetido em cada consulta abriria espaço para versões divergentes da mesma regra. Os três indicadores são mutuamente exclusivos na PokéAPI; a precedência só formaliza isso.

**Custo.** Mudar a regra exige recarregar o silver, o que o pipeline faz inteiro a cada execução.

## 6. Conciliação de chaves (R4)

O campo `#` do CSV é um índice sequencial, sem relação aritmética com a Pokédex. A correspondência é feita por nome, pela função `conciliar` do `carregar.py`, contra o índice de formas (`/pokemon/`) e espécies (`/pokemon-species/`) lido do bronze. As tentativas, em ordem:

1. **Normalização.** `♀`/`♂` viram `-f`/`-m`; apóstrofos, pontos, dois-pontos e `%` são removidos; acentos são retirados (`Flabébé → flabebe`); minúsculas; espaços e hífens viram um único hífen. Resolve `Nidoran♀`, `Farfetch'd`, `Mr. Mime`, `Mime Jr.`, `Ho-oh`, `Porygon-Z`, `Porygon2`.
2. **Exceções manuais** (`EXCECOES_MANUAIS`): nomes que a regra geral não resolve (Zygarde).
3. **Nome direto** em `/pokemon/` (`pikachu`, `groudon-primal`).
4. **Nome de espécie** → forma padrão da espécie (`Basculin → basculin-red-striped`).
5. **Tokenização.** O nome é quebrado em palavras (inclusive nomes colados, como `CharizardMega Charizard X`, e letras seguidas de números); localiza-se a maior sequência de palavras que forma o nome de uma espécie; as demais palavras, sem termos genéricos (`forme`, `form`, `cloak`, `size`, `mode`, `confined`), são os qualificadores. Testam-se `especie-qualificadores` em todas as ordens: `Mega Charizard X → charizard-mega-x`, `Primal Kyogre → kyogre-primal`, `Heat Rotom → rotom-heat`, `Black Kyurem → kyurem-black`, `Deoxys Attack Forme → deoxys-attack`, `Wormadam Sandy Cloak → wormadam-sandy`, `Pumpkaboo Super Size → pumpkaboo-super`. Sem qualificador restante, usa-se a forma padrão (`Hoopa Confined → hoopa`).
6. **Forma padrão inferida.** Se a espécie foi identificada mas nenhuma forma bate, usa-se a forma padrão da espécie e o registro é marcado com o método `especie_forma_padrao_inferida`, para conferência manual.
7. **Não conciliado.** O registro não é descartado: permanece na `dim_pokemon` com os atributos do CSV e `status_conciliacao = nao_conciliado`, e seus combates permanecem na fato.

O relatório tem duas partes, geradas a cada execução do `carregar.py`:

- `conciliacao.csv`: uma linha por registro do CSV, com `numero_csv`, nome original, nome normalizado, `status` (`conciliado`, `sem_nome`, `nao_conciliado`), método, forma e número da Pokédex encontrados, tratamento aplicado e divergências de tipo, status ou geração entre CSV e PokéAPI. Também sinaliza quando dois registros do CSV apontam para a mesma forma.
- `conciliacao_resumo.md`: quantidade de registros por situação e por método, e a relação de todos os não conciliados ou conciliados por inferência, com o tratamento de cada um.

Os dois arquivos são versionados no repositório depois da execução.

### Herança dos atributos de espécie

Formas alternativas existem em `/pokemon/`, mas não em `/pokemon-species/`. Cada documento de forma contém `species.name`; o `carregar.py` busca a espécie por esse nome e copia para a linha da forma: número da Pokédex, geração, habitat, cor, forma corporal, taxa de crescimento, grupos de ovo, taxa de captura, felicidade base e os indicadores de raridade. Altura, peso, experiência base e quantidade de habilidades são próprios da forma e vêm do documento da forma. Assim, `Mega Charizard X` herda geração I, habitat `mountain` e raridade `Comum` de `charizard`, mas tem o próprio peso.

A geração vem da espécie na PokéAPI; a coluna `Generation` do CSV só é usada para o registro sem nome e para não conciliados, e divergências entre as duas ficam no relatório.

## 7. Gold — agregados publicados

O `publicar.py` executa `sql/controle.sql` e `sql/gold.sql` (criação idempotente), esvazia as seis tabelas com `TRUNCATE` e executa `sql/gold_carga.sql`, que contém apenas `INSERT INTO gold.* SELECT ... FROM silver.*`. Toda a agregação ocorre no PostgreSQL; nenhuma linha do silver é trazida para o Python. Em seguida verifica o resultado (sete checagens: cada agregado soma as 100.000 participações, o ranking cobre todos os Pokémon, a matriz tem 324 células), registra as contagens em `controle.execucao` e só então confirma a transação.

| Tabela | Grão | Análise |
|---|---|---|
| `gold.ranking_pokemon` | um registro da `dim_pokemon` | 3 |
| `gold.taxa_vitorias_por_tipo` | um tipo primário | 4 |
| `gold.taxa_vitorias_por_faixa_velocidade` | uma faixa de diferença de velocidade | 5 |
| `gold.taxa_vitorias_por_multiplicador` | um multiplicador efetivo | 6 |
| `gold.matriz_confronto` | tipo atacante × tipo defensor | 7 |
| `gold.ganho_forma_alternativa` | uma forma alternativa, pareada à forma padrão da espécie | 8 |

### 7.1 Corte mínimo de combates (análise 3)

`gold.ranking_pokemon` guarda todos os Pokémon, inclusive os que não lutaram, com a coluna `combates`. O corte é aplicado na consulta: `WHERE combates >= 100`. Pode ser alterado sem reprocessar.

Justificativa do valor 100: são 100.000 participações para 800 registros, média de 125 combates por Pokémon. O erro-padrão de uma proporção é no máximo `0,5 / √n`; com 100 combates, 5 pontos percentuais, o que dá intervalo de confiança de 95% de aproximadamente ±10 p.p. Abaixo disso, diferenças entre os primeiros colocados se confundem com ruído. Como a média é 125, o corte elimina apenas a cauda de Pokémon com poucos combates, que é justamente onde aparecem taxas extremas espúrias. A distribuição pode ser conferida no silver:

```sql
SELECT MIN(c) AS minimo,
       percentile_cont(0.05) WITHIN GROUP (ORDER BY c) AS p05,
       percentile_cont(0.50) WITHIN GROUP (ORDER BY c) AS mediana,
       MAX(c) AS maximo,
       COUNT(*) FILTER (WHERE c < 100) AS abaixo_do_corte
FROM (SELECT p.sk_pokemon, COUNT(f.id_combate) AS c
      FROM silver.dim_pokemon p LEFT JOIN silver.fato_confronto f ON f.sk_pokemon = p.sk_pokemon
      GROUP BY p.sk_pokemon) x;
```

### 7.2 Faixas de diferença de velocidade (análise 5)

A velocidade base vai de 5 a 180, então a diferença vai de cerca de −175 a +175. Foram definidas nove faixas simétricas:

| Faixa | Intervalo |
|---|---|
| Mais lento por 60 ou mais | ≤ −60 |
| Mais lento por 30 a 59 | −59 a −30 |
| Mais lento por 10 a 29 | −29 a −10 |
| Mais lento por 1 a 9 | −9 a −1 |
| Mesma velocidade | 0 |
| Mais rápido por 1 a 9 | 1 a 9 |
| Mais rápido por 10 a 29 | 10 a 29 |
| Mais rápido por 30 a 59 | 30 a 59 |
| Mais rápido por 60 ou mais | ≥ 60 |

- **Zero isolado.** O empate é o único caso em que a velocidade não define quem age primeiro; misturá-lo a diferenças pequenas esconderia esse comportamento.
- **Faixas estreitas perto de zero.** Se a velocidade atua porque define quem ataca primeiro, o efeito aparece como um degrau entre −1 e +1, e as faixas de 1 a 9 pontos mostram isso. Se atua de forma gradual, a taxa cresce ao longo das faixas. As duas hipóteses dão leituras diferentes, e só faixas estreitas perto de zero permitem separá-las.
- **Faixas largas nas pontas.** Há menos confrontos com diferenças grandes; faixas estreitas ali teriam amostra pequena.
- **Simetria.** Pelo grão por participação, cada combate contribui com uma linha em uma faixa e outra na faixa espelhada; as taxas de faixas espelhadas somam 1. A tabela é lida pela metade positiva, e a negativa confirma a consistência.

### 7.3 Divergência na matriz (análise 7)

A célula (A, B) é a taxa de vitórias dos Pokémon de tipo primário A contra os de tipo primário B, orientada pelo vencedor (quem atacou primeiro não participa). O resultado esperado é `Vantagem` se o multiplicador A → B é maior que 1, `Desvantagem` se é menor e `Neutro` se é 1. A célula é **divergente** quando o multiplicador indica vantagem e a taxa é menor que 0,5, ou indica desvantagem e a taxa é maior que 0,5. Células neutras não são marcadas como divergentes, mas o desvio de 0,5 está disponível para leitura. As células da diagonal (A contra A) valem 0,5 por construção, já que cada combate entre dois Pokémon de mesmo tipo contribui com uma vitória e uma derrota à mesma célula.

## 8. Análise proposta pelo grupo

**Pergunta.** *A forma alternativa (Mega, Primal ou outra forma) vence mais do que a forma padrão da mesma espécie, e o ganho de taxa de vitórias acompanha o ganho de atributos?*

**Relevância.** As formas alternativas são a principal mecânica de "poder adicional" da geração VI (as Mega Evoluções e as formas Primal foram introduzidas nela). Para quem equilibra um jogo ou monta uma equipe, a pergunta é se a transformação compensa, isto é, se o ganho de taxa é consistente e proporcional ao ganho de status, ou se há formas que mudam atributos sem mudar o resultado (por exemplo, trocas entre ataque e defesa, como Aegislash e Darmanitan).

**Capacidade do modelo exigida e não exigida pelas sete anteriores.**

- **Relação entre membros da mesma dimensão por uma chave natural conciliada.** A forma alternativa é pareada à forma padrão pela coluna `numero_pokedex`, que só existe porque a conciliação resolveu o campo `#` para a espécie. Nenhuma das análises obrigatórias relaciona dois Pokémon entre si fora de um combate.
- **Atributo que nenhuma outra análise usa.** `categoria_forma` (`Padrão`, `Mega`, `Primal`, `Outra forma`), derivado de `is_default` e do nome da forma na PokéAPI.
- **Grão distinto.** Uma linha por par forma alternativa × forma padrão da mesma espécie.

Tabela: `gold.ganho_forma_alternativa`, com combates e taxa de cada lado, `ganho_taxa`, `diferenca_total_status` e `diferenca_velocidade`. Interpretação no `RELATORIO.md`.

## 9. Mapa de `consultas.sql`

As instruções estão na ordem abaixo, separadas por `;`.

| Instrução | Análise | Fonte |
|---:|---|---|
| 1 | 1 — Pokémon por tipo primário × geração (com linha de total) | silver |
| 2 | 2 — média de cada atributo por tipo primário | silver |
| 3 | 2 — posição de cada tipo em velocidade e resistência, número de atributos que lidera e se está acima da média geral em todos | silver |
| 4 | 3 — dez maiores taxas (≥ 100 combates) | gold |
| 5 | 3 — dez menores taxas (≥ 100 combates) | gold |
| 6 | 4 — taxa de vitórias por tipo primário | gold |
| 7 | 5 — taxa de vitórias por faixa de diferença de velocidade | gold |
| 8 | 6 — taxa de vitórias por multiplicador efetivo | gold |
| 9 | 7 — matriz 18 × 18 completa | gold |
| 10 | 7 — somente as células divergentes | gold |
| 11 | 8 — ganho da forma alternativa sobre a forma padrão | gold |

Resistência (análise 2) foi definida como HP + Defesa + Defesa Especial: é a quantidade de dano que o Pokémon suporta, e combina vida com as duas defesas.

As consultas 4 a 11 usam apenas `SELECT`, `WHERE`, `ORDER BY` e `LIMIT` sobre uma tabela do gold.

## 10. Idempotência por camada

| Camada | Mecanismo |
|---|---|
| Bronze | Cache em disco: a rede só é usada se o arquivo não existe, logo a segunda execução faz zero requisições. `_id` derivado da chave natural e `ReplaceOne(..., upsert=True)`: a segunda execução substitui cada documento por ele mesmo. `_ingerido_em` vem da data do arquivo de cache, e não do relógio, e por isso também não muda. |
| Silver | `CREATE ... IF NOT EXISTS`; `TRUNCATE ... RESTART IDENTITY` de todas as tabelas e recarga, tudo em uma única transação. A ordem de inserção é determinística (tipos por id, Pokémon por `#`, combates por linha), então as chaves substitutas são as mesmas em toda execução. Se qualquer etapa falhar, o silver anterior permanece intacto. |
| Gold | `CREATE ... IF NOT EXISTS`; `TRUNCATE` e `INSERT ... SELECT` na mesma transação, com verificação antes do `COMMIT`. |
| Controle | `controle.execucao` é um registro de execuções e, por definição, ganha linhas a cada execução. É o único ponto que cresce, e não faz parte de nenhuma camada analítica. |

## 11. Decisões não especificadas pelo enunciado

- **Tipos `stellar`, `unknown` e `shadow`.** Ficam no bronze (a camada não descarta nada) e são excluídos no silver: não existem no jogo que originou as batalhas, nenhum registro do CSV os usa e não fazem parte da tabela de efetividade entre os 18 tipos. Mantê-los criaria 21 × 21 pares de efetividade sem uso e um tipo "desconhecido" que se confundiria com o membro especial.
- **Tipos e status: CSV; classificação: PokéAPI.** Ver decisão 5. A PokéAPI reflete os jogos mais recentes; o CSV reflete o que o simulador usou.
- **Escopo da extração.** Todas as variedades das 721 espécies são extraídas, inclusive formas posteriores à geração VI (regionais, Gigantamax). O enunciado pede todas as formas de `varieties[]`, e o bronze deve ser completo; o silver usa só o que o CSV referencia.
- **Nomes de tipo em português.** `dim_tipo` guarda o nome da PokéAPI (`fire`) e o nome em português (`Fogo`); as análises exibem o português.
- **Nome exibido.** `dim_pokemon.nome` é o nome do CSV (`Mega Charizard X`), mais legível; o nome da PokéAPI fica em `nome_pokeapi`.
- **Schema `controle`.** Registro das execuções separado dos schemas analíticos, para que nenhuma consulta de análise o encontre por engano.
- **Transação única por etapa.** Uma carga interrompida nunca deixa o silver ou o gold pela metade.
- **`gerar_relatorio.py`.** Não faz parte do pipeline. Lê `sql/consultas.sql`, executa as instruções e substitui os marcadores de `RELATORIO.modelo.md`, gerando o `RELATORIO.md` com as tabelas e um parágrafo de destaques numéricos por análise, para que o relatório corresponda sempre ao estado do banco.
- **Contêineres.** O grupo usou `docker-compose.yml`; a VM da disciplina funciona da mesma forma se as variáveis de ambiente apontarem para ela.

## 12. Bibliotecas (R11)

`requirements.txt` lista exatamente o que o pipeline importa: `requests` (cliente HTTP), `pymongo` (MongoDB) e `psycopg[binary]` (PostgreSQL). O resto é biblioteca padrão: `csv`, `json`, `io`, `pathlib`, `re`, `unicodedata`, `itertools`, `decimal`, `datetime`, `time`, `os`, `sys`. Não há pandas, polars, numpy, pyarrow nem outra biblioteca tabular. A conciliação é feita com dicionários, a agregação no PostgreSQL.

## 13. Perguntas não previstas — exemplos sobre o silver

O modelo responde a perguntas fora das oito análises sem alterar o esquema. Alguns exemplos:

Quem ataca primeiro vence mais?

```sql
SELECT atacou_primeiro, COUNT(*) AS participacoes, ROUND(AVG(venceu), 4) AS taxa_vitorias
FROM silver.fato_confronto
GROUP BY atacou_primeiro;
```

Taxa de vitórias por habitat, distinguindo "não se aplica" de "não informado":

```sql
SELECT p.habitat, COUNT(*) AS participacoes, ROUND(AVG(f.venceu), 4) AS taxa_vitorias
FROM silver.fato_confronto f
JOIN silver.dim_pokemon p ON p.sk_pokemon = f.sk_pokemon
GROUP BY p.habitat
ORDER BY taxa_vitorias DESC;
```

Lendários contra não lendários, pelo papel de oponente:

```sql
SELECT eu.categoria_raridade AS participante, op.categoria_raridade AS oponente,
       COUNT(*) AS participacoes, ROUND(AVG(f.venceu), 4) AS taxa_vitorias
FROM silver.fato_confronto f
JOIN silver.dim_pokemon eu ON eu.sk_pokemon = f.sk_pokemon
JOIN silver.dim_pokemon op ON op.sk_pokemon = f.sk_oponente
GROUP BY eu.categoria_raridade, op.categoria_raridade
ORDER BY participante, oponente;
```

Taxa de vitórias entre gerações:

```sql
SELECT g.nome_geracao AS geracao, go.nome_geracao AS geracao_oponente, ROUND(AVG(f.venceu), 4) AS taxa_vitorias
FROM silver.fato_confronto f
JOIN silver.dim_geracao g  ON g.sk_geracao  = f.sk_geracao
JOIN silver.dim_geracao go ON go.sk_geracao = f.sk_geracao_oponente
GROUP BY g.numero_geracao, g.nome_geracao, go.numero_geracao, go.nome_geracao
ORDER BY g.numero_geracao, go.numero_geracao;
```
