import csv
import io
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from pymongo import MongoClient, ReplaceOne

RAIZ = Path(__file__).resolve().parent
CACHE = Path(os.environ.get("CACHE_DIR", RAIZ / "dados_brutos"))
MONGO_URI = os.environ.get("MONGO_URI", "mongodb://localhost:27017")
MONGO_DB = os.environ.get("MONGO_DB", "pokedex_bronze")

API = "https://pokeapi.co/api/v2"
PRIMEIRA_ESPECIE = 1
ULTIMA_ESPECIE = 721
INTERVALO_SEGUNDOS = 0.1
TENTATIVAS = 5
TAMANHO_LOTE = 2000

FONTE_API = "pokeapi"
FONTE_CSV = "pokemon_app_csv"
URL_POKEMON_CSV = "https://raw.githubusercontent.com/cdiener/pokemon_app/master/pokemon.csv"
URL_COMBATES_CSV = "https://raw.githubusercontent.com/cdiener/pokemon_app/master/combats.csv"


class ClienteComCache:
    def __init__(self):
        self.sessao = requests.Session()
        self.sessao.headers["User-Agent"] = "pokedex-pipeline-etl/1.0 (trabalho academico)"
        self.requisicoes = 0

    def obter(self, url, destino):
        if destino.exists():
            return destino.read_bytes()
        ultimo_erro = None
        for tentativa in range(TENTATIVAS):
            try:
                resposta = self.sessao.get(url, timeout=30)
            except requests.RequestException as erro:
                ultimo_erro = erro
                self.requisicoes += 1
                time.sleep(2 ** tentativa)
                continue
            self.requisicoes += 1
            time.sleep(INTERVALO_SEGUNDOS)
            if resposta.status_code == 200:
                destino.parent.mkdir(parents=True, exist_ok=True)
                temporario = destino.with_name(destino.name + ".parcial")
                temporario.write_bytes(resposta.content)
                temporario.replace(destino)
                return resposta.content
            if resposta.status_code in (429, 500, 502, 503, 504):
                ultimo_erro = RuntimeError(f"HTTP {resposta.status_code} em {url}")
                time.sleep(2 ** tentativa)
                continue
            resposta.raise_for_status()
        raise RuntimeError(f"Falha ao obter {url}: {ultimo_erro}")


def momento_obtencao(caminho):
    instante = datetime.fromtimestamp(caminho.stat().st_mtime, tz=timezone.utc)
    return instante.strftime("%Y-%m-%dT%H:%M:%SZ")


def caminho_relativo(caminho):
    try:
        return caminho.resolve().relative_to(RAIZ).as_posix()
    except ValueError:
        return caminho.resolve().as_posix()


def id_da_url(url):
    return int(url.rstrip("/").split("/")[-1])


def documento_api(prefixo, identificador, url, caminho, conteudo):
    documento = {
        "_id": f"{prefixo}/{identificador}",
        "_fonte": FONTE_API,
        "_url": url,
        "_arquivo": caminho_relativo(caminho),
        "_ingerido_em": momento_obtencao(caminho),
    }
    documento.update(json.loads(conteudo))
    return documento


