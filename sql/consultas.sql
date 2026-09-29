SELECT COALESCE(tipo_primario, 'Total') AS tipo_primario,
       COUNT(*) FILTER (WHERE numero_geracao = 1) AS "Geração I",
       COUNT(*) FILTER (WHERE numero_geracao = 2) AS "Geração II",
       COUNT(*) FILTER (WHERE numero_geracao = 3) AS "Geração III",
       COUNT(*) FILTER (WHERE numero_geracao = 4) AS "Geração IV",
       COUNT(*) FILTER (WHERE numero_geracao = 5) AS "Geração V",
       COUNT(*) FILTER (WHERE numero_geracao = 6) AS "Geração VI",
       COUNT(*) AS total
FROM silver.dim_pokemon
GROUP BY ROLLUP (tipo_primario)
ORDER BY GROUPING(tipo_primario), tipo_primario;

SELECT tipo_primario,
       COUNT(*) AS pokemon,
       ROUND(AVG(hp), 1) AS hp,
       ROUND(AVG(ataque), 1) AS ataque,
       ROUND(AVG(defesa), 1) AS defesa,
       ROUND(AVG(ataque_especial), 1) AS ataque_especial,
       ROUND(AVG(defesa_especial), 1) AS defesa_especial,
       ROUND(AVG(velocidade), 1) AS velocidade,
       ROUND(AVG(hp + defesa + defesa_especial), 1) AS resistencia,
       ROUND(AVG(total_status), 1) AS total_status
FROM silver.dim_pokemon
GROUP BY tipo_primario
ORDER BY tipo_primario;

WITH medias AS (
    SELECT tipo_primario,
           AVG(hp) AS hp,
           AVG(ataque) AS ataque,
           AVG(defesa) AS defesa,
           AVG(ataque_especial) AS ataque_especial,
           AVG(defesa_especial) AS defesa_especial,
           AVG(velocidade) AS velocidade,
           AVG(hp + defesa + defesa_especial) AS resistencia
    FROM silver.dim_pokemon
    GROUP BY tipo_primario
),
geral AS (
    SELECT AVG(hp) AS hp,
           AVG(ataque) AS ataque,
           AVG(defesa) AS defesa,
           AVG(ataque_especial) AS ataque_especial,
           AVG(defesa_especial) AS defesa_especial,
           AVG(velocidade) AS velocidade
    FROM silver.dim_pokemon
)
SELECT m.tipo_primario,
       ROUND(m.velocidade, 1) AS velocidade_media,
       RANK() OVER (ORDER BY m.velocidade DESC) AS posicao_velocidade,
       ROUND(m.resistencia, 1) AS resistencia_media,
       RANK() OVER (ORDER BY m.resistencia DESC) AS posicao_resistencia,
       (m.hp = MAX(m.hp) OVER ())::INTEGER
         + (m.ataque = MAX(m.ataque) OVER ())::INTEGER
         + (m.defesa = MAX(m.defesa) OVER ())::INTEGER
         + (m.ataque_especial = MAX(m.ataque_especial) OVER ())::INTEGER
         + (m.defesa_especial = MAX(m.defesa_especial) OVER ())::INTEGER
         + (m.velocidade = MAX(m.velocidade) OVER ())::INTEGER AS atributos_em_que_lidera,
       (m.hp > g.hp
         AND m.ataque > g.ataque
         AND m.defesa > g.defesa
         AND m.ataque_especial > g.ataque_especial
         AND m.defesa_especial > g.defesa_especial
         AND m.velocidade > g.velocidade) AS acima_da_media_em_todos
FROM medias AS m
CROSS JOIN geral AS g
ORDER BY atributos_em_que_lidera DESC, posicao_velocidade;

SELECT nome_pokemon, tipo_primario, geracao, categoria_forma, combates, vitorias, taxa_vitorias
FROM gold.ranking_pokemon
WHERE combates >= 100
ORDER BY taxa_vitorias DESC, combates DESC
LIMIT 10;

SELECT nome_pokemon, tipo_primario, geracao, categoria_forma, combates, vitorias, taxa_vitorias
FROM gold.ranking_pokemon
WHERE combates >= 100
ORDER BY taxa_vitorias ASC, combates DESC
LIMIT 10;

SELECT tipo_primario, pokemon_distintos, participacoes, vitorias, taxa_vitorias, diferenca_para_equilibrio
FROM gold.taxa_vitorias_por_tipo
ORDER BY taxa_vitorias DESC;

SELECT faixa, limite_inferior, limite_superior, participacoes, vitorias, taxa_vitorias
FROM gold.taxa_vitorias_por_faixa_velocidade
ORDER BY ordem_faixa;

SELECT rotulo AS efetividade, classificacao, participacoes, vitorias, taxa_vitorias
FROM gold.taxa_vitorias_por_multiplicador
ORDER BY multiplicador;

SELECT tipo_atacante, tipo_defensor, multiplicador, participacoes, taxa_vitorias,
       resultado_esperado, resultado_observado, divergente
FROM gold.matriz_confronto
ORDER BY tipo_atacante, tipo_defensor;

SELECT tipo_atacante, tipo_defensor, multiplicador, participacoes, taxa_vitorias,
       resultado_esperado, resultado_observado
FROM gold.matriz_confronto
WHERE divergente
ORDER BY ABS(taxa_vitorias - 0.5) DESC, tipo_atacante, tipo_defensor;

SELECT especie, forma_padrao, forma_alternativa, categoria_forma,
       combates_padrao, taxa_padrao, combates_forma, taxa_forma, ganho_taxa,
       diferenca_total_status, diferenca_velocidade
FROM gold.ganho_forma_alternativa
ORDER BY ganho_taxa DESC NULLS LAST, forma_alternativa;
