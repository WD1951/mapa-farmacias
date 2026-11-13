"""Baixa a tabela de preços da CMED (dados abertos da Anvisa) e grava precos.json,
que a página busca.html lê. Roda sozinho todo dia 5 (robô cmed.yml).

Descarta uso hospitalar, produtos não comercializados e embalagens múltiplas."""
import csv
import io
import json
import re
import unicodedata
import urllib.request
import zipfile
from datetime import date

URL = "https://dados.anvisa.gov.br/dados/TA_PRECO_MEDICAMENTO.csv"

# São Paulo: genéricos 12%, demais medicamentos 18%
ALIQUOTA_GENERICO = "12"
ALIQUOTA_DEMAIS = "18"

UNIDADES_DOSE = r"MCG|MG|G|ML|UI|MEQ|%"
FORMAS = [("COM", "comprimido"), ("CAP", "cápsula"), ("DRG", "drágea"),
          ("SACHE", "sachê"), ("AMP", "ampola"), ("ENV", "envelope")]
FORMAS_APRESENTACAO = [
    ("INJ", "injetável"), ("EFEV", "efervescente"), ("GOT", "gotas"),
    ("XPE", "xarope"), ("SUS", "suspensão"), ("SUP", "supositório"),
    ("COM", "comprimido"), ("CAP", "cápsula"), ("DRG", "drágea"),
    ("SACHE", "sachê"), ("ENV", "sachê"), ("POM", "pomada"),
    ("CREM", "creme"), ("GEL", "gel"), ("SPR", "spray"), ("SOL", "solução"),
]


def normalizar(texto):
    texto = unicodedata.normalize("NFKD", str(texto)).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Z0-9]", "", texto.upper())


def baixar(url):
    pedido = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    dados = urllib.request.urlopen(pedido, timeout=180).read()
    if dados[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(dados)) as z:
            nome = next(n for n in z.namelist() if n.lower().endswith(".csv"))
            dados = z.read(nome)
    for codificacao in ("utf-8-sig", "latin-1"):
        try:
            return dados.decode(codificacao)
        except UnicodeDecodeError:
            continue


def achar_cabecalho(linhas):
    for i, linha in enumerate(linhas[:80]):
        n = normalizar(" ".join(linha))
        if "APRESENTACAO" in n and "PMC" in n:
            return i
    raise SystemExit("Não encontrei o cabeçalho da tabela (APRESENTACAO e PMC).")


def mapear(cabecalho):
    n = [normalizar(c) for c in cabecalho]

    def primeiro(teste):
        for i, c in enumerate(n):
            if teste(c):
                return i
        return None

    def ultimo(teste):
        achado = None
        for i, c in enumerate(n):
            if teste(c):
                achado = i
        return achado

    pmc = lambda aliq: primeiro(lambda c: re.search(rf"PMC\D*{aliq}(?!\d)", c) and "ALC" not in c)
    return {
        "substancia": primeiro(lambda c: "SUBSTANCIA" in c or "PRINCIPIO" in c),
        "produto": primeiro(lambda c: "PRODUTO" in c and not any(
            x in c for x in ("TIPO", "STATUS", "REGISTRO", "CODIGO"))),
        "apresentacao": primeiro(lambda c: "APRESENTACAO" in c),
        "laboratorio": primeiro(lambda c: "LABORATORIO" in c or "RAZAOSOCIAL" in c),
        "tipo": primeiro(lambda c: "TIPO" in c or "STATUS" in c),
        "pmc_gen": pmc(ALIQUOTA_GENERICO),
        "pmc_demais": pmc(ALIQUOTA_DEMAIS),
        "hospitalar": primeiro(lambda c: "RESTRICAOHOSPITALAR" in c),
        "comercializacao": ultimo(lambda c: c.startswith("COMERCIALIZACAO")),
    }


def preco(texto):
    t = str(texto).strip().replace("*", "")
    if not t:
        return None
    if "," in t:
        t = t.replace(".", "").replace(",", ".")
    try:
        valor = float(t)
    except ValueError:
        return None
    return round(valor, 2) if valor > 0 else None


