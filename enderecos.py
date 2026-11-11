"""
Transforma os endereços do farmacias_cnpj.csv (Receita) em pontos no mapa.

Para cada farmácia:
  1. procura o endereço com número no OpenStreetMap (Nominatim)  -> "exato" ou "rua"
  2. se não achar, usa o CEP: coordenada do CEP (BrasilAPI) ou o nome
     oficial da rua pelo CEP (ViaCEP) procurado no OpenStreetMap  -> "cep"

Ficam de fora do mapa: SCPs (sociedades de investimento, não lojas) e
endereços com 10 ou mais empresas diferentes (sede fiscal, não farmácia).
As que não foram achadas são procuradas de novo a cada rodada.

Tem memória (enderecos_cache.csv): só procura o que é novo ou mudou de
endereço. A primeira rodada é longa (cerca de 2 horas); as mensais, curtas.

Resultado: farmacias_receita.json, que o mapa vai ler.
"""
import csv, json, os, sys, time, urllib.request, urllib.parse, datetime

ENTRADA = "farmacias_cnpj.csv"
CACHE = "enderecos_cache.csv"
SAIDA = "farmacias_receita.json"
UA = {"User-Agent": "mapa-farmacias (github.com/WD1951/mapa-farmacias)"}
CAIXA = (-24.01, -46.83, -23.35, -46.36)   # cidade de São Paulo
LIMITE_REDE = 5
SALVAR_A_CADA = 100


CENTRO_FALSO = (-23.5475, -46.63611)      # "centro da cidade" que o serviço de CEP
                                          # devolve quando não sabe a coordenada


def eh_centro_falso(lat, lon):
    return abs(lat - CENTRO_FALSO[0]) < 0.001 and abs(lon - CENTRO_FALSO[1]) < 0.001


def dentro(lat, lon):
    return CAIXA[0] <= lat <= CAIXA[2] and CAIXA[1] <= lon <= CAIXA[3]


def pegar_json(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def pelo_endereco(endereco):
    if not endereco.strip():
        return None
    rua, _, numero = endereco.partition(",")
    q = urllib.parse.urlencode({
        "street": f"{numero.strip()} {rua.strip()}".strip(),
        "city": "São Paulo", "state": "SP", "country": "Brasil",
        "format": "jsonv2", "addressdetails": 1, "limit": 1,
    })
    try:
        res = pegar_json("https://nominatim.openstreetmap.org/search?" + q)
    except Exception as e:
        print("  nominatim falhou:", e)
        return None
    finally:
        time.sleep(1.1)  # regra do Nominatim: no máximo 1 pedido por segundo
    if not res:
        return None
    lat, lon = float(res[0]["lat"]), float(res[0]["lon"])
    if not dentro(lat, lon):
        return None
    precisao = "exato" if res[0].get("address", {}).get("house_number") else "rua"
    return lat, lon, precisao


def pelo_cep(cep):
    cep = "".join(c for c in cep if c.isdigit())
    if len(cep) != 8:
        return None
    # 1) coordenada do próprio CEP
    try:
        d = pegar_json(f"https://brasilapi.com.br/api/cep/v2/{cep}")
        co = (d.get("location") or {}).get("coordinates") or {}
        lat, lon = float(co["latitude"]), float(co["longitude"])
        if dentro(lat, lon) and not eh_centro_falso(lat, lon):
            return lat, lon, "cep"
    except Exception:
        pass
    finally:
        time.sleep(0.5)
    # 2) nome oficial da rua pelo CEP, procurado no OpenStreetMap
    try:
        d = pegar_json(f"https://viacep.com.br/ws/{cep}/json/")
        rua = d.get("logradouro", "")
    except Exception:
        rua = ""
    finally:
        time.sleep(0.5)
    achou = pelo_endereco(rua + ",") if rua else None
    return (achou[0], achou[1], "cep") if achou else None


def fora_do_mapa(farmacias):
    """SCPs e endereços-sede com muitas empresas não são farmácias de rua."""
    empresas = {}
    for f in farmacias:
        empresas.setdefault((f["endereco"], f["cep"]), set()).add(f["raiz"])
    sede = {k for k, v in empresas.items() if len(v) >= 10}
    return {f["cnpj"] for f in farmacias
            if " SCP" in f["fantasia"].upper() or (f["endereco"], f["cep"]) in sede}


def ler_cache():
    cache = {}
    if os.path.exists(CACHE):
        with open(CACHE, encoding="utf-8") as f:
            for r in csv.DictReader(f):
                cache[r["chave"]] = r
    return cache


def gravar_cache(cache):
    with open(CACHE, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["chave", "lat", "lon", "precisao"])
        w.writeheader()
        w.writerows(cache.values())


def main():
    with open(ENTRADA, encoding="utf-8") as f:
        farmacias = list(csv.DictReader(f))
    cache = ler_cache()
    for c in cache.values():               # desfaz os pontos falsos já gravados
        if c["lat"] and eh_centro_falso(float(c["lat"]), float(c["lon"])):
            c.update(lat="", lon="", precisao="nao_achou")
    chave = lambda f: f'{f["cnpj"]}|{f["endereco"]}|{f["cep"]}'
    excluir = fora_do_mapa(farmacias)
    print(f"{len(excluir)} registros fora do mapa (SCP ou sede com muitas empresas).")
    farmacias = [f for f in farmacias if f["cnpj"] not in excluir]
    novas = [f for f in farmacias if chave(f) not in cache
             or cache[chave(f)]["precisao"] == "nao_achou"]
    print(f"{len(farmacias)} farmácias; {len(novas)} para procurar agora.", flush=True)

    for i, f in enumerate(novas, 1):
        achou = pelo_endereco(f["endereco"]) or pelo_cep(f["cep"])
        lat, lon, prec = achou if achou else ("", "", "nao_achou")
        cache[chave(f)] = {"chave": chave(f), "lat": lat, "lon": lon, "precisao": prec}
        if i % SALVAR_A_CADA == 0:
            gravar_cache(cache)
            print(f"  {i}/{len(novas)} procuradas", flush=True)
    gravar_cache(cache)

    pontos, conta = [], {"exato": 0, "rua": 0, "cep": 0, "nao_achou": 0}
    for f in farmacias:
        c = cache[chave(f)]
        conta[c["precisao"]] += 1
        if c["precisao"] == "nao_achou":
            continue
        lojas = int(f["lojas_mesma_empresa"] or 1)
        pontos.append({
            "lat": round(float(c["lat"]), 6), "lon": round(float(c["lon"]), 6),
            "nome": f["fantasia"] or "Farmácia sem nome fantasia",
            "end": f["endereco"].title(), "bairro": f["bairro"].title(),
            "tipo": f["tipo"],
            "rede": f["tipo"] == "drogaria" and lojas >= LIMITE_REDE,
            "lojas": lojas, "precisao": c["precisao"],
        })
    with open(SAIDA, "w", encoding="utf-8") as f:
        json.dump({"atualizado": datetime.date.today().isoformat(), "farmacias": pontos},
                  f, ensure_ascii=False, separators=(",", ":"))

    print("\n===== RESUMO =====")
    print(f"No mapa: {len(pontos)} de {len(farmacias)}")
    for k, v in conta.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
