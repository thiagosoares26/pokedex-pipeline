import csv
import itertools
import os
import re
import sys
import time
import unicodedata
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import psycopg
from pymongo import MongoClient

RAIZ = Path(__file__).resolve().parent
SQL = RAIZ / "sql"
MONGO_URI = os.environ.get("MONGO_URI", "mongodb://localhost:27017")
MONGO_DB = os.environ.get("MONGO_DB", "pokedex_bronze")
PG_DSN = os.environ.get("PG_DSN", "postgresql://pokedex:pokedex@localhost:5432/pokedex")
ARQUIVO_CONCILIACAO = RAIZ / "conciliacao.csv"
ARQUIVO_RESUMO = RAIZ / "conciliacao_resumo.md"

NAO_INFORMADO = "Não informado"
NAO_SE_APLICA = "Não se aplica"
SEM_SEGUNDO_TIPO = "Sem segundo tipo"
SK_SEM_SEGUNDO_TIPO = -2
ULTIMA_GERACAO_COM_HABITAT = 3
ID_ULTIMO_TIPO_REAL = 18

TIPOS_PT = {
    "normal": "Normal",
    "fighting": "Lutador",
    "flying": "Voador",
    "poison": "Venenoso",
    "ground": "Terrestre",
    "rock": "Pedra",
    "bug": "Inseto",
    "ghost": "Fantasma",
    "steel": "Aço",
    "fire": "Fogo",
    "water": "Água",
    "grass": "Planta",
    "electric": "Elétrico",
    "psychic": "Psíquico",
    "ice": "Gelo",
    "dragon": "Dragão",
    "dark": "Sombrio",
    "fairy": "Fada",
}

GERACOES = {
    1: ("Geração I", "Kanto"),
    2: ("Geração II", "Johto"),
    3: ("Geração III", "Hoenn"),
    4: ("Geração IV", "Sinnoh"),
    5: ("Geração V", "Unova"),
    6: ("Geração VI", "Kalos"),
}

ROMANOS = {"i": 1, "ii": 2, "iii": 3, "iv": 4, "v": 5, "vi": 6, "vii": 7, "viii": 8, "ix": 9}

STATUS_CSV = {
    "hp": "HP",
    "attack": "Attack",
    "defense": "Defense",
    "special-attack": "Sp. Atk",
    "special-defense": "Sp. Def",
    "speed": "Speed",
}

TERMOS_GENERICOS = {"forme", "form", "cloak", "size", "mode", "confined"}

SUBSTITUICOES = {"♀": " f", "♂": " m", "'": "", "’": "", ".": "", ":": "", "%": ""}

EXCECOES_MANUAIS = {
    "zygarde-half-forme": "zygarde-50",
    "zygarde-50-forme": "zygarde-50",
}

COLUNAS_DIM_POKEMON = [
    "numero_csv", "numero_pokedex", "id_pokeapi", "nome", "nome_pokeapi", "especie",
    "categoria_forma", "status_conciliacao", "tipo_primario", "tipo_secundario",
    "numero_geracao", "geracao", "regiao", "categoria_raridade", "lendario_csv",
    "habitat", "cor", "forma_corporal", "taxa_crescimento", "grupos_ovo",
    "taxa_captura", "felicidade_base", "experiencia_base", "altura_m", "peso_kg",
    "qtd_habilidades", "hp", "ataque", "defesa", "ataque_especial", "defesa_especial",
    "velocidade", "total_status", "eh_membro_especial",
]

COLUNAS_FATO = [
    "id_combate", "atacou_primeiro", "sk_pokemon", "sk_oponente",
    "sk_tipo_primario", "sk_tipo_secundario", "sk_tipo_oponente_primario",
    "sk_tipo_oponente_secundario", "sk_geracao", "sk_geracao_oponente",
    "venceu", "diferenca_velocidade", "diferenca_total_status",
]

