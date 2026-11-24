"""Catálogo público: o estoque da loja num link para mandar ao cliente.

Pedido do Atalaia (cadastro manual que "gere um link de catálogo", ver
`docs/analise-concorrente-carmillion.md`). `/c/{slug}` lista os carros à venda
e `/c/{slug}/{id}` é a ficha de um carro, com o botão que abre o WhatsApp da
loja já com a mensagem "Tenho interesse no …".

Decisões:

  - **A página é montada no servidor, não no app React.** O uso principal é o
    vendedor mandar o link de um carro no WhatsApp, e a prévia que o WhatsApp
    desenha (foto, nome, preço) sai das tags `og:` do HTML que o servidor
    devolve: o WhatsApp não executa JavaScript, então com o app todo link
    mostraria a mesma prévia genérica. De quebra, quem abre o catálogo não
    baixa o CRM inteiro. O Caddy manda `/c/*` para o backend.
  - **Só o que é do anúncio.** Carro vendido não aparece (o link antigo de um
    vendido abre "esse já foi vendido" com o caminho para os outros); reservado
    aparece marcado. Placa, localização no pátio e quem cadastrou nunca saem.
  - **A foto pública passa por aqui**, não por `/api/media`, que exige login:
    só é servida se for de um carro à venda de um catálogo ligado. Desligar o
    catálogo ou vender o carro tira as fotos do ar junto.
  - **Sem JavaScript.** Busca e filtro são um `<form method=get>`, a galeria é
    rolagem com `scroll-snap`. Página que funciona em qualquer celular, rápida
    em 3G, e que não tem o que quebrar.
  - Nada de "ZappZen" nem da marca do revendedor: a página é da loja.
"""
import html
import re
import unicodedata
from urllib.parse import quote

SLUG_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{1,38}[a-z0-9])$")
RESERVADOS = {"api", "app", "admin", "login", "static", "c", "www"}
A_VENDA = ["disponivel", "reservado"]
TEXTO_WHATSAPP_PADRAO = "Olá! Tenho interesse no {carro} que vi no catálogo: {link}"

ROTULOS = {
    "cambio": {"manual": "Manual", "automatico": "Automático", "cvt": "CVT", "automatizado": "Automatizado"},
    "combustivel": {"flex": "Flex", "gasolina": "Gasolina", "etanol": "Etanol", "diesel": "Diesel",
                    "hibrido": "Híbrido", "eletrico": "Elétrico", "gnv": "GNV"},
    "categoria": {"hatch": "Hatch", "sedan": "Sedã", "suv": "SUV", "picape": "Picape",
                  "minivan": "Minivan", "esportivo": "Esportivo", "utilitario": "Utilitário", "moto": "Moto"},
    "condicao": {"novo": "Novo", "seminovo": "Seminovo", "usado": "Usado"},
}

ORDENS = {"recentes": "Mais recentes", "menor": "Menor preço", "maior": "Maior preço", "km": "Menor km"}


def sugerir_slug(nome: str) -> str:
    s = "".join(c for c in unicodedata.normalize("NFD", nome or "") if unicodedata.category(c) != "Mn")
    s = re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:40].strip("-")
    return s if len(s) >= 3 else (s + "-loja").strip("-")


def slug_valido(slug: str) -> bool:
    return bool(SLUG_RE.match(slug or "")) and slug not in RESERVADOS


def so_digitos(s: str | None) -> str:
    return "".join(c for c in (s or "") if c.isdigit())


def _e(v) -> str:
    return html.escape(str(v if v is not None else ""), quote=True)


def _sem_acento(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", str(s or ""))
                   if unicodedata.category(c) != "Mn").lower()


def reais(n) -> str:
    return "R$ " + f"{float(n):,.0f}".replace(",", ".")


def nome_carro(v: dict) -> str:
    return " ".join(p for p in (v.get("marca"), v.get("modelo")) if p)


def ano(v: dict) -> str:
    f, m = v.get("ano_fabricacao"), v.get("ano_modelo")
    if f and m and f != m:
        return f"{f}/{m}"
    return str(m or f or "")


def km(v: dict) -> str:
    return f"{v['km']:,} km".replace(",", ".") if v.get("km") is not None else ""


