"""
Transforma os endereços do farmacias_cnpj.csv (Receita) em pontos no mapa.

Para cada farmácia:
  1. procura o endereço com número no OpenStreetMap (Nominatim)  -> "exato" ou "rua"
  2. se não achar, usa o CEP: coordenada do CEP (BrasilAPI) ou o nome
     oficial da rua pelo CEP (ViaCEP) procurado no OpenStreetMap  -> "cep"

Conferência: todo ponto precisa cair perto do próprio bairro (ou da região
do CEP), medido pelas outras farmácias do mesmo bairro, e dentro do
município de São Paulo. Ponto que não passa é procurado de novo; se nada
passar, a farmácia fica fora do mapa. Melhor faltar do que mentir.

Ficam de fora do mapa: SCPs (sociedades de investimento, não lojas) e
endereços com 10 ou mais empresas diferentes (sede fiscal, não farmácia).
As que não foram achadas são procuradas de novo a cada rodada.

Tem memória (enderecos_cache.csv): só procura o que é novo ou mudou de
endereço. A primeira rodada é longa (cerca de 2 horas); as mensais, curtas.

Resultado: farmacias_receita.json, que o mapa vai ler.
"""
import csv, json, os, sys, time, math, statistics, unicodedata, urllib.request, urllib.parse, datetime

ENTRADA = "farmacias_cnpj.csv"
CACHE = "enderecos_cache.csv"
SAIDA = "farmacias_receita.json"
UA = {"User-Agent": "mapa-farmacias (github.com/WD1951/mapa-farmacias)"}
CAIXA = (-24.01, -46.83, -23.35, -46.36)   # cidade de São Paulo
LIMITE_REDE = 5

# Nome que o público conhece, para lojas que vieram sem nome fantasia.
# Chave: razão social como aparece no farmacias_cnpj.csv. Pode acrescentar linhas.
MARCAS = {
    "IMIFARMA PRODUTOS FARMACEUTICOS E COSMETICOS": "EXTRAFARMA",
    "DIMED S/A - DISTRIBUIDORA DE MEDICAMENTOS": "PANVEL",
    "EMPREENDIMENTOS PAGUE MENOS": "PAGUE MENOS",
    "ORGANIZACAO FARMACEUTICA NAKANO": "PROMOFARMA",
    "CARREFOUR COMERCIO E INDUSTRIA": "DROGARIA CARREFOUR",
    "SENDAS DISTRIBUIDORA": "FARMACIA ASSAI",
    "DROGA RAPHAEL SANSANA": "DROGA LESTE",
}
SALVAR_A_CADA = 100


CENTRO_FALSO = (-23.5475, -46.63611)      # "centro da cidade" que o serviço de CEP
                                          # devolve quando não sabe a coordenada


def eh_centro_falso(lat, lon):
    return abs(lat - CENTRO_FALSO[0]) < 0.001 and abs(lon - CENTRO_FALSO[1]) < 0.001


def km(a, b, c, d):
    p = math.radians
    h = math.sin(p(c - a) / 2) ** 2 + math.cos(p(a)) * math.cos(p(c)) * math.sin(p(d - b) / 2) ** 2
    return 12742 * math.asin(math.sqrt(h))


def normal(t):
    t = unicodedata.normalize("NFKD", t or "").encode("ascii", "ignore").decode()
    return " ".join(t.upper().split())


def digitos(t):
    return "".join(c for c in (t or "") if c.isdigit())


class Referencia:
    """Centro típico de cada bairro e de cada região de CEP, tirado da mediana
    das farmácias já localizadas. A mediana não se deixa levar por alguns
    pontos errados."""
    # (mínimo de farmácias para confiar no centro, distância máxima aceita em km)
    REGRAS = {"bairro": (4, 4.0), "cep5": (3, 3.0), "cep3": (5, 8.0)}

    def __init__(self, farmacias, cache, chave):
        grupos = {}
        for f in farmacias:
            c = cache.get(chave(f))
            if not c or not c["lat"]:
                continue
            ponto = (float(c["lat"]), float(c["lon"]))
            for tipo, k in self.chaves(f).items():
                grupos.setdefault((tipo, k), []).append(ponto)
        self.centro = {}
        for (tipo, k), pts in grupos.items():
            if k and len(pts) >= self.REGRAS[tipo][0]:
                self.centro[(tipo, k)] = (statistics.median(x for x, _ in pts),
                                          statistics.median(y for _, y in pts))

    @staticmethod
    def chaves(f):
        cep = digitos(f["cep"])
        return {"bairro": normal(f["bairro"]), "cep5": cep[:5] if len(cep) == 8 else "",
                "cep3": cep[:3] if len(cep) == 8 else ""}

    def confere(self, f, lat, lon):
        """True se o ponto está perto de onde a farmácia deveria estar.
        Sem referência nenhuma, aceita (não há com o que comparar)."""
        for tipo, k in self.chaves(f).items():
            centro = self.centro.get((tipo, k))
            if centro:
                return km(lat, lon, *centro) <= self.REGRAS[tipo][1]
        return True