def extrair_api(cliente):
    especies, formas, tipos = [], [], []

    url_lista_tipos = f"{API}/type?limit=100"
    caminho_lista = CACHE / "listas" / "tipos.json"
    lista_tipos = json.loads(cliente.obter(url_lista_tipos, caminho_lista))
    for item in lista_tipos["results"]:
        identificador = id_da_url(item["url"])
        url = f"{API}/type/{identificador}"
        caminho = CACHE / "tipos" / f"{identificador}.json"
        tipos.append(documento_api("tipo", identificador, url, caminho, cliente.obter(url, caminho)))

    formas_vistas = set()
    for numero in range(PRIMEIRA_ESPECIE, ULTIMA_ESPECIE + 1):
        url = f"{API}/pokemon-species/{numero}"
        caminho = CACHE / "especies" / f"{numero}.json"
        documento = documento_api("especie", numero, url, caminho, cliente.obter(url, caminho))
        especies.append(documento)
        for variedade in documento["varieties"]:
            identificador = id_da_url(variedade["pokemon"]["url"])
            if identificador in formas_vistas:
                continue
            formas_vistas.add(identificador)
            url_forma = f"{API}/pokemon/{identificador}"
            caminho_forma = CACHE / "pokemon" / f"{identificador}.json"
            conteudo = cliente.obter(url_forma, caminho_forma)
            formas.append(documento_api("pokemon", identificador, url_forma, caminho_forma, conteudo))
        if numero % 50 == 0:
            print(f"  espécies processadas: {numero}/{ULTIMA_ESPECIE} | requisições: {cliente.requisicoes}")

    return especies, formas, tipos


def ler_csv(conteudo):
    texto = conteudo.decode("utf-8-sig")
    return list(csv.DictReader(io.StringIO(texto, newline="")))


def documento_csv(prefixo, chave, url, caminho, numero_linha, linha):
    documento = {
        "_id": f"{prefixo}/{chave}",
        "_fonte": FONTE_CSV,
        "_url": url,
        "_arquivo": caminho_relativo(caminho),
        "_linha": numero_linha,
        "_ingerido_em": momento_obtencao(caminho),
    }
    documento.update(linha)
    return documento


def extrair_csv(cliente):
    caminho_pokemon = CACHE / "csv" / "pokemon.csv"
    caminho_combates = CACHE / "csv" / "combats.csv"
    linhas_pokemon = ler_csv(cliente.obter(URL_POKEMON_CSV, caminho_pokemon))
    linhas_combates = ler_csv(cliente.obter(URL_COMBATES_CSV, caminho_combates))

    pokemon_csv = [
        documento_csv("pokemon_csv", linha["#"], URL_POKEMON_CSV, caminho_pokemon, indice, linha)
        for indice, linha in enumerate(linhas_pokemon, start=1)
    ]
    combates = [
        documento_csv("combate", indice, URL_COMBATES_CSV, caminho_combates, indice, linha)
        for indice, linha in enumerate(linhas_combates, start=1)
    ]
    return pokemon_csv, combates


def gravar(colecao, documentos):
    ids = [documento["_id"] for documento in documentos]
    if len(ids) != len(set(ids)):
        raise RuntimeError(f"Chaves duplicadas na coleção {colecao.name}")
    for inicio in range(0, len(documentos), TAMANHO_LOTE):
        lote = documentos[inicio:inicio + TAMANHO_LOTE]
        operacoes = [ReplaceOne({"_id": documento["_id"]}, documento, upsert=True) for documento in lote]
        colecao.bulk_write(operacoes, ordered=False)
    return colecao.count_documents({})


def main():
    inicio = time.time()
    cliente = ClienteComCache()

    print("Extraindo PokéAPI (com cache em disco)...")
    especies, formas, tipos = extrair_api(cliente)
    print("Extraindo arquivos CSV...")
    pokemon_csv, combates = extrair_csv(cliente)

    mongo = MongoClient(MONGO_URI, serverSelectionTimeoutMS=10000)
    banco = mongo[MONGO_DB]
    resultado = {
        "pokemon": gravar(banco["pokemon"], formas),
        "especies": gravar(banco["especies"], especies),
        "tipos": gravar(banco["tipos"], tipos),
        "pokemon_csv": gravar(banco["pokemon_csv"], pokemon_csv),
        "combates": gravar(banco["combates"], combates),
    }
    mongo.close()

    print()
    print(f"Banco: {MONGO_DB}")
    for colecao, quantidade in resultado.items():
        print(f"  {colecao:<12} {quantidade:>7} documentos")
    print(f"Requisições HTTP realizadas nesta execução: {cliente.requisicoes}")
    print(f"Tempo total: {time.time() - inicio:.1f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
