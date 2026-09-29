INSERT INTO gold.ranking_pokemon (
    numero_csv, nome_pokemon, tipo_primario, tipo_secundario, geracao,
    categoria_raridade, categoria_forma, combates, vitorias, derrotas, taxa_vitorias
)
SELECT p.numero_csv,
       p.nome,
       p.tipo_primario,
       p.tipo_secundario,
       p.geracao,
       p.categoria_raridade,
       p.categoria_forma,
       COUNT(f.id_combate),
       COALESCE(SUM(f.venceu), 0),
       COUNT(f.id_combate) - COALESCE(SUM(f.venceu), 0),
       ROUND(AVG(f.venceu), 4)
FROM silver.dim_pokemon AS p
LEFT JOIN silver.fato_confronto AS f ON f.sk_pokemon = p.sk_pokemon
GROUP BY p.sk_pokemon;

INSERT INTO gold.taxa_vitorias_por_tipo (
    tipo_primario, pokemon_distintos, participacoes, vitorias, taxa_vitorias, diferenca_para_equilibrio
)
SELECT t.nome_tipo_pt,
       COUNT(DISTINCT f.sk_pokemon),
       COUNT(*),
       SUM(f.venceu),
       ROUND(AVG(f.venceu), 4),
       ROUND(AVG(f.venceu) - 0.5, 4)
FROM silver.fato_confronto AS f
JOIN silver.dim_tipo AS t ON t.sk_tipo = f.sk_tipo_primario
GROUP BY t.sk_tipo;

INSERT INTO gold.taxa_vitorias_por_faixa_velocidade (
    ordem_faixa, faixa, limite_inferior, limite_superior, participacoes, vitorias, taxa_vitorias
)
SELECT fx.ordem,
       fx.rotulo,
       fx.minimo,
       fx.maximo,
       COUNT(f.id_combate),
       COALESCE(SUM(f.venceu), 0),
       ROUND(AVG(f.venceu), 4)
FROM (
    VALUES (1, 'Mais lento por 60 ou mais', NULL::INTEGER, -60),
           (2, 'Mais lento por 30 a 59',    -59,           -30),
           (3, 'Mais lento por 10 a 29',    -29,           -10),
           (4, 'Mais lento por 1 a 9',      -9,            -1),
           (5, 'Mesma velocidade',          0,             0),
           (6, 'Mais rápido por 1 a 9',     1,             9),
           (7, 'Mais rápido por 10 a 29',   10,            29),
           (8, 'Mais rápido por 30 a 59',   30,            59),
           (9, 'Mais rápido por 60 ou mais', 60,           NULL::INTEGER)
) AS fx (ordem, rotulo, minimo, maximo)
LEFT JOIN silver.fato_confronto AS f
       ON (fx.minimo IS NULL OR f.diferenca_velocidade >= fx.minimo)
      AND (fx.maximo IS NULL OR f.diferenca_velocidade <= fx.maximo)
GROUP BY fx.ordem, fx.rotulo, fx.minimo, fx.maximo;

INSERT INTO gold.taxa_vitorias_por_multiplicador (
    multiplicador, rotulo, classificacao, participacoes, vitorias, taxa_vitorias
)
SELECT m.multiplicador,
       'x' || REPLACE(RTRIM(RTRIM(m.multiplicador::TEXT, '0'), '.'), '.', ','),
       CASE
           WHEN m.multiplicador = 0 THEN 'Sem efeito'
           WHEN m.multiplicador < 1 THEN 'Pouco efetivo'
           WHEN m.multiplicador = 1 THEN 'Neutro'
           ELSE 'Super efetivo'
       END,
       COUNT(*),
       SUM(m.venceu),
       ROUND(AVG(m.venceu), 4)