def no_municipio(endereco_osm):
    """O OpenStreetMap diz em que cidade o ponto está; tem de ser São Paulo."""
    cidade = (endereco_osm.get("city") or endereco_osm.get("town")
              or endereco_osm.get("municipality") or "")
    return not cidade or normal(cidade) == "SAO PAULO"


def dentro(lat, lon):
    return CAIXA[0] <= lat <= CAIXA[2] and CAIXA[1] <= lon <= CAIXA[3]


def pegar_json(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def pelo_endereco(endereco, ok, bairro=""):
    """Procura o endereço e devolve o primeiro resultado que passar em ok(lat, lon).
    Com bairro, faz uma busca livre incluindo o bairro."""
    if not endereco.strip():
        return None
    rua, _, numero = endereco.partition(",")
    if bairro:
        campos = {"q": f"{rua.strip()} {numero.strip()}, {bairro}, São Paulo, SP, Brasil"}
    else:
        campos = {"street": f"{numero.strip()} {rua.strip()}".strip(),
                  "city": "São Paulo", "state": "SP", "country": "Brasil"}
    q = urllib.parse.urlencode({**campos, "format": "jsonv2", "addressdetails": 1, "limit": 5})
    try:
        res = pegar_json("https://nominatim.openstreetmap.org/search?" + q)
    except Exception as e:
        print("  nominatim falhou:", e)
        return None
    finally:
        time.sleep(1.1)  # regra do Nominatim: no máximo 1 pedido por segundo
    for r in res or []:
        lat, lon = float(r["lat"]), float(r["lon"])
        endereco_osm = r.get("address", {})
        if dentro(lat, lon) and no_municipio(endereco_osm) and ok(lat, lon):
            return lat, lon, ("exato" if endereco_osm.get("house_number") else "rua")
    return None


def pelo_cep(cep, ok):
    cep = "".join(c for c in cep if c.isdigit())
    if len(cep) != 8:
        return None
    # 1) coordenada do próprio CEP
    try:
        d = pegar_json(f"https://brasilapi.com.br/api/cep/v2/{cep}")
        co = (d.get("location") or {}).get("coordinates") or {}
        lat, lon = float(co["latitude"]), float(co["longitude"])
        if dentro(lat, lon) and not eh_centro_falso(lat, lon) and ok(lat, lon):
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
    achou = pelo_endereco(rua + ",", ok) if rua else None
    return (achou[0], achou[1], "cep") if achou else None


def fora_do_mapa(farmacias):
    """SCPs e endereços-sede com muitas empresas não são farmácias de rua."""
    empresas = {}
    for f in farmacias:
        empresas.setdefault((f["endereco"], f["cep"]), set()).add(f["raiz"])
    sede = {k for k, v in empresas.items() if len(v) >= 10}
    return {f["cnpj"] for f in farmacias
            if " SCP" in (f["fantasia"] + " " + f.get("razao", "")).upper() or (f["endereco"], f["cep"]) in sede}


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
    ref = Referencia(farmacias, cache, chave)
    refeitas = 0
    for f in farmacias:                   # confere os pontos já guardados
        c = cache.get(chave(f))
        if c and c["lat"] and not ref.confere(f, float(c["lat"]), float(c["lon"])):
            c.update(lat="", lon="", precisao="nao_achou")
            refeitas += 1
    print(f"{refeitas} pontos guardados estavam longe do próprio bairro; serão procurados de novo.")
    novas = [f for f in farmacias if chave(f) not in cache
             or cache[chave(f)]["precisao"] == "nao_achou"]
    print(f"{len(farmacias)} farmácias; {len(novas)} para procurar agora.", flush=True)

    for i, f in enumerate(novas, 1):
        ok = lambda lat, lon, f=f: ref.confere(f, lat, lon)
        achou = (pelo_endereco(f["endereco"], ok)
                 or pelo_endereco(f["endereco"], ok, bairro=f["bairro"].title())
                 or pelo_cep(f["cep"], ok))
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
            "nome": f["fantasia"] or MARCAS.get(f.get("razao", "")) or f.get("razao") or "Farmácia sem nome",
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
    print(f"Refeitas por estarem longe do bairro: {refeitas}")
    for k, v in conta.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