def filtrar(veiculos: list[dict], q: str = "", categoria: str = "", ordem: str = "recentes") -> list[dict]:
    termos = _sem_acento(q).split()
    if termos:
        def alvo(v):
            return _sem_acento(" ".join(str(v.get(c) or "") for c in
                                        ("marca", "modelo", "versao", "cor", "ano_modelo", "ano_fabricacao"))
                               + " " + ROTULOS["categoria"].get(v.get("categoria") or "", ""))
        veiculos = [v for v in veiculos if all(t in alvo(v) for t in termos)]
    if categoria:
        veiculos = [v for v in veiculos if v.get("categoria") == categoria]
    if ordem == "menor":
        veiculos.sort(key=lambda v: (not v.get("preco"), v.get("preco") or 0))
    elif ordem == "maior":
        veiculos.sort(key=lambda v: -(v.get("preco") or 0))
    elif ordem == "km":
        veiculos.sort(key=lambda v: (v.get("km") is None, v.get("km") or 0))
    else:
        veiculos.sort(key=lambda v: v.get("entrada_em") or "", reverse=True)
        veiculos.sort(key=lambda v: not v.get("destaque"))
    # Reservado vai para o fim: ainda aparece, mas não é o que se oferece primeiro.
    veiculos.sort(key=lambda v: v.get("status") == "reservado")
    return veiculos


def link_whatsapp(cfg: dict, v: dict | None, link: str) -> str | None:
    numero = so_digitos(cfg.get("whatsapp"))
    if not numero:
        return None
    if v:
        texto = (cfg.get("texto_whatsapp") or TEXTO_WHATSAPP_PADRAO)
        carro = " ".join(p for p in (nome_carro(v), v.get("versao"), ano(v)) if p)
        texto = texto.replace("{carro}", carro).replace("{link}", link)
    else:
        texto = f"Olá! Vi o catálogo da {cfg.get('nome') or 'loja'} e queria mais informações."
    return f"https://wa.me/{numero}?text={quote(texto)}"


# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------

