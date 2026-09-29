CREATE SCHEMA IF NOT EXISTS gold;

CREATE TABLE IF NOT EXISTS gold.ranking_pokemon (
    numero_csv          INTEGER      PRIMARY KEY,
    nome_pokemon        TEXT         NOT NULL,
    tipo_primario       TEXT         NOT NULL,
    tipo_secundario     TEXT         NOT NULL,
    geracao             TEXT         NOT NULL,
    categoria_raridade  TEXT         NOT NULL,
    categoria_forma     TEXT         NOT NULL,
    combates            INTEGER      NOT NULL,
    vitorias            INTEGER      NOT NULL,
    derrotas            INTEGER      NOT NULL,
    taxa_vitorias       NUMERIC(5,4)
);

CREATE TABLE IF NOT EXISTS gold.taxa_vitorias_por_tipo (
    tipo_primario              TEXT         PRIMARY KEY,
    pokemon_distintos          INTEGER      NOT NULL,
    participacoes              INTEGER      NOT NULL,
    vitorias                   INTEGER      NOT NULL,
    taxa_vitorias              NUMERIC(5,4) NOT NULL,
    diferenca_para_equilibrio  NUMERIC(5,4) NOT NULL
);

CREATE TABLE IF NOT EXISTS gold.taxa_vitorias_por_faixa_velocidade (
    ordem_faixa      SMALLINT     PRIMARY KEY,
    faixa            TEXT         NOT NULL,
    limite_inferior  INTEGER,
    limite_superior  INTEGER,
    participacoes    INTEGER      NOT NULL,
    vitorias         INTEGER      NOT NULL,
    taxa_vitorias    NUMERIC(5,4)
);

CREATE TABLE IF NOT EXISTS gold.taxa_vitorias_por_multiplicador (
    multiplicador  NUMERIC(4,2) PRIMARY KEY,
    rotulo         TEXT         NOT NULL,
    classificacao  TEXT         NOT NULL,
    participacoes  INTEGER      NOT NULL,
    vitorias       INTEGER      NOT NULL,
    taxa_vitorias  NUMERIC(5,4) NOT NULL
);

CREATE TABLE IF NOT EXISTS gold.matriz_confronto (
    tipo_atacante        TEXT         NOT NULL,
    tipo_defensor        TEXT         NOT NULL,
    multiplicador        NUMERIC(3,2) NOT NULL,
    resultado_esperado   TEXT         NOT NULL,
    participacoes        INTEGER      NOT NULL,
    vitorias             INTEGER      NOT NULL,
    taxa_vitorias        NUMERIC(5,4),
    resultado_observado  TEXT         NOT NULL,
    divergente           BOOLEAN      NOT NULL,
    PRIMARY KEY (tipo_atacante, tipo_defensor)
);

CREATE TABLE IF NOT EXISTS gold.ganho_forma_alternativa (
    numero_csv_forma        INTEGER      PRIMARY KEY,
    especie                 TEXT         NOT NULL,
    forma_padrao            TEXT         NOT NULL,
    forma_alternativa       TEXT         NOT NULL,
    categoria_forma         TEXT         NOT NULL,
    combates_padrao         INTEGER      NOT NULL,
    taxa_padrao             NUMERIC(5,4),
    combates_forma          INTEGER      NOT NULL,
    taxa_forma              NUMERIC(5,4),
    ganho_taxa              NUMERIC(5,4),
    diferenca_total_status  INTEGER      NOT NULL,
    diferenca_velocidade    INTEGER      NOT NULL
);
