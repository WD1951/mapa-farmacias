"""TESTE: o GitHub consegue ler o preço das redes pelo código de barras (EAN)?
Consulta uma cesta pequena na Drogaria São Paulo e na Pacheco (plataforma VTEX).
Não grava nada: só mostra o resultado na tela do GitHub."""
import json
import time
import urllib.error
import urllib.request

REDES = {
    "Drogaria São Paulo": "https://www.drogariasaopaulo.com.br",
    "Pacheco": "https://www.drogariaspacheco.com.br",
}
# Cesta de teste: (palavra da substância, dose, forma)
CESTA = [("dipirona", "500", "comprimido"), ("paracetamol", "750", "comprimido"),
         ("losartana", "50", "comprimido"), ("omeprazol", "20", "cápsula"),
         ("sinvastatina", "20", "comprimido"), ("metformina", "850", "comprimido"),
         ("ibuprofeno", "600", "comprimido"), ("enalapril", "10", "comprimido"),
         ("hidroclorotiazida", "25", "comprimido"), ("loratadina", "10", "comprimido")]
POR_ITEM = 3     # apresentações por item da cesta (as de menor preço-teto)


def reais(v):
    return ("R$ " + f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")) if v else "—"


def ean_limpo(e):
    e = e or ""
    return e[1:] if len(e) == 14 and e.startswith("0") else e


def escolher():
    d = json.load(open("precos.json", encoding="utf-8"))
    c = {n: i for i, n in enumerate(d["colunas"])}
    if "ean" not in c:
        raise SystemExit("precos.json ainda sem código de barras. Rode antes o robô 'Atualizar CMED'.")
    # Controle: produto que sabemos estar no site da Pacheco (dipirona Prati, 20 comprimidos)
    escolhidos = [{"ean": "7899547531206", "nome": "CONTROLE: DIPIRONA 500 MG PRATI X 20",
                   "lab": "PRATI DONADUZZI", "teto": None}]
    for sub, dose, forma in CESTA:
        cand = []
        for l in d["itens"]:
            pu, pmc = l[c["preco_unidade"]], l[c["pmc"]]
            if not (pu and pmc) or pmc / pu > 60:          # fora caixas de 100, 500…
                continue
            if (sub in l[c["substancia"]].lower() and ";" not in l[c["substancia"]]
                    and f" {dose} " in (l[c["doses"]] or "") and l[c["forma"]] == forma
                    and ean_limpo(l[c["ean"]]).startswith("789")):
                cand.append(l)
        cand.sort(key=lambda l: l[c["preco_unidade"]])
        labs = set()
        for l in cand:                                       # laboratórios diferentes
            if l[c["laboratorio"]] in labs:
                continue
            labs.add(l[c["laboratorio"]])
            escolhidos.append({"ean": ean_limpo(l[c["ean"]]), "nome": f"{l[c['produto']]} {l[c['apresentacao']]}",
                               "lab": l[c["laboratorio"]], "teto": l[c["pmc"]]})
            if len(labs) == POR_ITEM:
                break
    return escolhidos


def pedir(url):
    pedido = urllib.request.Request(url, headers={
        "User-Agent": "MedicamentosBaratos-teste/0.1 (contato@medicamentosbaratos.com.br)",
        "Accept": "application/json"})
    with urllib.request.urlopen(pedido, timeout=30) as r:
        return json.load(r)


def consultar(base, ean):
    caminhos = [f"/api/catalog_system/pub/products/search?fq=alternateIds_Ean:{ean}",
                f"/api/catalog_system/pub/products/search?ft={ean}"]
    dados = []
    for caminho in caminhos:
        try:
            dados = pedir(base + caminho)
        except urllib.error.HTTPError as e:
            return {"erro": f"HTTP {e.code}"}
        except Exception as e:
            return {"erro": type(e).__name__}
        if dados:
            break
    for prod in dados:
        for item in prod.get("items", []):
            if item.get("ean") in (ean, "0" + ean) or len(dados) == 1:
                oferta = (item.get("sellers") or [{}])[0].get("commertialOffer", {})
                return {"preco": oferta.get("Price"), "de": oferta.get("ListPrice"),
                        "estoque": oferta.get("AvailableQuantity", 0) > 0}
    return {"erro": "não encontrado"}


itens = escolher()
print(f"Cesta de teste: {len(itens)} apresentações, {len(REDES)} redes.\n")
placar = {r: {"preço": 0, "sem produto": 0, "bloqueio/erro": 0} for r in REDES}
for it in itens:
    print(it["nome"][:70])
    print(f"   {it['lab'][:40]} · teto CMED {reais(it['teto'])} · EAN {it['ean']}")
    for rede, base in REDES.items():
        r = consultar(base, it["ean"])
        if "erro" in r:
            chave = "sem produto" if r["erro"] == "não encontrado" else "bloqueio/erro"
            placar[rede][chave] += 1
            print(f"   {rede}: {r['erro']}")
        else:
            placar[rede]["preço"] += 1
            est = "" if r["estoque"] else " (esgotado no site)"
            print(f"   {rede}: {reais(r['preco'])} (de {reais(r['de'])}){est}")
        time.sleep(1.5)   # devagar, para não sobrecarregar os sites
    print()

print("RESUMO")
for rede, p in placar.items():
    print(f"   {rede}: {p['preço']} com preço, {p['sem produto']} sem o produto, {p['bloqueio/erro']} bloqueios ou erros")
