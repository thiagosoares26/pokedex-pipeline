import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import psycopg

RAIZ = Path(__file__).resolve().parent
SQL = RAIZ / "sql"
PG_DSN = os.environ.get("PG_DSN", "postgresql://pokedex:pokedex@localhost:5432/pokedex")

TABELAS_GOLD = [
    "gold.ranking_pokemon",
    "gold.taxa_vitorias_por_tipo",
    "gold.taxa_vitorias_por_faixa_velocidade",
    "gold.taxa_vitorias_por_multiplicador",
    "gold.matriz_confronto",
    "gold.ganho_forma_alternativa",
]


def ler_sql(nome):
    return (SQL / nome).read_text(encoding="utf-8")


def valor(cursor, consulta):
    return cursor.execute(consulta).fetchone()[0]


def verificar(cursor):
    participacoes = valor(cursor, "SELECT COUNT(*) FROM silver.fato_confronto")
    pokemon = valor(cursor, "SELECT COUNT(*) FROM silver.dim_pokemon")
    pares_tipo = valor(cursor, "SELECT COUNT(*) FROM silver.efetividade_tipo")
    checagens = [
        ("ranking cobre toda a dim_pokemon",
         valor(cursor, "SELECT COUNT(*) FROM gold.ranking_pokemon"), pokemon),
        ("ranking soma todas as participações",
         valor(cursor, "SELECT COALESCE(SUM(combates), 0) FROM gold.ranking_pokemon"), participacoes),
        ("tipos somam todas as participações",
         valor(cursor, "SELECT COALESCE(SUM(participacoes), 0) FROM gold.taxa_vitorias_por_tipo"), participacoes),
        ("faixas de velocidade somam todas as participações",
         valor(cursor, "SELECT COALESCE(SUM(participacoes), 0) FROM gold.taxa_vitorias_por_faixa_velocidade"),
         participacoes),
        ("multiplicadores somam todas as participações",
         valor(cursor, "SELECT COALESCE(SUM(participacoes), 0) FROM gold.taxa_vitorias_por_multiplicador"),
         participacoes),
        ("matriz possui todos os pares de tipo",
         valor(cursor, "SELECT COUNT(*) FROM gold.matriz_confronto"), pares_tipo),
        ("matriz soma todas as participações",
         valor(cursor, "SELECT COALESCE(SUM(participacoes), 0) FROM gold.matriz_confronto"), participacoes),
    ]
    falhas = [f"{nome}: obtido {obtido}, esperado {esperado}" for nome, obtido, esperado in checagens if obtido != esperado]
    if falhas:
        raise RuntimeError("Verificação do gold falhou:\n  " + "\n  ".join(falhas))
    return len(checagens)


def main():
    inicio = time.time()
    agora = datetime.now(timezone.utc)
    with psycopg.connect(PG_DSN) as conexao:
        with conexao.cursor() as cursor:
            existe = valor(cursor, "SELECT to_regclass('silver.fato_confronto') IS NOT NULL")
            if not existe or valor(cursor, "SELECT COUNT(*) FROM silver.fato_confronto") == 0:
                raise SystemExit("Camada silver vazia. Execute carregar.py antes de publicar.py.")

            cursor.execute(ler_sql("controle.sql"))
            cursor.execute(ler_sql("gold.sql"))
            cursor.execute(f"TRUNCATE {', '.join(TABELAS_GOLD)}")
            cursor.execute(ler_sql("gold_carga.sql"))

            quantidade_checagens = verificar(cursor)
            contagens = {tabela: valor(cursor, f"SELECT COUNT(*) FROM {tabela}") for tabela in TABELAS_GOLD}
            cursor.executemany(
                "INSERT INTO controle.execucao (etapa, tabela, linhas, executado_em) VALUES ('publicar', %s, %s, %s)",
                [(tabela, quantidade, agora) for tabela, quantidade in contagens.items()],
            )
        conexao.commit()

    print(f"Publicação concluída em {agora.isoformat(timespec='seconds')}")
    print(f"Verificações de consistência aprovadas: {quantidade_checagens}")
    for tabela, quantidade in contagens.items():
        print(f"  {tabela:<40} {quantidade:>6} linhas")
    print(f"Tempo total: {time.time() - inicio:.1f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