TABELAS_SILVER = [
    "silver.dim_geracao",
    "silver.dim_tipo",
    "silver.dim_pokemon",
    "silver.efetividade_tipo",
    "silver.fato_confronto",
]


def ler_sql(nome):
    return (SQL / nome).read_text(encoding="utf-8")


def ler_bronze():
    cliente = MongoClient(MONGO_URI, serverSelectionTimeoutMS=10000)
    banco = cliente[MONGO_DB]
    dados = {nome: list(banco[nome].find()) for nome in ("tipos", "especies", "pokemon", "pokemon_csv", "combates")}
    cliente.close()
    vazias = [nome for nome, documentos in dados.items() if not documentos]
    if vazias:
        raise SystemExit(f"Camada bronze incompleta, coleções vazias: {', '.join(vazias)}. Execute extrair.py.")
    return dados


def nome_ou(valor, padrao=NAO_INFORMADO):
    if isinstance(valor, dict) and valor.get("name"):
        return valor["name"]
    return padrao


def numero_da_geracao(nome_geracao):
    return ROMANOS[nome_geracao.split("-", 1)[1]]


def montar_tipos(documentos):
    reais = sorted((d for d in documentos if 1 <= d["id"] <= ID_ULTIMO_TIPO_REAL), key=lambda d: d["id"])
    nomes = [d["name"] for d in reais]
    if len(reais) != ID_ULTIMO_TIPO_REAL or set(nomes) != set(TIPOS_PT):
        raise RuntimeError(f"Tipos inesperados na camada bronze: {nomes}")
    return reais


def montar_efetividade(tipos):
    nomes = [t["name"] for t in tipos]
    matriz = {(atacante, defensor): Decimal("1") for atacante in nomes for defensor in nomes}
    fatores_para = (("double_damage_to", Decimal("2")), ("half_damage_to", Decimal("0.5")), ("no_damage_to", Decimal("0")))
    fatores_de = (("double_damage_from", Decimal("2")), ("half_damage_from", Decimal("0.5")), ("no_damage_from", Decimal("0")))
    for tipo in tipos:
        relacoes = tipo["damage_relations"]
        for chave, fator in fatores_para:
            for alvo in relacoes[chave]:
                if alvo["name"] in TIPOS_PT:
                    matriz[(tipo["name"], alvo["name"])] = fator
    inconsistencias = []
    for tipo in tipos:
        relacoes = tipo["damage_relations"]
        for chave, fator in fatores_de:
            for origem in relacoes[chave]:
                par = (origem["name"], tipo["name"])
                if par in matriz and matriz[par] != fator:
                    inconsistencias.append(par)
    return matriz, inconsistencias


def indexar_api(especies, formas):
    especie_por_nome = {e["name"]: e for e in especies}
    forma_por_nome = {f["name"]: f for f in formas}
    padrao_por_especie = {}
    for especie in especies:
        for variedade in especie["varieties"]:
            if variedade["is_default"]:
                padrao_por_especie[especie["name"]] = variedade["pokemon"]["name"]
    return {
        "especie_por_nome": especie_por_nome,
        "forma_por_nome": forma_por_nome,
        "padrao_por_especie": padrao_por_especie,
    }


def normalizar(texto):
    for antigo, novo in SUBSTITUICOES.items():
        texto = texto.replace(antigo, novo)
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    texto = texto.lower().replace("-", " ")
    return "-".join(texto.split())


def fragmentar(texto):
    texto = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", texto)
    texto = re.sub(r"(?<=[A-Za-z])(?=\d)|(?<=\d)(?=[A-Za-z])", " ", texto)
    return [parte for parte in normalizar(texto).split("-") if parte]


def localizar_especie(partes, especies):
    for tamanho in range(len(partes), 0, -1):
        for inicio in range(len(partes) - tamanho + 1):
            candidato = "-".join(partes[inicio:inicio + tamanho])
            if candidato in especies:
                return candidato, set(range(inicio, inicio + tamanho))
    return None, set()