CSS = """
:root{--bg:#f6f6f4;--card:#fff;--ink:#16181d;--ink2:#4b5160;--ink3:#737a89;--line:#e6e6e1;
--brand:#16181d;--ok:#1f8f4e;--okfg:#fff;--warn:#8a6206;--warnbg:#fbf3dc;--r:16px}
@media (prefers-color-scheme:dark){:root{--bg:#111316;--card:#1a1d22;--ink:#f1f2f4;--ink2:#c3c7cf;
--ink3:#9097a3;--line:#2a2e35;--brand:#f1f2f4;--ok:#25a65c;--warn:#f2c14e;--warnbg:#2d2614}}
*{box-sizing:border-box}html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.45 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
a{color:inherit;text-decoration:none}img{display:block;max-width:100%}
.wrap{max-width:1180px;margin:0 auto;padding:0 16px}
header.top{background:var(--card);border-bottom:1px solid var(--line)}
header.top .wrap{display:flex;align-items:center;justify-content:space-between;gap:12px;padding-top:16px;padding-bottom:16px}
.loja{font-weight:750;font-size:20px;letter-spacing:-.01em}.sub{color:var(--ink3);font-size:13px}
.btn{display:inline-flex;align-items:center;justify-content:center;gap:8px;border-radius:12px;padding:11px 16px;
font-weight:650;font-size:14px;border:1px solid var(--line);background:var(--card);cursor:pointer;color:var(--ink)}
.btn-wa{background:var(--ok);border-color:var(--ok);color:var(--okfg)}
form.filtros{display:flex;flex-wrap:wrap;gap:8px;margin:20px 0 6px}
form.filtros input,form.filtros select{flex:1 1 160px;min-width:0;border:1px solid var(--line);background:var(--card);
color:var(--ink);border-radius:12px;padding:11px 12px;font:inherit}
form.filtros input{flex-basis:240px}
.qtd{color:var(--ink3);font-size:13px;margin:10px 0 14px}
.grade{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:16px;padding-bottom:40px}
.card{background:var(--card);border:1px solid var(--line);border-radius:var(--r);overflow:hidden;display:flex;flex-direction:column}
.foto{aspect-ratio:4/3;background:var(--line);position:relative;overflow:hidden}
.foto img{width:100%;height:100%;object-fit:cover}
.sem-foto{width:100%;height:100%;display:flex;align-items:center;justify-content:center;color:var(--ink3);font-size:13px}
.selo{position:absolute;top:10px;left:10px;background:var(--warnbg);color:var(--warn);font-size:11px;font-weight:700;
padding:4px 8px;border-radius:999px;text-transform:uppercase;letter-spacing:.04em}
.selo.dest{background:var(--card);color:var(--ink)}
.info{padding:14px 16px 16px;display:flex;flex-direction:column;gap:4px;flex:1}
.nome{font-weight:700;font-size:16px}.versao{color:var(--ink2);font-size:13px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.meta{color:var(--ink3);font-size:13px}.preco{font-weight:750;font-size:20px;margin-top:auto;padding-top:8px;font-variant-numeric:tabular-nums}
.de{color:var(--ink3);font-size:12px;text-decoration:line-through;font-weight:500}
.vazio{text-align:center;color:var(--ink3);padding:60px 0}
.ficha{display:grid;grid-template-columns:1fr;gap:24px;padding:20px 0 110px}
@media (min-width:900px){.ficha{grid-template-columns:1.35fr 1fr;padding-bottom:48px}}
.galeria{display:flex;overflow-x:auto;scroll-snap-type:x mandatory;border-radius:var(--r);gap:8px;scrollbar-width:thin}
.galeria img{flex:0 0 100%;aspect-ratio:4/3;object-fit:cover;scroll-snap-align:start;border-radius:var(--r);background:var(--line)}
.dica{color:var(--ink3);font-size:12px;margin-top:6px}
.painel{background:var(--card);border:1px solid var(--line);border-radius:var(--r);padding:20px}
.painel h1{font-size:26px;line-height:1.15;margin:0 0 4px;letter-spacing:-.01em}
.grande{font-size:32px;font-weight:800;margin:14px 0 4px;font-variant-numeric:tabular-nums}
dl{display:grid;grid-template-columns:repeat(2,1fr);gap:14px 16px;margin:18px 0;padding:16px 0;border-top:1px solid var(--line);border-bottom:1px solid var(--line)}
dt{color:var(--ink3);font-size:11px;text-transform:uppercase;letter-spacing:.05em}dd{margin:2px 0 0;font-weight:600}
.tags{display:flex;flex-wrap:wrap;gap:6px}.tag{background:var(--bg);border:1px solid var(--line);border-radius:8px;padding:4px 9px;font-size:13px}
h2{font-size:13px;text-transform:uppercase;letter-spacing:.06em;color:var(--ink3);margin:20px 0 8px}
.desc{white-space:pre-line;color:var(--ink2)}
.voltar{display:inline-block;margin-top:18px;color:var(--ink2);font-size:14px}
.barra{position:fixed;left:0;right:0;bottom:0;background:var(--card);border-top:1px solid var(--line);padding:12px 16px calc(12px + env(safe-area-inset-bottom))}
.barra .btn{width:100%}
@media (min-width:900px){.barra{position:static;background:none;border:0;padding:0;margin-top:18px}}
footer{color:var(--ink3);font-size:12px;text-align:center;padding:24px 0 32px}
"""


def _pagina(titulo: str, corpo: str, og: dict) -> str:
    metas = "".join(
        f'<meta property="og:{k}" content="{_e(v)}">' for k, v in og.items() if v)
    descricao = og.get("description") or ""
    return (
        "<!doctype html><html lang=\"pt-BR\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1,viewport-fit=cover\">"
        f"<title>{_e(titulo)}</title><meta name=\"description\" content=\"{_e(descricao)}\">"
        f"{metas}<meta name=\"twitter:card\" content=\"summary_large_image\">"
        "<meta name=\"robots\" content=\"noindex\">"
        f"<style>{CSS}</style></head><body>{corpo}</body></html>"
    )


