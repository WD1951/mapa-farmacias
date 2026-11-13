"""Robô diário: lê o preço dos remédios da cesta nos sites das redes (plataforma VTEX)
e grava precos_redes.json. A ligação com a CMED é feita pelo código de barras (EAN).
Roda todo dia de manhã (robô redes.yml)."""
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

REDES = {
    "Drogaria São Paulo": "https://www.drogariasaopaulo.com.br",
    "Pague Menos": "https://www.paguemenos.com.br",
}

# Cesta: como as pessoas procuram. Para incluir um remédio, acrescente uma linha.
CESTA = [
    "dipirona 500mg", "dipirona 1g", "paracetamol 500mg", "paracetamol 750mg",
    "ibuprofeno 400mg", "ibuprofeno 600mg", "nimesulida 100mg", "diclofenaco 50mg",
    "losartana 50mg", "losartana 100mg", "enalapril 10mg", "enalapril 20mg",
    "captopril 25mg", "hidroclorotiazida 25mg", "anlodipino 5mg", "anlodipino 10mg",
    "atenolol 25mg", "atenolol 50mg", "propranolol 40mg", "espironolactona 25mg",
    "furosemida 40mg", "metformina 500mg", "metformina 850mg", "glibenclamida 5mg",
    "gliclazida 30mg", "sinvastatina 20mg", "sinvastatina 40mg", "atorvastatina 20mg",
    "rosuvastatina 10mg", "omeprazol 20mg", "pantoprazol 40mg", "domperidona 10mg",
    "loratadina 10mg", "desloratadina 5mg", "cetirizina 10mg", "dexclorfeniramina 2mg",
    "levotiroxina 25mcg", "levotiroxina 50mcg", "acido acetilsalicilico 100mg",
    "clopidogrel 75mg", "fluoxetina 20mg", "sertralina 50mg", "escitalopram 10mg",
    "metoclopramida 10mg", "escopolamina 10mg", "prednisona 20mg", "dexametasona 4mg",
    "amoxicilina 500mg", "azitromicina 500mg", "cloridrato de ciclobenzaprina 5mg",
]
POR_PAGINA = 50
PAUSA = 1.2   # segundos entre consultas, para não sobrecarregar os sites


def ean_limpo(e):
    e = "".join(ch for ch in str(e or "") if ch.isdigit())
    return e[1:] if len(e) == 14 and e.startswith("0") else e


def pedir(url):
    pedido = urllib.request.Request(url, headers={
        "User-Agent": "MedicamentosBaratos/1.0 (contato@medicamentosbaratos.com.br)",
        "Accept": "application/json"})
    with urllib.request.urlopen(pedido, timeout=30) as r:
        return json.load(r)


def buscar(base, termo):
    url = (f"{base}/api/catalog_system/pub/products/search"
           f"?ft={urllib.parse.quote(termo)}&_from=0&_to={POR_PAGINA - 1}")
    return pedir(url)


def main():
    cmed = json.load(open("precos.json", encoding="utf-8"))
    c = {n: i for i, n in enumerate(cmed["colunas"])}
    if "ean" not in c:
        raise SystemExit("precos.json sem código de barras. Rode antes o robô 'Atualizar CMED'.")
    eans_cmed = {ean_limpo(l[c["ean"]]) for l in cmed["itens"] if l[c["ean"]]}

    precos = {}          # ean -> lista de [rede, preço, preço "de", tem estoque]
    placar = {r: {"precos": 0, "erros": 0} for r in REDES}
    for rede, base in REDES.items():
        for termo in CESTA:
            try:
                produtos = buscar(base, termo)
            except urllib.error.HTTPError as e:
                placar[rede]["erros"] += 1
                print(f"{rede} · {termo}: HTTP {e.code}")
                time.sleep(PAUSA)
                continue
            except Exception as e:
                placar[rede]["erros"] += 1
                print(f"{rede} · {termo}: {type(e).__name__}")
                time.sleep(PAUSA)
                continue
            for prod in produtos:
                for item in prod.get("items", []):
                    ean = ean_limpo(item.get("ean"))
                    if ean not in eans_cmed:
                        continue
                    oferta = (item.get("sellers") or [{}])[0].get("commertialOffer", {})
                    preco = oferta.get("Price") or 0
                    if preco <= 0:
                        continue
                    lista = precos.setdefault(ean, [])
                    if any(x[0] == rede for x in lista):
                        continue
                    lista.append([rede, round(preco, 2), round(oferta.get("ListPrice") or 0, 2),
                                  1 if (oferta.get("AvailableQuantity") or 0) > 0 else 0])
                    placar[rede]["precos"] += 1
            time.sleep(PAUSA)

    total = sum(p["precos"] for p in placar.values())
    if total < 20:
        raise SystemExit("Poucos preços encontrados; arquivo anterior mantido. Veja os erros acima.")
    agora = datetime.now(ZoneInfo("America/Sao_Paulo"))
    saida = {"atualizado": agora.strftime("%Y-%m-%dT%H:%M"),
             "campos": ["rede", "preco", "preco_de", "estoque"], "precos": precos}
    with open("precos_redes.json", "w", encoding="utf-8") as f:
        json.dump(saida, f, ensure_ascii=False, separators=(",", ":"))
    print(f"\nprecos_redes.json gravado: {len(precos)} apresentações com preço.")
    for rede, p in placar.items():
        print(f"   {rede}: {p['precos']} preços, {p['erros']} erros")


if __name__ == "__main__":
    main()
