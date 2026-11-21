"""TESTE: quais redes deixam o robô ler o preço pelo site (plataforma VTEX)?
Rodar pelo botão "Teste preços das redes" na aba Actions do GitHub.
Não grava nada: só mostra o resultado na tela do GitHub.
Escolhidas pelas lojas que aparecem no mapa de São Paulo."""
import json
import time
import urllib.error
import urllib.parse
import urllib.request

CANDIDATAS = {
    "Farma Conde": ["https://www.farmaconde.com.br"],
    "Extrafarma": ["https://www.extrafarma.com.br"],
    "Panvel": ["https://www.panvel.com"],
    "Farmácias Nissei": ["https://www.farmaciasnissei.com.br"],
    # controle: esta já funciona no robô diário
    "Drogaria São Paulo (controle)": ["https://www.drogariasaopaulo.com.br"],
}
TERMOS = ["losartana 50mg", "dipirona 500mg", "omeprazol 20mg"]
PAUSA = 1.5


def ean_limpo(e):
    e = "".join(ch for ch in str(e or "") if ch.isdigit())
    return e[1:] if len(e) == 14 and e.startswith("0") else e


def pedir(url):
    pedido = urllib.request.Request(url, headers={
        "User-Agent": "MedicamentosBaratos-teste/0.2 (contato@medicamentosbaratos.com.br)",
        "Accept": "application/json"})
    with urllib.request.urlopen(pedido, timeout=30) as r:
        return json.load(r)


def main():
    cmed = json.load(open("precos.json", encoding="utf-8"))
    c = {n: i for i, n in enumerate(cmed["colunas"])}
    eans_cmed = {ean_limpo(l[c["ean"]]) for l in cmed["itens"] if l[c["ean"]]}

    resumo = []
    for rede, bases in CANDIDATAS.items():
        print(f"\n=== {rede}")
        achou = 0
        for base in bases:
            for termo in TERMOS:
                url = (f"{base}/api/catalog_system/pub/products/search"
                       f"?ft={urllib.parse.quote(termo)}&_from=0&_to=19")
                try:
                    produtos = pedir(url)
                except urllib.error.HTTPError as e:
                    print(f"  {termo}: bloqueado ou inexistente (HTTP {e.code})")
                    time.sleep(PAUSA)
                    continue
                except Exception as e:
                    print(f"  {termo}: sem resposta ({type(e).__name__})")
                    time.sleep(PAUSA)
                    continue
                if not isinstance(produtos, list):
                    print(f"  {termo}: respondeu, mas não no formato VTEX")
                    time.sleep(PAUSA)
                    continue
                casados = []
                for prod in produtos:
                    for item in prod.get("items", []):
                        ean = ean_limpo(item.get("ean"))
                        oferta = (item.get("sellers") or [{}])[0].get("commertialOffer", {})
                        if ean in eans_cmed and (oferta.get("Price") or 0) > 0:
                            casados.append((prod.get("productName", "")[:45], oferta["Price"]))
                achou += len(casados)
                exemplo = f" · ex.: {casados[0][0]} R$ {casados[0][1]:.2f}" if casados else ""
                print(f"  {termo}: {len(produtos)} produtos, {len(casados)} com código de barras da CMED{exemplo}")
                time.sleep(PAUSA)
        resumo.append((rede, achou))

    print("\n=== RESULTADO")
    for rede, n in resumo:
        print(f"  {'FUNCIONA' if n else 'não funciona'} · {rede} ({n} preços ligados à CMED)")


if __name__ == "__main__":
    main()