def conciliar(nome, indice):
    formas = indice["forma_por_nome"]
    especies = indice["especie_por_nome"]
    padrao = indice["padrao_por_especie"]
    direto = normalizar(nome)

    alvo = EXCECOES_MANUAIS.get(direto)
    if alvo in formas:
        return formas[alvo], "excecao_manual"
    if direto in formas:
        return formas[direto], "nome_direto"
    if direto in especies and padrao.get(direto) in formas:
        return formas[padrao[direto]], "especie_forma_padrao"

    partes = fragmentar(nome)
    especie, posicoes = localizar_especie(partes, especies)
    if especie is None:
        return None, "especie_nao_identificada"
    tokens_especie = set(especie.split("-"))
    qualificadores = [
        parte for posicao, parte in enumerate(partes)
        if posicao not in posicoes and parte not in tokens_especie and parte not in TERMOS_GENERICOS
    ]
    if not qualificadores and padrao.get(especie) in formas:
        return formas[padrao[especie]], "tokens_forma_padrao"
    if len(qualificadores) <= 4:
        for permutacao in itertools.permutations(qualificadores):
            candidato = "-".join((especie,) + permutacao)
            if candidato in formas:
                return formas[candidato], "tokens_qualificadores"
    if padrao.get(especie) in formas:
        return formas[padrao[especie]], "especie_forma_padrao_inferida"
    return None, "forma_nao_encontrada"


def categoria_raridade(especie):
    if especie["is_mythical"]:
        return "Mítico"
    if especie["is_legendary"]:
        return "Lendário"
    if especie["is_baby"]:
        return "Bebê"
    return "Comum"


def categoria_forma(forma):
    if forma["is_default"]:
        return "Padrão"
    partes = forma["name"].split("-")
    if "mega" in partes:
        return "Mega"
    if "primal" in partes:
        return "Primal"
    return "Outra forma"


def atributos_csv(linha):
    tipo1 = linha["Type 1"].strip().lower()
    tipo2 = linha["Type 2"].strip().lower()
    for tipo in filter(None, (tipo1, tipo2)):
        if tipo not in TIPOS_PT:
            raise RuntimeError(f"Tipo desconhecido no registro #{linha['#']}: {tipo}")
    status = {
        "hp": int(linha["HP"]),
        "ataque": int(linha["Attack"]),
        "defesa": int(linha["Defense"]),
        "ataque_especial": int(linha["Sp. Atk"]),
        "defesa_especial": int(linha["Sp. Def"]),
        "velocidade": int(linha["Speed"]),
    }
    status["total_status"] = sum(status.values())
    return {
        "numero_csv": int(linha["#"]),
        "tipo1": tipo1,
        "tipo2": tipo2 or None,
        "tipo_primario": TIPOS_PT[tipo1],
        "tipo_secundario": TIPOS_PT[tipo2] if tipo2 else SEM_SEGUNDO_TIPO,
        "numero_geracao_csv": int(linha["Generation"]),
        "lendario_csv": linha["Legendary"].strip().lower() == "true",
        **status,
    }


def atributos_desconhecidos():
    return {
        "numero_pokedex": None,
        "id_pokeapi": None,
        "nome_pokeapi": NAO_INFORMADO,
        "especie": NAO_INFORMADO,
        "categoria_forma": NAO_INFORMADO,
        "categoria_raridade": NAO_INFORMADO,
        "habitat": NAO_INFORMADO,
        "cor": NAO_INFORMADO,
        "forma_corporal": NAO_INFORMADO,
        "taxa_crescimento": NAO_INFORMADO,
        "grupos_ovo": NAO_INFORMADO,
        "taxa_captura": None,
        "felicidade_base": None,
        "experiencia_base": None,
        "altura_m": None,
        "peso_kg": None,
        "qtd_habilidades": None,
    }