def forma(apresentacao):
    a = apresentacao.upper()
    for sigla, nome in FORMAS_APRESENTACAO:
        if re.search(rf"\b{sigla}", a):
            return nome
    return "outra"


def quantidade(apresentacao):
    a = " " + apresentacao.upper().replace(",", ".") + " "
    fim = re.findall(r"X\s*(\d+(?:\.\d+)?)\s*(ML|G|L)?\b", a)
    if not fim:
        return None, None
    numero, medida = fim[-1]
    qtd = float(numero)
    mult = re.search(r"\bCT\s+(\d+)\s+(?:BL|STR|ENV|FR|FA|AMP|BG|SACHE|BS)", a)
    if mult:
        qtd *= int(mult.group(1))
    if medida == "L":
        return qtd * 1000, "ml"
    if medida:
        return qtd, medida.lower()
    for sigla, nome in FORMAS:
        if re.search(rf"\b{sigla}", a):
            return qtd, nome
    return qtd, "unidade"


def _numero(texto):
    return f"{float(texto.replace(',', '.')):g}"


def doses(apresentacao):
    a = apresentacao.upper().replace(",", ".")
    achados = set()
    for m in re.finditer(rf"(\d+(?:\.\d+)?)\s*({UNIDADES_DOSE})(?![A-Z])", a):
        inicio = m.start()
        if inicio > 0 and (a[inicio - 1].isdigit() or a[inicio - 1] == "."):
            continue
        if a[:inicio].rstrip().endswith("X"):
            continue
        achados.add(_numero(m.group(1)))
    return " " + " ".join(sorted(achados)) + " " if achados else ""


def main():
    texto = baixar(URL)
    amostra = texto[:5000]
    separador = ";" if amostra.count(";") > amostra.count(",") else ","
    linhas = list(csv.reader(io.StringIO(texto), delimiter=separador))
    i = achar_cabecalho(linhas)
    cabecalho = linhas[i]
    mapa = mapear(cabecalho)
    faltando = [k for k in ("substancia", "apresentacao", "pmc_gen", "pmc_demais") if mapa[k] is None]
    if faltando:
        raise SystemExit(f"Faltam colunas essenciais: {faltando}")

    def campo(linha, chave):
        pos = mapa[chave]
        return linha[pos].strip() if pos is not None and pos < len(linha) else ""

    itens = []
    for linha in linhas[i + 1:]:
        apres = campo(linha, "apresentacao")
        if not apres or "EMB MULT" in apres.upper():
            continue
        if normalizar(campo(linha, "hospitalar")) == "SIM":
            continue
        if normalizar(campo(linha, "comercializacao")) == "NAO":
            continue
        tipo = campo(linha, "tipo")
        generico = "GENERICO" in normalizar(tipo)
        pmc = preco(campo(linha, "pmc_gen" if generico else "pmc_demais"))
        qtd, unidade = quantidade(apres)
        por_unidade = round(pmc / qtd, 4) if pmc and qtd else None
        itens.append([campo(linha, "substancia"), campo(linha, "produto"), apres,
                      campo(linha, "laboratorio"), tipo, pmc, forma(apres),
                      unidade, por_unidade, doses(apres)])

    if len(itens) < 1000:
        raise SystemExit("Poucas linhas: a tabela pode ter mudado de formato. Mantido o arquivo anterior.")
    saida = {"atualizado": date.today().isoformat(),
             "colunas": ["substancia", "produto", "apresentacao", "laboratorio", "tipo",
                         "pmc", "forma", "unidade", "preco_unidade", "doses"],
             "itens": itens}
    with open("precos.json", "w", encoding="utf-8") as f:
        json.dump(saida, f, ensure_ascii=False, separators=(",", ":"))
    print(f"precos.json gravado com {len(itens)} apresentações.")


if __name__ == "__main__":
    main()
