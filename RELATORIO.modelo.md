# Relatório de resultados

Resultados obtidos pela execução de `sql/consultas.sql` sobre o banco carregado pelo pipeline. Tabelas geradas por `gerar_relatorio.py` em {{gerado_em}}.

Convenções de leitura:

- A fato está no grão de participação (duas linhas por combate). A taxa de vitórias média de todo o conjunto é exatamente 0,5; toda taxa deve ser lida em relação a esse valor.
- "Participações" conta linhas da fato. Em agrupamentos por tipo ou faixa, um combate entre dois Pokémon do mesmo grupo conta duas vezes, uma vitória e uma derrota.
- As batalhas foram produzidas por um simulador. Todo padrão abaixo descreve o comportamento desse programa, e não partidas reais.

---

## Análise 1 — Pokémon por tipo primário e geração

**Pergunta.** Quantos registros há por tipo primário em cada geração? A contagem é coerente com o esperado?

{{consulta_01}}

**Destaques.** {{destaque_1}}

**Interpretação.** A contagem é feita sobre a `dim_pokemon`, e não sobre espécies: formas alternativas contam como registros próprios, e por isso o total é 800, e não 721. A linha de total deve somar 800 e bater com o arquivo de origem; qualquer diferença indicaria registro descartado na carga, o que o `carregar.py` impede. A distribuição por geração acompanha o tamanho de cada Pokédex regional (a geração V é a maior e a geração VI a menor), acrescida das formas alternativas, que se concentram nas gerações I e III por causa das Mega Evoluções e das formas Primal. Água e Normal lideram com folga, padrão conhecido da franquia. Tipos como Fada e Aço aparecem pouco como tipo primário nas primeiras gerações porque Fada só existe a partir da geração VI (e foi atribuído retroativamente, muitas vezes como segundo tipo) e Aço a partir da II. Como a coluna de tipo vem do CSV, a matriz reflete os tipos usados pelo simulador. O registro 63 (sem nome) aparece contado como Lutador da geração I: ele é um Pokémon do cadastro, apenas sem identidade.

---

## Análise 2 — Média dos atributos por tipo primário

**Pergunta.** Qual tipo é o mais rápido em média, qual o mais resistente, e algum tipo supera os demais em todos os atributos?

{{consulta_02}}

{{consulta_03}}

**Destaques.** {{destaque_2}}

**Interpretação.** Resistência foi definida como HP + Defesa + Defesa Especial. A segunda tabela mostra, para cada tipo, a posição em velocidade e em resistência, em quantos dos seis atributos ele tem a maior média e se está acima da média geral nos seis. Os tipos se especializam: o perfil mais rápido costuma ser o de tipos com muitos Pokémon ágeis e frágeis (Voador, Elétrico), enquanto a resistência se concentra em tipos pesados (Aço, Pedra, Dragão). Nenhum tipo lidera os seis atributos, o que reflete o desenho do jogo: velocidade e defesa costumam ser trocadas uma pela outra. A coluna de média geral é mais informativa do que a liderança: um tipo acima da média nos seis atributos (Dragão é o candidato natural, pela concentração de lendários e pseudolendários) não é o melhor em nada, mas é forte em tudo. Esse ponto é relevante para as análises de batalha: um tipo com médias altas pode vencer mais por causa dos status, e não por causa do tipo, e as análises 4 e 7 devem ser lidas com isso em mente.

---

## Análise 3 — Taxa de vitórias por Pokémon

**Pergunta.** Quais Pokémon têm as maiores e as menores taxas de vitórias, considerando apenas quem disputou pelo menos 100 combates?

Dez maiores:

{{consulta_04}}

Dez menores:

{{consulta_05}}

**Destaques.** {{destaque_3}}

**Interpretação.** O corte de 100 combates limita o erro-padrão de cada taxa a 5 pontos percentuais (justificativa no README, seção 7.1); a quantidade de combates está ao lado de cada taxa. As duas pontas do ranking devem ser comparadas com a coluna de velocidade da `dim_pokemon`: os primeiros colocados tendem a ser Pokémon muito rápidos (formas Mega com velocidade aumentada, lendários velozes e Pokémon frágeis de alta velocidade), e os últimos, Pokémon lentos e de baixo status total, inclusive formas bebê e Pokémon defensivos cujo valor no jogo real depende de golpes de suporte que o simulador não reproduz. Se isso se confirmar, o ranking é, antes de tudo, um ranking de velocidade — hipótese testada diretamente pela análise 5. Taxas próximas de 100% com mais de 100 combates não são ruído: indicam que, para o simulador, o Pokémon praticamente não perde.

---

## Análise 4 — Taxa de vitórias por tipo primário

**Pergunta.** Algum tipo primário domina as batalhas?

{{consulta_06}}

**Destaques.** {{destaque_4}}

**Interpretação.** A coluna `diferenca_para_equilibrio` mostra quanto cada tipo se afasta de 0,5. Um tipo dominante seria um que se destaca dos demais com folga, e não apenas o primeiro de uma sequência contínua; a distância entre o primeiro e o segundo colocados, nos destaques, é o que responde a isso. A leitura precisa considerar a análise 2: os tipos do topo coincidem com os de maior velocidade média? Se sim, a vantagem é de velocidade, e não de tipo. Tipos com poucos Pokémon distintos (Voador como tipo primário é o caso mais extremo) têm taxa mais sensível a poucos indivíduos, e a coluna `pokemon_distintos` deve acompanhar a leitura. A separação entre efeito de tipo e efeito de velocidade é o objeto das análises 5 e 6.

---