def _cabecalho(cfg: dict, base: str, wa: str | None) -> str:
    sub = f'<div class="sub">{_e(cfg["endereco"])}</div>' if cfg.get("endereco") else ""
    botao = f'<a class="btn btn-wa" href="{_e(wa)}" rel="noopener">WhatsApp</a>' if wa else ""
    return (f'<header class="top"><div class="wrap"><a href="{_e(base)}"><div class="loja">'
            f'{_e(cfg.get("nome") or "Catálogo")}</div>{sub}</a>{botao}</div></header>')


def _foto_url(base: str, media_id: str) -> str:
    return f"{base}/foto/{quote(media_id)}"


def _preco_html(cfg: dict, v: dict, classe: str) -> str:
    if not cfg.get("mostrar_preco", True) or not v.get("preco"):
        return f'<div class="{classe}">Consulte</div>'
    de = ""
    if v.get("preco_anterior") and v["preco_anterior"] > v["preco"]:
        de = f'<span class="de">{reais(v["preco_anterior"])}</span> '
    return f'<div class="{classe}">{de}{reais(v["preco"])}</div>'


def pagina_lista(cfg: dict, veiculos: list[dict], base: str, total: int,
                 q: str = "", categoria: str = "", ordem: str = "recentes",
                 categorias: list[str] | None = None) -> str:
    wa = link_whatsapp(cfg, None, base)
    cats = "".join(
        f'<option value="{_e(c)}"{" selected" if c == categoria else ""}>{_e(ROTULOS["categoria"].get(c, c))}</option>'
        for c in (categorias or []))
    ords = "".join(f'<option value="{k}"{" selected" if k == ordem else ""}>{r}</option>'
                   for k, r in ORDENS.items())
    filtros = (
        f'<form class="filtros" method="get" action="{_e(base)}">'
        f'<input type="search" name="q" value="{_e(q)}" placeholder="Buscar marca, modelo, ano…" aria-label="Buscar">'
        + (f'<select name="categoria" aria-label="Categoria"><option value="">Todas as categorias</option>{cats}</select>'
           if categorias else "")
        + f'<select name="ordem" aria-label="Ordenar">{ords}</select>'
        '<button class="btn" type="submit">Filtrar</button></form>')
    cards = []
    for v in veiculos:
        fotos = v.get("fotos") or []
        img = (f'<img src="{_e(_foto_url(base, fotos[0]))}" alt="{_e(nome_carro(v))}" loading="lazy">'
               if fotos else '<div class="sem-foto">Foto em breve</div>')
        selo = ('<span class="selo">Reservado</span>' if v.get("status") == "reservado"
                else '<span class="selo dest">Destaque</span>' if v.get("destaque") else "")
        meta = " · ".join(p for p in (ano(v), km(v)) if p)
        cards.append(
            f'<a class="card" href="{_e(base)}/{_e(v["id"])}"><div class="foto">{img}{selo}</div>'
            f'<div class="info"><div class="nome">{_e(nome_carro(v))}</div>'
            + (f'<div class="versao">{_e(v["versao"])}</div>' if v.get("versao") else "")
            + (f'<div class="meta">{_e(meta)}</div>' if meta else "")
            + _preco_html(cfg, v, "preco") + "</div></a>")
    filtrando = bool(q or categoria)
    qtd = (f"{len(veiculos)} de {total} veículos" if filtrando
           else f"{total} veículo{'s' if total != 1 else ''} disponíve{'is' if total != 1 else 'l'}")
    lista = (f'<div class="grade">{"".join(cards)}</div>' if cards else
             '<div class="vazio">Nenhum veículo encontrado'
             + (f' — <a href="{_e(base)}"><u>ver todos</u></a>' if filtrando else "") + "</div>")
    corpo = (_cabecalho(cfg, base, wa)
             + f'<main class="wrap">{filtros}<div class="qtd">{qtd}</div>{lista}</main>'
             + f'<footer>{_e(cfg.get("nome") or "")}</footer>')
    primeira = next((v["fotos"][0] for v in veiculos if v.get("fotos")), None)
    og = {"title": f"Estoque {cfg.get('nome') or ''}".strip(), "type": "website", "url": base,
          "description": f"{total} veículos à venda. Veja fotos, preços e fale com a gente no WhatsApp.",
          "image": _foto_url(base, primeira) if primeira else None}
    return _pagina(og["title"], corpo, og)


