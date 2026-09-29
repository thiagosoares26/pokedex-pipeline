import os
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import psycopg

RAIZ = Path(__file__).resolve().parent
PG_DSN = os.environ.get("PG_DSN", "postgresql://pokedex:pokedex@localhost:5432/pokedex")
ARQUIVO_CONSULTAS = RAIZ / "sql" / "consultas.sql"
ARQUIVO_MODELO = RAIZ / "RELATORIO.modelo.md"
ARQUIVO_RELATORIO = RAIZ / "RELATORIO.md"


def instrucoes(texto):
    return [trecho.strip() for trecho in texto.split(";") if trecho.strip()]


def formatar(valor):
    if valor is None:
        return "—"
    if isinstance(valor, bool):
        return "sim" if valor else "não"
    if isinstance(valor, Decimal):
        return format(valor, "f").replace(".", ",")
    return str(valor).replace("|", "\\|")


def tabela_markdown(colunas, linhas):
    cabecalho = "| " + " | ".join(colunas) + " |"
    separador = "|" + "|".join("---" for _ in colunas) + "|"
    corpo = ["| " + " | ".join(formatar(v) for v in linha) + " |" for linha in linhas]
    return "\n".join([cabecalho, separador, *corpo])


def percentual(valor):
    if valor is None:
        return "—"
    return f"{Decimal(valor) * 100:.1f}%".replace(".", ",")


