CREATE SCHEMA IF NOT EXISTS controle;

CREATE TABLE IF NOT EXISTS controle.execucao (
    id_execucao   BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    etapa         TEXT        NOT NULL,
    tabela        TEXT        NOT NULL,
    linhas        BIGINT      NOT NULL,
    executado_em  TIMESTAMPTZ NOT NULL
);