def atributos_api(forma, especie):
    numero_geracao = numero_da_geracao(especie["generation"]["name"])
    if especie.get("habitat"):
        habitat = especie["habitat"]["name"]
    elif numero_geracao > ULTIMA_GERACAO_COM_HABITAT:
        habitat = NAO_SE_APLICA
    else:
        habitat = NAO_INFORMADO
    grupos = ", ".join(sorted(g["name"] for g in especie.get("egg_groups") or []))
    return {
        "numero_pokedex": especie["id"],
        "id_pokeapi": forma["id"],
        "nome_pokeapi": forma["name"],
        "especie": especie["name"],
        "categoria_forma": categoria_forma(forma),
        "categoria_raridade": categoria_raridade(especie),
        "habitat": habitat,
        "cor": nome_ou(especie.get("color")),
        "forma_corporal": nome_ou(especie.get("shape")),
        "taxa_crescimento": nome_ou(especie.get("growth_rate")),
        "grupos_ovo": grupos or NAO_INFORMADO,
        "taxa_captura": especie.get("capture_rate"),
        "felicidade_base": especie.get("base_happiness"),
        "experiencia_base": forma.get("base_experience"),
        "altura_m": Decimal(forma["height"]) / 10 if forma.get("height") is not None else None,
        "peso_kg": Decimal(forma["weight"]) / 10 if forma.get("weight") is not None else None,
        "qtd_habilidades": len(forma.get("abilities") or []),
        "numero_geracao_api": numero_geracao,
    }


def divergencias(base, forma, geracao_api):
    lista = []
    tipos_api = [t["type"]["name"] for t in sorted(forma["types"], key=lambda t: t["slot"])]
    tipos_csv = [t for t in (base["tipo1"], base["tipo2"]) if t]
    if tipos_api != tipos_csv:
        lista.append(f"tipos csv={'/'.join(tipos_csv)} api={'/'.join(tipos_api)}")
    colunas = {
        "hp": "hp", "attack": "ataque", "defense": "defesa",
        "special-attack": "ataque_especial", "special-defense": "defesa_especial", "speed": "velocidade",
    }
    for item in forma["stats"]:
        nome = item["stat"]["name"]
        if nome in colunas and base[colunas[nome]] != item["base_stat"]:
            lista.append(f"{colunas[nome]} csv={base[colunas[nome]]} api={item['base_stat']}")
    if base["numero_geracao_csv"] != geracao_api:
        lista.append(f"geracao csv={base['numero_geracao_csv']} api={geracao_api}")
    return lista