def pagina_veiculo(cfg: dict, v: dict, base: str) -> str:
    link = f"{base}/{v['id']}"
    wa = link_whatsapp(cfg, v, link)
    fotos = v.get("fotos") or []
    galeria = (
        '<div><div class="galeria">' + "".join(
            f'<img src="{_e(_foto_url(base, m))}" alt="{_e(nome_carro(v))} — foto {i + 1}"'
            f'{" loading=lazy" if i else ""}>' for i, m in enumerate(fotos)) + "</div>"
        + (f'<div class="dica">{len(fotos)} fotos · arraste para o lado</div>' if len(fotos) > 1 else "")
        + "</div>") if fotos else '<div class="foto" style="border-radius:16px"><div class="sem-foto">Foto em breve</div></div>'
    specs = [("Ano", ano(v)), ("Quilometragem", km(v)),
             ("Câmbio", ROTULOS["cambio"].get(v.get("cambio") or "", "")),
             ("Combustível", ROTULOS["combustivel"].get(v.get("combustivel") or "", "")),
             ("Motor", v.get("motor")), ("Portas", v.get("portas")),
             ("Cor", v.get("cor")), ("Categoria", ROTULOS["categoria"].get(v.get("categoria") or "", "")),
             ("Condição", ROTULOS["condicao"].get(v.get("condicao") or "", ""))]
    dl = "".join(f"<div><dt>{k}</dt><dd>{_e(val)}</dd></div>" for k, val in specs if val)
    opc = ("<h2>Opcionais</h2><div class=\"tags\">"
           + "".join(f'<span class="tag">{_e(o)}</span>' for o in v["opcionais"]) + "</div>"
           if v.get("opcionais") else "")
    desc = f'<h2>Sobre o veículo</h2><div class="desc">{_e(v["observacoes"])}</div>' if v.get("observacoes") else ""
    reservado = ('<div class="selo" style="position:static;display:inline-block;margin-bottom:10px">'
                 'Reservado</div>' if v.get("status") == "reservado" else "")
    botao = (f'<div class="barra"><a class="btn btn-wa" href="{_e(wa)}" rel="noopener">'
             'Tenho interesse — chamar no WhatsApp</a></div>' if wa else "")
    painel = (
        f'<div><div class="painel">{reservado}<h1>{_e(nome_carro(v))}</h1>'
        + (f'<div class="versao" style="white-space:normal">{_e(v["versao"])}</div>' if v.get("versao") else "")
        + _preco_html(cfg, v, "grande")
        + (f"<dl>{dl}</dl>" if dl else "") + opc + desc + botao
        + f'</div><a class="voltar" href="{_e(base)}">← Ver todos os veículos</a></div>')
    corpo = (_cabecalho(cfg, base, link_whatsapp(cfg, None, base))
             + f'<main class="wrap"><div class="ficha">{galeria}{painel}</div></main>')
    preco_txt = (reais(v["preco"]) if cfg.get("mostrar_preco", True) and v.get("preco") else "")
    titulo = " ".join(p for p in (nome_carro(v), ano(v)) if p)
    og = {"title": f"{titulo}{' · ' + preco_txt if preco_txt else ''}", "type": "product", "url": link,
          "description": " · ".join(p for p in (v.get("versao"), km(v),
                                                ROTULOS["cambio"].get(v.get("cambio") or "", ""),
                                                cfg.get("nome")) if p),
          "image": _foto_url(base, fotos[0]) if fotos else None}
    return _pagina(f"{titulo} — {cfg.get('nome') or 'Catálogo'}", corpo, og)


def pagina_aviso(cfg: dict | None, base: str | None, titulo: str, texto: str) -> str:
    voltar = f'<p><a class="btn" href="{_e(base)}">Ver os veículos disponíveis</a></p>' if base else ""
    corpo = ((_cabecalho(cfg, base, None) if cfg and base else "")
             + f'<main class="wrap"><div class="vazio"><h1 style="color:var(--ink)">{_e(titulo)}</h1>'
             f'<p>{_e(texto)}</p>{voltar}</div></main>')
    return _pagina(titulo, corpo, {"title": titulo})


def url_base(publica: str, slug: str) -> str:
    return f"{publica.rstrip('/')}/c/{slug}"
