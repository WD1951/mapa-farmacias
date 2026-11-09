import urllib.request, base64, re, zipfile, io, csv, os, collections, sys
TOKEN = "gn672Ad4CF8N6TK"
BASE = "https://arquivos.receitafederal.gov.br"
AUTH = "Basic " + base64.b64encode((TOKEN + ":").encode()).decode()
DAV = BASE + "/public.php/webdav/Dados/Cadastros/CNPJ/"

def pedir(url, metodo="GET", extra=None):
    h = {"Authorization": AUTH, "User-Agent": "mapa-farmacias"}
    if extra: h.update(extra)
    return urllib.request.urlopen(urllib.request.Request(url, method=metodo, headers=h), timeout=600)

# 1. descobrir a pasta mensal mais recente
lista = pedir(DAV, "PROPFIND", {"Depth": "1"}).read().decode("utf-8", "ignore")
pastas = sorted(set(re.findall(r"/(\d{4}-\d{2})/", lista)))
print("Pastas encontradas:", pastas[-5:])
if not pastas: sys.exit("Nenhuma pasta mensal encontrada")
mes = pastas[-1]
print("Usando a pasta", mes)

CNAE = {"4771701": "drogaria", "4771702": "manipulacao", "4771703": "homeopatia"}
linhas = []
for n in range(10):
    nome = f"Estabelecimentos{n}.zip"
    print("Baixando", nome, flush=True)
    try:
        with pedir(DAV + mes + "/" + nome) as r, open("tmp.zip", "wb") as f:
            while True:
                b = r.read(1 << 20)
                if not b: break
                f.write(b)
    except Exception as e:
        print("  falhou:", e); continue
    with zipfile.ZipFile("tmp.zip") as z:
        for interno in z.namelist():
            with z.open(interno) as bruto:
                for row in csv.reader(io.TextIOWrapper(bruto, encoding="latin-1"), delimiter=";"):
                    if len(row) < 21: continue
                    if row[20] != "7107" or row[5] != "02": continue
                    if row[11] not in CNAE: continue
                    linhas.append({
                        "cnpj": row[0] + row[1] + row[2], "raiz": row[0],
                        "fantasia": row[4].strip(), "tipo": CNAE[row[11]],
                        "endereco": " ".join(x for x in [row[13], row[14]] if x).strip() + (", " + row[15] if row[15] else ""),
                        "bairro": row[17].strip(), "cep": row[18], "inicio": row[10],
                    })
    os.remove("tmp.zip")
    print("  farmácias até agora:", len(linhas), flush=True)

if not linhas: sys.exit("Nada encontrado; mantendo arquivo anterior")
conta = collections.Counter(l["raiz"] for l in linhas)
for l in linhas: l["lojas_mesma_empresa"] = conta[l["raiz"]]
with open("farmacias_cnpj.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=list(linhas[0].keys()))
    w.writeheader(); w.writerows(linhas)
tipos = collections.Counter(l["tipo"] for l in linhas)
rede = sum(1 for l in linhas if l["tipo"] == "drogaria" and l["lojas_mesma_empresa"] >= 5)
print("==== RESUMO", mes, "====")
print("Total ativas na cidade:", len(linhas))
for t, q in tipos.items(): print(" ", t, q)
print("Drogarias de empresas com 5 ou mais lojas na cidade:", rede)