def montar_pokemon(linhas_csv, indice):
    registros = []
    auditoria = []
    proximo_especial = -1
    alvos = {}

    for linha in sorted(linhas_csv, key=lambda d: int(d["#"])):
        base = atributos_csv(linha)
        nome = (linha.get("Name") or "").strip()
        registro = {**base, "eh_membro_especial": False}
        entrada = {
            "numero_csv": base["numero_csv"],
            "nome_csv": nome,
            "nome_normalizado": normalizar(nome) if nome else "",
            "metodo": "",
            "nome_pokeapi": "",
            "id_pokeapi": "",
            "numero_pokedex": "",
            "divergencias": "",
        }

        if not nome:
            registro.update(atributos_desconhecidos())
            registro.update({
                "sk_pokemon": proximo_especial,
                "nome": f"{NAO_INFORMADO} (registro #{base['numero_csv']})",
                "status_conciliacao": "sem_nome",
                "numero_geracao": base["numero_geracao_csv"],
                "eh_membro_especial": True,
            })
            entrada.update({
                "status": "sem_nome",
                "metodo": "nenhum",
                "sk_pokemon": proximo_especial,
                "tratamento": "Dado ausente: membro especial da dim_pokemon com atributos do CSV preservados; combates mantidos",
            })
            proximo_especial -= 1
        else:
            forma, metodo = conciliar(nome, indice)
            if forma is None:
                registro.update(atributos_desconhecidos())
                registro.update({
                    "nome": nome,
                    "status_conciliacao": "nao_conciliado",
                    "numero_geracao": base["numero_geracao_csv"],
                })
                entrada.update({
                    "status": "nao_conciliado",
                    "metodo": metodo,
                    "tratamento": "Mantido na dimensão com atributos do CSV; atributos da PokéAPI como Não informado",
                })
            else:
                especie = indice["especie_por_nome"][forma["species"]["name"]]
                api = atributos_api(forma, especie)
                registro.update(api)
                registro.update({
                    "nome": nome,
                    "status_conciliacao": "conciliado",
                    "numero_geracao": api["numero_geracao_api"],
                })
                lista = divergencias(base, forma, api["numero_geracao_api"])
                alvos.setdefault(forma["name"], []).append(base["numero_csv"])
                inferido = metodo == "especie_forma_padrao_inferida"
                entrada.update({
                    "status": "conciliado",
                    "metodo": metodo,
                    "nome_pokeapi": forma["name"],
                    "id_pokeapi": forma["id"],
                    "numero_pokedex": especie["id"],
                    "divergencias": "; ".join(lista),
                    "tratamento": (
                        "Conciliado por inferência da forma padrão da espécie; conferir manualmente"
                        if inferido else "Conciliado; tipos e status do CSV, classificação da PokéAPI"
                    ),
                })
        numero_geracao = registro["numero_geracao"]
        if numero_geracao not in GERACOES:
            raise RuntimeError(f"Geração fora do escopo no registro #{base['numero_csv']}: {numero_geracao}")
        registro["geracao"], registro["regiao"] = GERACOES[numero_geracao]
        registros.append(registro)
        auditoria.append(entrada)

    for entrada in auditoria:
        repetidos = alvos.get(entrada["nome_pokeapi"], [])
        if len(repetidos) > 1:
            outros = ",".join(str(n) for n in repetidos if n != entrada["numero_csv"])
            complemento = f"alvo compartilhado com #{outros}"
            entrada["divergencias"] = "; ".join(filter(None, (entrada["divergencias"], complemento)))
    return registros, auditoria


def escrever_conciliacao(auditoria):
    colunas = [
        "numero_csv", "nome_csv", "nome_normalizado", "status", "metodo", "nome_pokeapi",
        "id_pokeapi", "numero_pokedex", "tratamento", "divergencias",
    ]
    with ARQUIVO_CONCILIACAO.open("w", encoding="utf-8", newline="") as arquivo:
        escritor = csv.DictWriter(arquivo, fieldnames=colunas, extrasaction="ignore", lineterminator="\n")
        escritor.writeheader()
        escritor.writerows(auditoria)

    contagem_status = {}
    contagem_metodo = {}
    for entrada in auditoria:
        contagem_status[entrada["status"]] = contagem_status.get(entrada["status"], 0) + 1
        contagem_metodo[entrada["metodo"]] = contagem_metodo.get(entrada["metodo"], 0) + 1
    pendentes = [e for e in auditoria if e["status"] != "conciliado" or e["metodo"] == "especie_forma_padrao_inferida"]
    com_divergencia = sum(1 for e in auditoria if e["divergencias"])

    linhas = [
        "# Resumo da conciliação de chaves",
        "",
        f"Gerado por `carregar.py` a partir da camada bronze. Detalhe por registro em `{ARQUIVO_CONCILIACAO.name}`.",
        "",
        f"- Registros no pokemon.csv: {len(auditoria)}",
    ]
    for status in sorted(contagem_status):
        linhas.append(f"- Status `{status}`: {contagem_status[status]}")
    linhas.append(f"- Registros conciliados com divergência de tipo, status ou geração: {com_divergencia}")
    linhas += ["", "## Registros por método de conciliação", "", "| Método | Registros |", "|---|---:|"]
    for metodo in sorted(contagem_metodo):
        linhas.append(f"| {metodo} | {contagem_metodo[metodo]} |")
    linhas += [
        "",
        "## Registros não conciliados ou conciliados por inferência",
        "",
        "| # | Nome no CSV | Status | Método | Tratamento |",
        "|---:|---|---|---|---|",
    ]
    for entrada in pendentes:
        linhas.append(
            f"| {entrada['numero_csv']} | {entrada['nome_csv'] or '(vazio)'} | {entrada['status']} "
            f"| {entrada['metodo']} | {entrada['tratamento']} |"
        )
    if not pendentes:
        linhas.append("| — | — | — | — | Nenhum registro pendente |")
    ARQUIVO_RESUMO.write_text("\n".join(linhas) + "\n", encoding="utf-8")
    return contagem_status


