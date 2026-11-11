"""
Farmácias da cidade de São Paulo a partir da base pública de CNPJ da Receita.

Lê os arquivos "Estabelecimentos" da Receita, um de cada vez, e guarda só
as farmácias ATIVAS com CNAE principal:
  4771-7/01  (sem manipulação)
  4771-7/02  (com manipulação)

De quebra, conta quantas lojas cada CNPJ tem no Brasil inteiro, para
separar REDE de INDEPENDENTE.

Resultado: dados/farmacias_sp.csv
"""
import csv
import io
import os
import re
import sys
import zipfile
import xml.etree.ElementTree as ET
from collections import Counter
from urllib.parse import unquote

import requests

TOKEN = "gn672Ad4CF8N6TK"  # link público da Receita (Nextcloud)
CAMINHO = "Dados/Cadastros/CNPJ"
ACESSOS = [
    (f"https://arquivos.receitafederal.gov.br/public.php/webdav/{CAMINHO}", (TOKEN, "")),
    (f"https://arquivos.receitafederal.gov.br/public.php/dav/files/{TOKEN}/{CAMINHO}", None),
]

CNAES = {"4771701": "sem manipulação", "4771702": "com manipulação"}
MUNICIPIO_SP = "7107"   # código da Receita para a cidade de São Paulo
LIMITE_REDE = 5         # 5 lojas ou mais no Brasil = rede
SAIDA = "dados/farmacias_sp.csv"


def listar(url, auth):
    r = requests.request("PROPFIND", url + "/", auth=auth,
                         headers={"Depth": "1"}, timeout=60)
    r.raise_for_status()
    ns = {"d": "DAV:"}
    nomes = []
    for resp in ET.fromstring(r.content).findall("d:response", ns):
        href = resp.find("d:href", ns).text.rstrip("/")
        nomes.append(unquote(href.split("/")[-1]))
    return nomes


def achar_pasta_mais_recente():
    for url, auth in ACESSOS:
        try:
            pastas = sorted(n for n in listar(url, auth)
                            if re.fullmatch(r"\d{4}-\d{2}", n))
            if pastas:
                print(f"Base da Receita encontrada. Mês mais recente: {pastas[-1]}")
                return url, auth, pastas[-1]
        except Exception as erro:
            print(f"Tentativa falhou em {url}: {erro}")
    sys.exit("ERRO: não consegui acessar a base da Receita. Mande este log.")


def baixar(url, auth, destino):
    with requests.get(url, auth=auth, stream=True, timeout=300) as r:
        r.raise_for_status()
        with open(destino, "wb") as f:
            for bloco in r.iter_content(1 << 20):
                f.write(bloco)


def processar_zip(caminho, lojas, farmacias_sp):
    with zipfile.ZipFile(caminho) as z:
        for nome in z.namelist():
            with z.open(nome) as bruto:
                texto = io.TextIOWrapper(bruto, encoding="latin-1", newline="")
                for c in csv.reader(texto, delimiter=";", quotechar='"'):
                    if len(c) < 21 or c[11] not in CNAES:
                        continue
                    if not c[5].strip().isdigit() or int(c[5]) != 2:  # 2 = ativa
                        continue
                    lojas[c[0]] += 1
                    if c[19] == "SP" and c[20] == MUNICIPIO_SP:
                        farmacias_sp.append(c)


def main():
    url, auth, mes = achar_pasta_mais_recente()
    lojas = Counter()
    farmacias_sp = []

    for i in range(10):
        arquivo = f"Estabelecimentos{i}.zip"
        print(f"Baixando {arquivo} ...", flush=True)
        try:
            baixar(f"{url}/{mes}/{arquivo}", auth, arquivo)
        except Exception as erro:
            sys.exit(f"ERRO ao baixar {arquivo}: {erro}")
        processar_zip(arquivo, lojas, farmacias_sp)
        os.remove(arquivo)
        print(f"  farmácias de SP até agora: {len(farmacias_sp)}", flush=True)

    os.makedirs("dados", exist_ok=True)
    with open(SAIDA, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["cnpj", "nome_fantasia", "tipo", "lojas_no_brasil",
                    "classificacao", "endereco", "complemento", "bairro",
                    "cep", "telefone", "inicio_atividade", "base_receita"])
        for c in farmacias_sp:
            n = lojas[c[0]]
            endereco = " ".join(p for p in (c[13], c[14], c[15]) if p.strip())
            telefone = f"({c[21]}) {c[22]}" if len(c) > 22 and c[22].strip() else ""
            w.writerow([c[0] + c[1] + c[2], c[4].strip(), CNAES[c[11]], n,
                        "rede" if n >= LIMITE_REDE else "independente",
                        endereco, c[16].strip(), c[17].strip(), c[18],
                        telefone, c[10], mes])

    redes = sum(1 for c in farmacias_sp if lojas[c[0]] >= LIMITE_REDE)
    print("\n===== RESUMO =====")
    print(f"Farmácias ativas na cidade de SP: {len(farmacias_sp)}")
    print(f"  de rede:        {redes}")
    print(f"  independentes:  {len(farmacias_sp) - redes}")
    print(f"Arquivo salvo: {SAIDA}")


if __name__ == "__main__":
    main()
