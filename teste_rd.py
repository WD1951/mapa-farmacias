# Teste: Drogasil e Raia deixam o robô ler os preços?
# Não grava nada no site. Só mostra o resultado no registro do GitHub.
import os
import requests

SITES = {
    "Drogasil": "https://www.drogasil.com.br/search?w={}",
    "Raia": "https://www.drogaraia.com.br/search?w={}",
}
TERMOS = ["losartana", "dipirona", "omeprazol"]

CABECALHO = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/124.0 Safari/537.36"),
    "Accept-Language": "pt-BR,pt;q=0.9",
}

SINAIS_BLOQUEIO = ["captcha", "cloudflare", "akamai", "access denied",
                   "acesso negado", "perimeterx", "blocked"]

os.makedirs("saida", exist_ok=True)

for nome, modelo in SITES.items():
    for termo in TERMOS:
        url = modelo.format(termo)
        try:
            r = requests.get(url, headers=CABECALHO, timeout=30)
            texto = r.text.lower()
            bloqueio = [s for s in SINAIS_BLOQUEIO if s in texto]
            print(f"\n== {nome} / {termo} ==")
            print(f"Código: {r.status_code}  Tamanho: {len(r.text)} letras")
            print(f"Tem 'R$': {'sim' if 'r$' in texto else 'não'}")
            print(f"Tem dados internos (__NEXT_DATA__): "
                  f"{'sim' if '__next_data__' in texto else 'não'}")
            print(f"Sinais de bloqueio: {bloqueio or 'nenhum'}")
            with open(f"saida/{nome}_{termo}.html", "w", encoding="utf-8") as f:
                f.write(r.text)
        except Exception as e:
            print(f"\n== {nome} / {termo} == ERRO: {e}")