def montar_fato(combates, perfil):
    linhas = []
    for documento in sorted(combates, key=lambda d: d["_linha"]):
        primeiro = int(documento["First_pokemon"])
        segundo = int(documento["Second_pokemon"])
        vencedor = int(documento["Winner"])
        if vencedor not in (primeiro, segundo):
            raise RuntimeError(f"Vencedor inválido no combate {documento['_linha']}")
        for proprio, oponente, atacou_primeiro in ((primeiro, segundo, 1), (segundo, primeiro, 0)):
            if proprio not in perfil or oponente not in perfil:
                raise RuntimeError(f"Combate {documento['_linha']} referencia registro inexistente")
            a, b = perfil[proprio], perfil[oponente]
            linhas.append((
                documento["_linha"],
                atacou_primeiro,
                a["sk_pokemon"],
                b["sk_pokemon"],
                a["sk_tipo1"],
                a["sk_tipo2"],
                b["sk_tipo1"],
                b["sk_tipo2"],
                a["sk_geracao"],
                b["sk_geracao"],
                1 if vencedor == proprio else 0,
                a["velocidade"] - b["velocidade"],
                a["total_status"] - b["total_status"],
            ))
    return linhas


def carregar_postgres(tipos, efetividade, registros, combates):
    agora = datetime.now(timezone.utc)
    with psycopg.connect(PG_DSN) as conexao:
        with conexao.cursor() as cursor:
            cursor.execute(ler_sql("controle.sql"))
            cursor.execute(ler_sql("silver.sql"))
            cursor.execute(
                "TRUNCATE silver.fato_confronto, silver.efetividade_tipo, silver.dim_pokemon, "
                "silver.dim_tipo, silver.dim_geracao RESTART IDENTITY"
            )

            cursor.executemany(
                "INSERT INTO silver.dim_geracao (numero_geracao, nome_geracao, regiao) VALUES (%s, %s, %s)",
                [(numero, nome, regiao) for numero, (nome, regiao) in sorted(GERACOES.items())],
            )
            sk_geracao = dict(cursor.execute("SELECT numero_geracao, sk_geracao FROM silver.dim_geracao").fetchall())

            cursor.execute(
                "INSERT INTO silver.dim_tipo (sk_tipo, id_tipo_pokeapi, nome_tipo, nome_tipo_pt, eh_membro_especial) "
                "VALUES (%s, NULL, %s, %s, TRUE)",
                (SK_SEM_SEGUNDO_TIPO, SEM_SEGUNDO_TIPO, SEM_SEGUNDO_TIPO),
            )
            cursor.executemany(
                "INSERT INTO silver.dim_tipo (id_tipo_pokeapi, nome_tipo, nome_tipo_pt, eh_membro_especial) "
                "VALUES (%s, %s, %s, FALSE)",
                [(t["id"], t["name"], TIPOS_PT[t["name"]]) for t in tipos],
            )
            sk_tipo = dict(cursor.execute("SELECT nome_tipo, sk_tipo FROM silver.dim_tipo").fetchall())

            cursor.executemany(
                "INSERT INTO silver.efetividade_tipo (sk_tipo_atacante, sk_tipo_defensor, multiplicador) "
                "VALUES (%s, %s, %s)",
                [(sk_tipo[a], sk_tipo[d], fator) for (a, d), fator in sorted(efetividade.items())],
            )

            colunas = ", ".join(COLUNAS_DIM_POKEMON)
            marcadores = ", ".join(["%s"] * len(COLUNAS_DIM_POKEMON))
            especiais = [r for r in registros if r["eh_membro_especial"]]
            regulares = [r for r in registros if not r["eh_membro_especial"]]
            cursor.executemany(
                f"INSERT INTO silver.dim_pokemon (sk_pokemon, {colunas}) VALUES (%s, {marcadores})",
                [(r["sk_pokemon"], *[r[c] for c in COLUNAS_DIM_POKEMON]) for r in especiais],
            )
            cursor.executemany(
                f"INSERT INTO silver.dim_pokemon ({colunas}) VALUES ({marcadores})",
                [tuple(r[c] for c in COLUNAS_DIM_POKEMON) for r in regulares],
            )
            sk_pokemon = dict(cursor.execute("SELECT numero_csv, sk_pokemon FROM silver.dim_pokemon").fetchall())

            perfil = {
                r["numero_csv"]: {
                    "sk_pokemon": sk_pokemon[r["numero_csv"]],
                    "sk_tipo1": sk_tipo[r["tipo1"]],
                    "sk_tipo2": sk_tipo[r["tipo2"]] if r["tipo2"] else SK_SEM_SEGUNDO_TIPO,
                    "sk_geracao": sk_geracao[r["numero_geracao"]],
                    "velocidade": r["velocidade"],
                    "total_status": r["total_status"],
                }
                for r in registros
            }
            linhas_fato = montar_fato(combates, perfil)
            with cursor.copy(f"COPY silver.fato_confronto ({', '.join(COLUNAS_FATO)}) FROM STDIN") as copia:
                for linha in linhas_fato:
                    copia.write_row(linha)

            total, distintos, vitorias = cursor.execute(
                "SELECT COUNT(*), COUNT(DISTINCT id_combate), SUM(venceu) FROM silver.fato_confronto"
            ).fetchone()
            esperado = len(combates)
            if (total, distintos, vitorias) != (2 * esperado, esperado, esperado):
                raise RuntimeError(
                    f"Fato inconsistente: {total} linhas, {distintos} combates, {vitorias} vitórias; "
                    f"esperado {2 * esperado}, {esperado}, {esperado}"
                )

            contagens = {}
            for tabela in TABELAS_SILVER:
                contagens[tabela] = cursor.execute(f"SELECT COUNT(*) FROM {tabela}").fetchone()[0]
            cursor.executemany(
                "INSERT INTO controle.execucao (etapa, tabela, linhas, executado_em) VALUES ('carregar', %s, %s, %s)",
                [(tabela, quantidade, agora) for tabela, quantidade in contagens.items()],
            )
        conexao.commit()
    return contagens, agora


def main():
    inicio = time.time()
    print("Lendo a camada bronze (MongoDB)...")
    dados = ler_bronze()

    tipos = montar_tipos(dados["tipos"])
    efetividade, inconsistencias = montar_efetividade(tipos)
    if inconsistencias:
        print(f"Aviso: {len(inconsistencias)} pares com damage_relations _to e _from divergentes; prevalece _to")

    indice = indexar_api(dados["especies"], dados["pokemon"])
    registros, auditoria = montar_pokemon(dados["pokemon_csv"], indice)
    contagem_status = escrever_conciliacao(auditoria)
    print("Conciliação de chaves:")
    for status, quantidade in sorted(contagem_status.items()):
        print(f"  {status:<16} {quantidade:>5}")
    print(f"  relatório: {ARQUIVO_CONCILIACAO.name} e {ARQUIVO_RESUMO.name}")

    print("Carregando o silver (PostgreSQL)...")
    contagens, momento = carregar_postgres(tipos, efetividade, registros, dados["combates"])
    print(f"Carga concluída em {momento.isoformat(timespec='seconds')}")
    for tabela, quantidade in contagens.items():
        print(f"  {tabela:<26} {quantidade:>7} linhas")
    print(f"Tempo total: {time.time() - inicio:.1f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