FROM (
    SELECT f.venceu,
           (e1.multiplicador * COALESCE(e2.multiplicador, 1))::NUMERIC(4,2) AS multiplicador
    FROM silver.fato_confronto AS f
    JOIN silver.efetividade_tipo AS e1
      ON e1.sk_tipo_atacante = f.sk_tipo_primario
     AND e1.sk_tipo_defensor = f.sk_tipo_oponente_primario
    LEFT JOIN silver.efetividade_tipo AS e2
      ON e2.sk_tipo_atacante = f.sk_tipo_primario
     AND e2.sk_tipo_defensor = f.sk_tipo_oponente_secundario
) AS m
GROUP BY m.multiplicador;

INSERT INTO gold.matriz_confronto (
    tipo_atacante, tipo_defensor, multiplicador, resultado_esperado,
    participacoes, vitorias, taxa_vitorias, resultado_observado, divergente
)
SELECT ta.nome_tipo_pt,
       td.nome_tipo_pt,
       e.multiplicador,
       CASE
           WHEN e.multiplicador > 1 THEN 'Vantagem'
           WHEN e.multiplicador < 1 THEN 'Desvantagem'
           ELSE 'Neutro'
       END,
       COALESCE(a.participacoes, 0),
       COALESCE(a.vitorias, 0),
       a.taxa_vitorias,
       CASE
           WHEN a.taxa_vitorias IS NULL THEN 'Sem confrontos'
           WHEN a.taxa_vitorias > 0.5 THEN 'Vantagem'
           WHEN a.taxa_vitorias < 0.5 THEN 'Desvantagem'
           ELSE 'Equilíbrio'
       END,
       COALESCE(
           (e.multiplicador > 1 AND a.taxa_vitorias < 0.5)
           OR (e.multiplicador < 1 AND a.taxa_vitorias > 0.5),
           FALSE
       )
FROM silver.efetividade_tipo AS e
JOIN silver.dim_tipo AS ta ON ta.sk_tipo = e.sk_tipo_atacante
JOIN silver.dim_tipo AS td ON td.sk_tipo = e.sk_tipo_defensor
LEFT JOIN (
    SELECT sk_tipo_primario,
           sk_tipo_oponente_primario,
           COUNT(*) AS participacoes,
           SUM(venceu) AS vitorias,
           ROUND(AVG(venceu), 4) AS taxa_vitorias
    FROM silver.fato_confronto
    GROUP BY sk_tipo_primario, sk_tipo_oponente_primario
) AS a
  ON a.sk_tipo_primario = e.sk_tipo_atacante
 AND a.sk_tipo_oponente_primario = e.sk_tipo_defensor;

WITH desempenho AS (
    SELECT p.sk_pokemon,
           p.numero_csv,
           p.numero_pokedex,
           p.especie,
           p.nome,
           p.categoria_forma,
           p.total_status,
           p.velocidade,
           COUNT(f.id_combate) AS combates,
           AVG(f.venceu) AS taxa
    FROM silver.dim_pokemon AS p
    LEFT JOIN silver.fato_confronto AS f ON f.sk_pokemon = p.sk_pokemon
    WHERE p.numero_pokedex IS NOT NULL
    GROUP BY p.sk_pokemon
)
INSERT INTO gold.ganho_forma_alternativa (
    numero_csv_forma, especie, forma_padrao, forma_alternativa, categoria_forma,
    combates_padrao, taxa_padrao, combates_forma, taxa_forma, ganho_taxa,
    diferenca_total_status, diferenca_velocidade
)
SELECT alt.numero_csv,
       alt.especie,
       pad.nome,
       alt.nome,
       alt.categoria_forma,
       pad.combates,
       ROUND(pad.taxa, 4),
       alt.combates,
       ROUND(alt.taxa, 4),
       ROUND(alt.taxa - pad.taxa, 4),
       alt.total_status - pad.total_status,
       alt.velocidade - pad.velocidade
FROM desempenho AS alt
JOIN desempenho AS pad
  ON pad.numero_pokedex = alt.numero_pokedex
 AND pad.categoria_forma = 'Padrão'
WHERE alt.categoria_forma IN ('Mega', 'Primal', 'Outra forma');