## Análise 5 — Diferença de velocidade e vitória

**Pergunta.** Ser mais rápido que o oponente aumenta a chance de vencer? Em que medida?

{{consulta_07}}

**Destaques.** {{destaque_5}}

**Interpretação.** As faixas são simétricas, e as taxas de faixas espelhadas somam 1 por construção do grão; a leitura se faz pela metade "mais rápido". A pergunta decisiva é a forma da curva. Um degrau abrupto entre "mais lento por 1 a 9" e "mais rápido por 1 a 9", com as faixas seguintes já próximas do teto, indica que o simulador usa a velocidade para definir quem age primeiro e que agir primeiro quase decide o combate: um ponto de velocidade vale tanto quanto sessenta. Um crescimento gradual ao longo das faixas indicaria que a velocidade entra no cálculo de dano de forma contínua. A faixa "mesma velocidade" mostra o critério de desempate do simulador: se ali a taxa é 0,5 exatamente, o empate é neutro. Qualquer que seja a forma, a diferença entre as faixas extremas mede o peso da velocidade no resultado e serve de régua para a análise 6: um efeito de tipo relevante precisaria ter ordem de grandeza comparável.

---

## Análise 6 — Vantagem de tipo e vitória

**Pergunta.** Pokémon com vantagem de tipo sobre o oponente vencem mais?

Critério adotado: tipo primário do participante contra os dois tipos do oponente (seis multiplicadores possíveis), conforme a decisão 3 do README.

{{consulta_08}}

**Destaques.** {{destaque_6}}

**Interpretação.** Se o simulador aplicasse a tabela de tipos, a taxa deveria crescer de forma monotônica de x0 a x4, com x2 e x4 claramente acima de 0,5 e x0,5 e x0,25 abaixo. A comparação a fazer é com a análise 5: quanto a taxa varia entre x0,5 e x2, contra quanto varia entre as faixas de velocidade. Um efeito pequeno, não monotônico ou dentro de poucos pontos de 0,5 é uma resposta válida e significa que o programa que gerou as batalhas não usou a efetividade de tipos, ou a usou com peso pequeno frente à velocidade. A linha x0 merece leitura à parte: em jogo real um ataque sem efeito é decisivo, e uma taxa próxima de 0,5 nesse multiplicador é o indício mais forte de que o simulador ignora a tabela. Há ainda um fator de confusão: multiplicadores altos ocorrem com mais frequência para alguns tipos atacantes, cujos Pokémon podem ser mais rápidos em média, e o efeito observado pode misturar tipo e velocidade.

---

## Análise 7 — Matriz de confronto entre tipos

**Pergunta.** Em cada par de tipos primários, a taxa de vitórias observada concorda com o multiplicador de efetividade?

Matriz completa (324 células):

{{consulta_09}}

Células divergentes (vantagem esperada com taxa abaixo de 0,5, ou desvantagem esperada com taxa acima de 0,5), da maior para a menor divergência:

{{consulta_10}}

**Destaques.** {{destaque_7}}

**Interpretação.** A orientação é pelo vencedor, e as células (A, B) e (B, A) somam 1; as células da diagonal valem 0,5 por construção. Se a análise 6 mostrar efeito de tipo fraco, espera-se uma quantidade grande de divergências, e a lista de divergentes deve ser lida como o mapa dos casos em que outro fator se impôs à efetividade. Um exemplo típico são pares em que o tipo "em desvantagem" reúne Pokémon muito mais rápidos que o tipo "em vantagem": Voador e Elétrico contra Pedra, ou Pedra contra Inseto e Voador. Nesses casos, a divergência é mais uma evidência do peso da velocidade (análise 5). Células com poucas participações devem ser descartadas da leitura, e a coluna `participacoes` está disponível para isso. Onde as divergências se concentram em poucos tipos atacantes, o fator é provavelmente o perfil de status do tipo (análise 2); onde se espalham, a tabela de efetividade simplesmente não explica o simulador.

---

## Análise 8 — Forma alternativa contra forma padrão (proposta pelo grupo)

**Pergunta de negócio.** A forma alternativa (Mega, Primal ou outra forma) vence mais do que a forma padrão da mesma espécie, e o ganho de taxa de vitórias acompanha o ganho de atributos?

**Por que importa.** A transformação é a principal mecânica de poder adicional introduzida na geração VI. Saber se ela sempre compensa, e se compensa na proporção do ganho de status, informa decisões de equilíbrio de jogo e de montagem de equipe.

{{consulta_11}}

**Destaques.** {{destaque_8}}

**Interpretação.** As formas Mega e Primal aumentam o total de status em 100 pontos e, em geral, a velocidade; espera-se ganho positivo na maior parte delas, e o tamanho do ganho deve acompanhar `diferenca_velocidade` mais do que `diferenca_total_status`, se a análise 5 confirmar o peso da velocidade. As exceções são a parte mais informativa da tabela: Megas que não ganham ou perdem velocidade (como Mega Slowbro e Mega Camerupt) devem ganhar pouco ou até perder, apesar dos 100 pontos a mais. Em "Outra forma" estão as trocas de atributos sem aumento de total (Aegislash Espada × Escudo, Darmanitan Zen, os tamanhos de Pumpkaboo e Gourgeist, as capas de Wormadam, as formas de Deoxys); ali o ganho pode ser negativo e deve ser explicado pela diferença de velocidade da troca. Se o ganho de taxa acompanhar de perto a diferença de velocidade e pouco a diferença de total, a conclusão é que, para o simulador, a transformação vale pelo que muda na velocidade, e não pelo aumento de poder em geral.
