"""
NASAJON - Prova Técnica
"""

import csv
import json
import os
import sys
import unicodedata
from collections import defaultdict

import requests
from rapidfuzz import process, fuzz

IBGE_URL = "https://servicodados.ibge.gov.br/api/v1/localidades/municipios"
SUBMIT_URL = "https://mynxlubykylncinttggu.functions.supabase.co/ibge-submit"

INPUT_FILE = "input.csv"
OUTPUT_FILE = "resultado.csv"

FUZZY_THRESHOLD = 80


def normalizar(texto: str) -> str:
    """Remove acentos e coloca em minúsculas para comparação."""
    sem_acento = unicodedata.normalize("NFKD", texto)
    sem_acento = "".join(c for c in sem_acento if not unicodedata.combining(c))
    return sem_acento.lower().strip()


# ---------------------------------------------------------------------------
# 1. Leitura do input.csv
# ---------------------------------------------------------------------------
def ler_input(caminho: str) -> list[dict]:
    municipios = []
    with open(caminho, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            municipios.append({
                "municipio": row["municipio"].strip(),
                "populacao": int(row["populacao"].strip()),
            })
    return municipios


# ---------------------------------------------------------------------------
# 2. Busca de todos os municípios do IBGE
# ---------------------------------------------------------------------------
def buscar_municipios_ibge() -> list[dict]:
    print("Buscando municípios na API do IBGE...")
    resp = requests.get(IBGE_URL, timeout=30)
    resp.raise_for_status()
    dados = resp.json()
    print(f"  {len(dados)} municípios carregados.")
    return dados


def construir_indice(dados_ibge: list[dict]) -> dict:
    """Retorna {nome_normalizado: {nome, uf, regiao, id}} para busca rápida."""
    indice = {}
    for m in dados_ibge:
        try:
            nome = m["nome"]
            microrregiao = m.get("microrregiao") or {}
            mesorregiao = microrregiao.get("mesorregiao") or {}
            uf_obj = mesorregiao.get("UF") or {}
            regiao_obj = uf_obj.get("regiao") or {}
            uf = uf_obj.get("sigla", "")
            regiao = regiao_obj.get("nome", "")
            id_ibge = m["id"]
            chave = normalizar(nome)
            indice[chave] = {
                "municipio_ibge": nome,
                "uf": uf,
                "regiao": regiao,
                "id_ibge": id_ibge,
            }
        except Exception:
            continue
    return indice


# ---------------------------------------------------------------------------
# 3. Matching
# ---------------------------------------------------------------------------
def encontrar_municipio(nome_input: str, indice: dict, chaves: list[str]) -> dict | None:
    chave_input = normalizar(nome_input)

    # Tentativa 1 – match exato
    if chave_input in indice:
        return indice[chave_input]

    # Tentativa 2 – fuzzy match
    resultado = process.extractOne(
        chave_input,
        chaves,
        scorer=fuzz.token_sort_ratio,
        score_cutoff=FUZZY_THRESHOLD,
    )
    if resultado:
        melhor_chave, score, _ = resultado
        print(f"  Fuzzy match: '{nome_input}' → '{indice[melhor_chave]['municipio_ibge']}' (score={score:.1f})")
        return indice[melhor_chave]

    return None


# ---------------------------------------------------------------------------
# 4. Processamento principal
# ---------------------------------------------------------------------------
def processar(municipios_input: list[dict], dados_ibge: list[dict]) -> list[dict]:
    indice = construir_indice(dados_ibge)
    chaves = list(indice.keys())
    resultados = []
    ibge_ids_ok: set = set()  # evita que dois inputs reivindiquem o mesmo município IBGE

    for row in municipios_input:
        nome = row["municipio"]
        pop = row["populacao"]

        try:
            match = encontrar_municipio(nome, indice, chaves)
        except Exception as e:
            print(f"  ERRO_API ao buscar '{nome}': {e}")
            resultados.append({
                "municipio_input": nome,
                "populacao_input": pop,
                "municipio_ibge": "",
                "uf": "",
                "regiao": "",
                "id_ibge": "",
                "status": "ERRO_API",
            })
            continue

        if match:
            ibge_id = match["id_ibge"]
            if ibge_id in ibge_ids_ok:
                # Mesmo município IBGE já foi reivindicado por outro input → duplicata
                print(f"  NAO_ENCONTRADO (duplicata IBGE {ibge_id}): '{nome}'")
                resultados.append({
                    "municipio_input": nome,
                    "populacao_input": pop,
                    "municipio_ibge": "",
                    "uf": "",
                    "regiao": "",
                    "id_ibge": "",
                    "status": "NAO_ENCONTRADO",
                })
            else:
                ibge_ids_ok.add(ibge_id)
                resultados.append({
                    "municipio_input": nome,
                    "populacao_input": pop,
                    "municipio_ibge": match["municipio_ibge"],
                    "uf": match["uf"],
                    "regiao": match["regiao"],
                    "id_ibge": match["id_ibge"],
                    "status": "OK",
                })
        else:
            print(f"  NAO_ENCONTRADO: '{nome}'")
            resultados.append({
                "municipio_input": nome,
                "populacao_input": pop,
                "municipio_ibge": "",
                "uf": "",
                "regiao": "",
                "id_ibge": "",
                "status": "NAO_ENCONTRADO",
            })

    return resultados


# ---------------------------------------------------------------------------
# 5. Geração do resultado.csv
# ---------------------------------------------------------------------------
def gerar_csv(resultados: list[dict], caminho: str):
    campos = ["municipio_input", "populacao_input", "municipio_ibge", "uf", "regiao", "id_ibge", "status"]
    with open(caminho, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=campos)
        writer.writeheader()
        writer.writerows(resultados)
    print(f"resultado.csv gerado em '{caminho}'.")


# ---------------------------------------------------------------------------
# 6. Cálculo de estatísticas
# ---------------------------------------------------------------------------
def calcular_estatisticas(resultados: list[dict]) -> dict:
    total_municipios = len(resultados)
    total_ok = sum(1 for r in resultados if r["status"] == "OK")
    total_nao_encontrado = sum(1 for r in resultados if r["status"] == "NAO_ENCONTRADO")
    total_erro_api = sum(1 for r in resultados if r["status"] == "ERRO_API")
    pop_total_ok = sum(r["populacao_input"] for r in resultados if r["status"] == "OK")

    # Média de população por região (apenas status OK)
    pop_por_regiao: dict[str, list[int]] = defaultdict(list)
    for r in resultados:
        if r["status"] == "OK" and r["regiao"]:
            pop_por_regiao[r["regiao"]].append(r["populacao_input"])

    medias_por_regiao = {
        regiao: round(sum(pops) / len(pops), 2)
        for regiao, pops in pop_por_regiao.items()
    }

    return {
        "total_municipios": total_municipios,
        "total_ok": total_ok,
        "total_nao_encontrado": total_nao_encontrado,
        "total_erro_api": total_erro_api,
        "pop_total_ok": pop_total_ok,
        "medias_por_regiao": medias_por_regiao,
    }


# ---------------------------------------------------------------------------
# 7. Envio para a API de correção
# ---------------------------------------------------------------------------
def enviar_resultado(stats: dict, access_token: str):
    payload = {"stats": stats}
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }
    print("\nEnviando resultado para a API de correção...")
    print("Payload:", json.dumps(payload, indent=2, ensure_ascii=False))

    resp = requests.post(SUBMIT_URL, json=payload, headers=headers, timeout=30)
    print(f"\nHTTP {resp.status_code}")

    try:
        resposta = resp.json()
        print("Resposta da API:")
        print(json.dumps(resposta, indent=2, ensure_ascii=False))
    except Exception:
        print("Resposta (texto):", resp.text)

    return resp


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main():
    ACCESS_TOKEN_FIXO = "eyJhbGciOiJIUzI1NiIsImtpZCI6ImR0TG03UVh1SkZPVDJwZEciLCJ0eXAiOiJKV1QifQ.eyJpc3MiOiJodHRwczovL215bnhsdWJ5a3lsbmNpbnR0Z2d1LnN1cGFiYXNlLmNvL2F1dGgvdjEiLCJzdWIiOiI4NjVjNjcwZi1lOTVlLTRkZjQtYjk0ZC1iYWMwNzE5ZjM5NmIiLCJhdWQiOiJhdXRoZW50aWNhdGVkIiwiZXhwIjoxNzc1ODU5NTg4LCJpYXQiOjE3NzU4NTU5ODgsImVtYWlsIjoiZ2FicmllbHJlaW5lcnRiQGdtYWlsLmNvbSIsInBob25lIjoiIiwiYXBwX21ldGFkYXRhIjp7InByb3ZpZGVyIjoiZW1haWwiLCJwcm92aWRlcnMiOlsiZW1haWwiXX0sInVzZXJfbWV0YWRhdGEiOnsiZW1haWwiOiJnYWJyaWVscmVpbmVydGJAZ21haWwuY29tIiwiZW1haWxfdmVyaWZpZWQiOnRydWUsIm5vbWUiOiJHYWJyaWVsIEJvbmFsdW1lIFJlaW5lcnQiLCJwaG9uZV92ZXJpZmllZCI6ZmFsc2UsInN1YiI6Ijg2NWM2NzBmLWU5NWUtNGRmNC1iOTRkLWJhYzA3MTlmMzk2YiJ9LCJyb2xlIjoiYXV0aGVudGljYXRlZCIsImFhbCI6ImFhbDEiLCJhbXIiOlt7Im1ldGhvZCI6InBhc3N3b3JkIiwidGltZXN0YW1wIjoxNzc1ODU1OTg4fV0sInNlc3Npb25faWQiOiI4MGJhYjU2MS1kYzYyLTQ4YTItOGNhMi04NzZkZWRkZjU0MDIiLCJpc19hbm9ueW1vdXMiOmZhbHNlfQ.oeePVAvFAURj-Ov4zuk5eydWOHf2bBNuLSup8t8pZlc"

    if len(sys.argv) > 1:
        access_token = sys.argv[1]
    else:
        access_token = os.environ.get("ACCESS_TOKEN", ACCESS_TOKEN_FIXO)

    if not access_token:
        print("ERRO: forneça o ACCESS_TOKEN como argumento ou variável de ambiente.")
        print("  Uso: python main.py <SEU_ACCESS_TOKEN>")
        print("  Ou:  $env:ACCESS_TOKEN='<token>'; python main.py")
        sys.exit(1)

    # Passo 1 – leitura
    municipios_input = ler_input(INPUT_FILE)
    print(f"Lidos {len(municipios_input)} municípios de '{INPUT_FILE}'.")

    # Passo 2 – API IBGE
    try:
        dados_ibge = buscar_municipios_ibge()
    except Exception as e:
        print(f"ERRO ao acessar a API do IBGE: {e}")
        sys.exit(1)

    # Passo 3/4 – matching + resultado.csv
    resultados = processar(municipios_input, dados_ibge)
    gerar_csv(resultados, OUTPUT_FILE)

    # Passo 5 – estatísticas
    stats = calcular_estatisticas(resultados)
    print("\nEstatísticas calculadas:")
    print(json.dumps(stats, indent=2, ensure_ascii=False))

    # Passo 6 – envio
    enviar_resultado(stats, access_token)


if __name__ == "__main__":
    main()