def destaques(resultados):
    def registros(indice):
        colunas, linhas = resultados[indice]
        return [dict(zip(colunas, linha)) for linha in linhas]

    texto = {}

    matriz = registros(0)
    total = next(r for r in matriz if r["tipo_primario"] == "Total")
    tipos = [r for r in matriz if r["tipo_primario"] != "Total"]
    maior_tipo = max(tipos, key=lambda r: r["total"])
    geracoes = {chave: total[chave] for chave in total if chave.startswith("Geração")}
    maior_geracao = max(geracoes, key=geracoes.get)
    texto[1] = (
        f"Total de {total['total']} registros na dim_pokemon. Tipo primário mais frequente: "
        f"{maior_tipo['tipo_primario']} ({maior_tipo['total']}). Geração com mais registros: "
        f"{maior_geracao} ({geracoes[maior_geracao]})."
    )

    posicoes = registros(2)
    mais_rapido = min(posicoes, key=lambda r: r["posicao_velocidade"])
    mais_resistente = min(posicoes, key=lambda r: r["posicao_resistencia"])
    lider = posicoes[0]
    dominante = [r["tipo_primario"] for r in posicoes if r["atributos_em_que_lidera"] == 6]
    acima = [r["tipo_primario"] for r in posicoes if r["acima_da_media_em_todos"]]
    texto[2] = (
        f"Maior velocidade média: {mais_rapido['tipo_primario']} ({formatar(mais_rapido['velocidade_media'])}). "
        f"Maior resistência média (HP + Defesa + Defesa Especial): {mais_resistente['tipo_primario']} "
        f"({formatar(mais_resistente['resistencia_media'])}). "
        f"Tipo que lidera mais atributos: {lider['tipo_primario']} ({lider['atributos_em_que_lidera']} de 6). "
        f"Tipo que lidera os seis atributos: {', '.join(dominante) if dominante else 'nenhum'}. "
        f"Tipos acima da média geral nos seis atributos: {', '.join(acima) if acima else 'nenhum'}."
    )

    maiores, menores = registros(3), registros(4)
    if maiores and menores:
        texto[3] = (
            f"Maior taxa com pelo menos 100 combates: {maiores[0]['nome_pokemon']} "
            f"({percentual(maiores[0]['taxa_vitorias'])} em {maiores[0]['combates']} combates). "
            f"Menor: {menores[0]['nome_pokemon']} "
            f"({percentual(menores[0]['taxa_vitorias'])} em {menores[0]['combates']} combates)."
        )
    else:
        texto[3] = "Nenhum Pokémon atingiu o corte de 100 combates."

    por_tipo = registros(5)
    texto[4] = (
        f"Maior taxa: {por_tipo[0]['tipo_primario']} ({percentual(por_tipo[0]['taxa_vitorias'])}). "
        f"Menor taxa: {por_tipo[-1]['tipo_primario']} ({percentual(por_tipo[-1]['taxa_vitorias'])}). "
        f"Segundo colocado: {por_tipo[1]['tipo_primario']} ({percentual(por_tipo[1]['taxa_vitorias'])})."
    )

    faixas = registros(6)
    iguais = next(r for r in faixas if r["limite_inferior"] == 0)
    texto[5] = (
        f"Faixa mais lenta ({faixas[0]['faixa']}): {percentual(faixas[0]['taxa_vitorias'])}. "
        f"Mesma velocidade: {percentual(iguais['taxa_vitorias'])} em {iguais['participacoes']} participações. "
        f"Faixa mais rápida ({faixas[-1]['faixa']}): {percentual(faixas[-1]['taxa_vitorias'])}. "
        f"Mais rápido por 1 a 9 pontos: "
        f"{percentual(next(r for r in faixas if r['limite_inferior'] == 1)['taxa_vitorias'])}."
    )

    multiplicadores = registros(7)
    texto[6] = "Taxa de vitórias por efetividade: " + "; ".join(
        f"{r['efetividade']} = {percentual(r['taxa_vitorias'])} ({r['participacoes']} participações)"
        for r in multiplicadores
    ) + "."

    celulas = registros(8)
    com_dados = [r for r in celulas if r["participacoes"] > 0]
    com_efeito = [r for r in com_dados if r["multiplicador"] != 1]
    divergentes = registros(9)
    principais = ", ".join(
        f"{r['tipo_atacante']} × {r['tipo_defensor']} (x{formatar(r['multiplicador'])}, {percentual(r['taxa_vitorias'])})"
        for r in divergentes[:3]
    )
    texto[7] = (
        f"Células com confrontos: {len(com_dados)} de {len(celulas)}. Células com multiplicador diferente de 1 "
        f"e confrontos: {len(com_efeito)}. Células divergentes: {len(divergentes)}. "
        f"Maiores divergências: {principais or 'nenhuma'}."
    )

    formas = registros(10)
    com_taxa = [r for r in formas if r["ganho_taxa"] is not None]
    positivos = [r for r in com_taxa if r["ganho_taxa"] > 0]
    if com_taxa:
        texto[8] = (
            f"Formas alternativas comparadas: {len(com_taxa)}. Com ganho de taxa sobre a forma padrão: "
            f"{len(positivos)}. Maior ganho: {com_taxa[0]['forma_alternativa']} "
            f"({formatar(com_taxa[0]['ganho_taxa'])}). Maior perda: {com_taxa[-1]['forma_alternativa']} "
            f"({formatar(com_taxa[-1]['ganho_taxa'])})."
        )
    else:
        texto[8] = "Nenhuma forma alternativa com combates registrados."
    return texto


def main():
    consultas = instrucoes(ARQUIVO_CONSULTAS.read_text(encoding="utf-8"))
    resultados = []
    with psycopg.connect(PG_DSN) as conexao:
        with conexao.cursor() as cursor:
            for consulta in consultas:
                cursor.execute(consulta)
                colunas = [coluna.name for coluna in cursor.description]
                resultados.append((colunas, cursor.fetchall()))

    relatorio = ARQUIVO_MODELO.read_text(encoding="utf-8")
    for indice, (colunas, linhas) in enumerate(resultados, start=1):
        relatorio = relatorio.replace(f"{{{{consulta_{indice:02d}}}}}", tabela_markdown(colunas, linhas))
    for indice, frase in destaques(resultados).items():
        relatorio = relatorio.replace(f"{{{{destaque_{indice}}}}}", frase)
    momento = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    relatorio = relatorio.replace("{{gerado_em}}", momento)

    ARQUIVO_RELATORIO.write_text(relatorio, encoding="utf-8")
    print(f"{ARQUIVO_RELATORIO.name} gerado com {len(resultados)} consultas.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
