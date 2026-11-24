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
  - Visual da tela de Estoque (direção Showroom), na paleta da marca da
    empresa, sem logo nem nome do revendedor: a página é da loja.
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
# HTML: a direção "Showroom" do Estoque, fora do app
# ---------------------------------------------------------------------------
#
# É a mesma linguagem da tela de Estoque (`frontend/src/index.css`, bloco
# "Showroom", e `components/estoque/Visual.jsx`): salão claro e silencioso,
# quem dá cor são as fotos; Poppins nos títulos, Inter no texto; cartão de
# 18px com a foto em fundo de estúdio e a silhueta em traço quando não há
# foto; selos discretos sobre a foto; o "de" riscado acima do preço; moldura
# escura (a barra do topo, como a lateral do painel) e o acento da marca só em
# detalhe. Os valores abaixo são **cópia** dos tokens de `index.css`: a página
# não carrega o CSS do app (é outro documento, sem build). Mudou um token lá,
# muda aqui.
#
# A paleta é a da marca da empresa (Logos ou R3), sem logo nem nome do
# revendedor: a cor é da casa, a página é da loja.

PALETAS = {
    "logos": {
        "claro": dict(bg="#F5F4F2", surface="#FFFFFF", surface2="#FAF9F7", surface3="#EFEDE9",
                      line="#E7E5E1", line2="#D4D1CB", text="#0E0E10", text2="#45454E",
                      text3="#63636F", text4="#8A8A96", nav="#0E0E10", navfg="#A8A8B3",
                      navforte="#FFFFFF", navlinha="#232328", acento="#F77C20",
                      acentotexto="#B4540A", acentofg="#0E0E10", sombra1="rgba(14,14,16,.05)",
                      sombra2="rgba(14,14,16,.16)"),
        "escuro": dict(bg="#0B0B0D", surface="#141417", surface2="#19191D", surface3="#222227",
                       line="#26262C", line2="#37373F", text="#F2F1EF", text2="#C6C6CE",
                       text3="#9C9CA8", text4="#75757F", nav="#08080A", navfg="#9C9CA8",
                       navforte="#FFFFFF", navlinha="#1C1C21", acento="#FF9A45",
                       acentotexto="#FF9A45", acentofg="#0E0E10", sombra1="rgba(0,0,0,.30)",
                       sombra2="rgba(0,0,0,.55)"),
        "titulo": "Poppins",
    },
    "r3": {
        "claro": dict(bg="#F1EEEE", surface="#FFFFFF", surface2="#F8F6F6", surface3="#E9E4E4",
                      line="#E5E0E0", line2="#CCC4C4", text="#00262E", text2="#2F535B",
                      text3="#4A6970", text4="#6B8389", nav="#00333D", navfg="#A9BEC2",
                      navforte="#FFFFFF", navlinha="#12505C", acento="#D6E30F",
                      acentotexto="#0A6A7B", acentofg="#00333D", sombra1="rgba(0,51,61,.06)",
                      sombra2="rgba(0,51,61,.18)"),
        "escuro": dict(bg="#00262E", surface="#00313B", surface2="#063A45", surface3="#0E4652",
                       line="#164F5A", line2="#29636F", text="#F1EEEE", text2="#C7D6D8",
                       text3="#9DB4B8", text4="#86A0A5", nav="#001D23", navfg="#9DB4B8",
                       navforte="#FFFFFF", navlinha="#0B3A44", acento="#D6E30F",
                       acentotexto="#D6E30F", acentofg="#00333D", sombra1="rgba(0,0,0,.30)",
                       sombra2="rgba(0,0,0,.55)"),
        "titulo": "Manrope",
    },
}

FONTES = ("https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700"
          "&family=Poppins:wght@500;600;700&family=Manrope:wght@600;700;800&display=swap")


def _vars(p: dict) -> str:
    return ";".join(f"--{k}:{v}" for k, v in p.items())


def _css(marca: str) -> str:
    pal = PALETAS.get(marca) or PALETAS["logos"]
    titulo = pal["titulo"]
    return (
        f":root{{{_vars(pal['claro'])};--titulo:'{titulo}','Inter',system-ui,sans-serif}}"
        f"@media (prefers-color-scheme:dark){{:root{{{_vars(pal['escuro'])}}}}}"
        + CSS_BASE
    )


CSS_BASE = """
*{box-sizing:border-box}html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--text);font:15px/1.5 'Inter',system-ui,-apple-system,sans-serif;-webkit-font-smoothing:antialiased}
a{color:inherit;text-decoration:none}img{display:block;max-width:100%}
.num{font-variant-numeric:tabular-nums}
.t{font-family:var(--titulo);letter-spacing:-.015em}
.wrap{max-width:1240px;margin:0 auto;padding:0 16px}
@media (min-width:640px){.wrap{padding:0 28px}}
.sobre{font-size:.66rem;font-weight:600;letter-spacing:.18em;text-transform:uppercase;color:var(--text3)}

/* Moldura: a barra do topo faz o papel da lateral escura do painel. */
.topo{background:var(--nav);color:var(--navforte);border-bottom:1px solid var(--navlinha)}
.topo .wrap{display:flex;align-items:center;justify-content:space-between;gap:16px;min-height:68px}
.loja{display:flex;flex-direction:column;min-width:0}
.loja-nome{font-family:var(--titulo);font-weight:700;font-size:1.15rem;letter-spacing:-.01em;line-height:1.2;
white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.loja-nome:after{content:"";display:block;width:22px;height:2px;border-radius:2px;background:var(--acento);margin-top:5px}
.loja-end{font-size:.74rem;color:var(--navfg);margin-top:4px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}

.btn{display:inline-flex;align-items:center;justify-content:center;gap:.5rem;height:2.6rem;padding:0 1.1rem;border-radius:12px;
font:600 .86rem 'Inter',system-ui,sans-serif;border:1px solid var(--line);background:var(--surface);color:var(--text);cursor:pointer;
transition:filter .15s,background .15s,border-color .15s;white-space:nowrap}
.btn:hover{border-color:var(--line2)}
.btn svg{width:17px;height:17px;flex:none}
.btn-zap{background:#1F7A4D;border-color:#1F7A4D;color:#fff}
.btn-zap:hover{filter:brightness(1.08)}
.topo .btn-zap{height:2.4rem;padding:0 .95rem}
@media (max-width:520px){.topo .btn-zap span{display:none}.topo .btn-zap{width:2.4rem;padding:0}}

/* Abertura da lista */
.abre{padding:34px 0 8px}
.abre h1{font-family:var(--titulo);font-weight:600;font-size:clamp(1.7rem,4vw,2.4rem);letter-spacing:-.02em;margin:6px 0 4px;line-height:1.1}
.abre p{margin:0;color:var(--text3);font-size:.9rem}

/* Filtros: busca, chips de categoria e ordem */
.filtros{display:flex;flex-wrap:wrap;align-items:center;gap:10px;margin:22px 0 10px}
.busca{position:relative;flex:1 1 280px;min-width:0}
.busca svg{position:absolute;left:13px;top:50%;translate:0 -50%;width:17px;height:17px;color:var(--text4)}
.campo{width:100%;height:2.75rem;border:1px solid var(--line);background:var(--surface);color:var(--text);border-radius:12px;
padding:0 14px;font:inherit;font-size:.9rem;outline:none;transition:border-color .15s,box-shadow .15s}
.busca .campo{padding-left:40px}
.campo:focus{border-color:var(--acentotexto);box-shadow:0 0 0 3px color-mix(in srgb,var(--acentotexto) 22%,transparent)}
select.campo{width:auto;flex:0 0 auto;padding-right:34px;appearance:none;cursor:pointer;
background-image:linear-gradient(45deg,transparent 50%,var(--text3) 50%),linear-gradient(135deg,var(--text3) 50%,transparent 50%);
background-position:calc(100% - 18px) 52%,calc(100% - 13px) 52%;background-size:5px 5px;background-repeat:no-repeat}
.chips{display:flex;flex-wrap:wrap;gap:8px;margin:4px 0 6px}
.chip{display:inline-flex;align-items:center;height:2.1rem;padding:0 .95rem;border-radius:999px;font-size:.8rem;font-weight:500;
color:var(--text2);background:var(--surface);border:1px solid var(--line);transition:border-color .15s,color .15s}
.chip:hover{color:var(--text);border-color:var(--line2)}
/* O sólido da marca: escuro no claro, quase branco no escuro (como `--brand` no painel). */
.chip.ativo{background:var(--text);border-color:var(--text);color:var(--surface)}
.qtd{color:var(--text3);font-size:.8rem;margin:14px 0 16px}

/* Vitrine: o mesmo cartão do Estoque */
.vitrine{display:grid;gap:1.25rem;grid-template-columns:repeat(auto-fill,minmax(17.5rem,1fr));padding-bottom:56px}
.cartao{display:flex;flex-direction:column;background:var(--surface);border:1px solid var(--line);border-radius:18px;overflow:hidden;
transition:transform .25s cubic-bezier(.2,.7,.2,1),box-shadow .25s ease,border-color .2s ease}
.cartao:hover{transform:translateY(-3px);border-color:var(--line2);box-shadow:0 18px 40px -24px var(--sombra2)}
.cartao:focus-visible{outline:none;box-shadow:0 0 0 3px color-mix(in srgb,var(--acentotexto) 35%,transparent)}
.foto{position:relative;overflow:hidden;aspect-ratio:4/3;background:radial-gradient(ellipse at 50% 35%,var(--surface) 0%,var(--surface3) 75%)}
.foto img{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;transition:transform .6s cubic-bezier(.2,.7,.2,1)}
.cartao:hover .foto img{transform:scale(1.035)}
.silhueta{position:absolute;inset:0;display:grid;place-items:center;color:var(--text4)}
.silhueta svg{width:50%;opacity:.4}
.selo{position:absolute;z-index:2;display:inline-flex;align-items:center;font-size:.66rem;font-weight:600;letter-spacing:.03em;padding:.28rem .55rem;
border-radius:8px;background:color-mix(in srgb,var(--surface) 92%,transparent);color:var(--text);backdrop-filter:blur(6px);box-shadow:0 1px 2px var(--sombra1)}
.selo.tl{top:12px;left:12px}.selo.br{bottom:10px;right:12px}
.selo.escuro{background:var(--nav);color:var(--navforte)}
.selo.destaque{background:var(--nav);color:var(--acento)}
.corpo{padding:16px 18px 18px;display:flex;flex-direction:column;flex:1}
@media (min-width:640px){.corpo{padding:18px 20px 20px}}
.nome{font-family:var(--titulo);font-weight:600;font-size:1.05rem;letter-spacing:-.015em;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.versao{font-size:.8rem;color:var(--text3);margin-top:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;min-height:1.2em}
.dados{font-size:.75rem;color:var(--text3);margin:12px 0 16px;display:flex;flex-wrap:wrap;gap:6px}
.dados i{font-style:normal;color:var(--line2)}
.preco-linha{margin-top:auto;padding-top:16px;border-top:1px solid var(--line);display:flex;align-items:flex-end;justify-content:space-between;gap:12px}
.de{font-size:.7rem;color:var(--text3);text-decoration:line-through;margin-bottom:4px}
.preco{font-family:var(--titulo);font-weight:600;font-size:1.3rem;letter-spacing:-.015em;line-height:1}
.consulte{font-size:.95rem;color:var(--text2)}
.ver{font-size:.75rem;font-weight:600;color:var(--acentotexto);white-space:nowrap}

/* Celular: duas colunas, como vitrine de loja de carro. Com metade da tela, o
   cartão encolhe: o "Ver detalhes" sai (o cartão inteiro é o link) e a linha
   de dados fica só com ano e km. */
@media (max-width:639px){
.vitrine{grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;padding-bottom:40px}
.cartao{border-radius:14px}
.cartao:hover{transform:none}
.corpo{padding:10px 11px 12px}
.nome{font-size:.86rem}
.versao{font-size:.7rem}
.dados{font-size:.66rem;margin:7px 0 9px;gap:4px}
.dados span:nth-of-type(3),.dados i:nth-of-type(2){display:none}
.preco-linha{padding-top:9px}
.preco{font-size:1rem}
.de{font-size:.62rem;margin-bottom:2px}
.consulte{font-size:.78rem}
.ver{display:none}
.selo{font-size:.58rem;padding:.2rem .42rem;border-radius:6px}
.selo.tl{top:7px;left:7px}.selo.br{bottom:6px;right:7px}
.silhueta svg{width:62%}
}

.vazio{text-align:center;padding:72px 16px 96px;color:var(--text3)}
.vazio svg{width:180px;color:var(--text4);opacity:.45;margin:0 auto 18px}
.vazio h2{font-family:var(--titulo);font-weight:600;color:var(--text);font-size:1.3rem;margin:0 0 6px}
.vazio .btn{margin-top:18px}

/* Ficha do carro: galeria à esquerda, ficha à direita, como no painel */
.ficha{display:grid;grid-template-columns:minmax(0,1fr);gap:22px;padding:22px 0 120px}
@media (min-width:960px){.ficha{grid-template-columns:minmax(0,1.4fr) minmax(0,1fr);gap:32px;padding:32px 0 64px;align-items:start}}
.voltar{display:inline-flex;align-items:center;gap:6px;font-size:.82rem;color:var(--text3);margin-top:22px}
.voltar:hover{color:var(--text)}
.galeria{background:var(--surface2);border:1px solid var(--line);border-radius:22px;padding:10px}
@media (min-width:640px){.galeria{padding:14px}}
.slides{display:flex;overflow-x:auto;scroll-snap-type:x mandatory;scroll-behavior:smooth;border-radius:16px;scrollbar-width:none}
.slides::-webkit-scrollbar{display:none}
.slide{flex:0 0 100%;scroll-snap-align:start;position:relative}
.slide .foto{border-radius:16px}
.miniaturas{display:flex;gap:8px;overflow-x:auto;margin-top:10px;padding-bottom:2px;scrollbar-width:thin}
.miniaturas a{flex:0 0 88px;border-radius:10px;overflow:hidden;opacity:.7;transition:opacity .15s}
.miniaturas a:hover{opacity:1}
.miniaturas .foto{aspect-ratio:4/3}
.painel{background:var(--surface);border:1px solid var(--line);border-radius:22px;padding:22px}
@media (min-width:640px){.painel{padding:28px 30px}}
@media (min-width:960px){.painel{position:sticky;top:20px}}
.painel h1{font-family:var(--titulo);font-weight:600;font-size:1.75rem;letter-spacing:-.02em;line-height:1.15;margin:6px 0 0}
.painel .versao{font-size:.9rem;color:var(--text2);white-space:normal;margin-top:4px}
.preco-grande{font-family:var(--titulo);font-weight:600;font-size:2.2rem;letter-spacing:-.02em;line-height:1;margin-top:6px}
.de-grande{font-size:.85rem;color:var(--text3);margin-top:20px}
.de-grande s{color:var(--text3)}
.specs{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px 20px;padding:20px 0;margin:20px 0 0;border-top:1px solid var(--line);border-bottom:1px solid var(--line)}
@media (min-width:640px){.specs{grid-template-columns:repeat(3,minmax(0,1fr))}}
.specs dt{font-size:.6rem;font-weight:600;letter-spacing:.18em;text-transform:uppercase;color:var(--text3)}
.specs dd{margin:4px 0 0;font-size:.9rem;font-weight:500}
.bloco{margin-top:22px}
.bloco .sobre{margin-bottom:10px}
.tags{display:flex;flex-wrap:wrap;gap:6px}
.tag{font-size:.78rem;background:var(--surface3);border-radius:8px;padding:5px 10px;color:var(--text2)}
.desc{white-space:pre-line;color:var(--text2);font-size:.9rem;line-height:1.65;margin:0}
.acao{position:fixed;left:0;right:0;bottom:0;z-index:5;background:color-mix(in srgb,var(--surface) 94%,transparent);backdrop-filter:blur(10px);
border-top:1px solid var(--line);padding:12px 16px calc(12px + env(safe-area-inset-bottom))}
.acao .btn{width:100%;height:3rem;font-size:.95rem}
@media (min-width:960px){.acao{position:static;background:none;backdrop-filter:none;border:0;padding:0;margin-top:26px}}
.reservado{display:inline-flex;font-size:.66rem;font-weight:600;letter-spacing:.03em;padding:.28rem .55rem;border-radius:8px;background:var(--nav);color:var(--navforte);margin-bottom:10px}

.rodape{border-top:1px solid var(--line);color:var(--text3);font-size:.78rem;padding:22px 0 30px}
.rodape .wrap{display:flex;flex-wrap:wrap;justify-content:space-between;gap:8px}
@media (prefers-reduced-motion:reduce){.cartao,.foto img{transition:none}.cartao:hover{transform:none}.slides{scroll-behavior:auto}}
"""

# A mesma silhueta em traço de `components/estoque/Visual.jsx`.
SILHUETA = (
    '<svg viewBox="0 0 640 240" aria-hidden="true"><path d="M58,164 L58,150 C58,134 66,124 82,120 L118,114 '
    'C150,108 176,92 206,78 C236,64 270,58 312,57 L372,57 C410,58 436,68 466,90 L492,108 L556,116 C578,119 '
    '590,130 592,146 L592,160 C592,166 588,170 582,170 L530,170 A42,42 0 0 0 446,170 L212,170 A42,42 0 0 0 '
    '128,170 L64,170 C60,170 58,168 58,164 Z" fill="none" stroke="currentColor" stroke-width="3" '
    'stroke-linejoin="round"/><path d="M214,84 C240,70 270,65 310,64 L336,64 L336,104 L176,104 C188,96 200,90 '
    '214,84 Z M348,64 L372,64 C404,65 428,74 452,94 L462,104 L348,104 Z" fill="none" stroke="currentColor" '
    'stroke-width="2.4" stroke-linejoin="round"/><circle cx="170" cy="160" r="32" fill="none" '
    'stroke="currentColor" stroke-width="3"/><circle cx="488" cy="160" r="32" fill="none" '
    'stroke="currentColor" stroke-width="3"/></svg>')

ICONE_ZAP = (
    '<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M12.04 2C6.58 2 2.13 6.45 2.13 '
    '11.91c0 1.75.46 3.45 1.32 4.95L2.05 22l5.25-1.38c1.45.79 3.08 1.21 4.74 1.21 5.46 0 9.91-4.45 '
    '9.91-9.91C21.95 6.45 17.5 2 12.04 2zm5.8 14.03c-.25.69-1.44 1.32-1.98 1.37-.51.05-.99.24-3.33-.69-2.82-1.11-4.6-4-4.74-4.18-.14-.18-1.13-1.5-1.13-2.86s.71-2.03.97-2.31c.25-.28.55-.35.73-.35h.53c.17 0 .4-.07.62.47.23.55.78 1.9.85 2.04.07.14.11.3.02.48-.09.18-.14.3-.28.46-.14.16-.29.36-.42.48-.14.14-.28.29-.12.57.16.28.72 1.19 1.55 1.93 1.07.95 1.97 1.25 2.25 1.39.28.14.44.12.6-.07.16-.18.69-.81.88-1.09.18-.28.37-.23.62-.14.25.09 1.6.76 1.87.9.28.14.46.21.53.32.07.12.07.67-.18 1.36z"/></svg>')

ICONE_BUSCA = ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" '
               'aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>')


def _pagina(titulo: str, corpo: str, og: dict, marca: str = "logos") -> str:
    metas = "".join(
        f'<meta property="og:{k}" content="{_e(v)}">' for k, v in og.items() if v)
    descricao = og.get("description") or ""
    return (
        "<!doctype html><html lang=\"pt-BR\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1,viewport-fit=cover\">"
        f"<title>{_e(titulo)}</title><meta name=\"description\" content=\"{_e(descricao)}\">"
        f"{metas}<meta name=\"twitter:card\" content=\"summary_large_image\">"
        "<meta name=\"robots\" content=\"noindex\">"
        '<link rel="preconnect" href="https://fonts.googleapis.com">'
        '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
        f'<link rel="stylesheet" href="{FONTES}">'
        f"<style>{_css(marca)}</style></head><body>{corpo}</body></html>"
    )


def _topo(cfg: dict, base: str, wa: str | None) -> str:
    end = f'<span class="loja-end">{_e(cfg["endereco"])}</span>' if cfg.get("endereco") else ""
    botao = (f'<a class="btn btn-zap" href="{_e(wa)}" rel="noopener" aria-label="Falar no WhatsApp">'
             f'{ICONE_ZAP}<span>Falar no WhatsApp</span></a>') if wa else ""
    return (f'<header class="topo"><div class="wrap"><a class="loja" href="{_e(base)}">'
            f'<span class="loja-nome">{_e(cfg.get("nome") or "Catálogo")}</span>{end}</a>{botao}</div></header>')


def _rodape(cfg: dict) -> str:
    return (f'<footer class="rodape"><div class="wrap"><span>{_e(cfg.get("nome") or "")}</span>'
            f'<span>{_e(cfg.get("endereco") or "")}</span></div></footer>')


def _foto_url(base: str, media_id: str) -> str:
    return f"{base}/foto/{quote(media_id)}"


def _foto(base: str, media_id: str | None, alt: str, lazy: bool = True) -> str:
    if not media_id:
        return f'<div class="foto"><div class="silhueta">{SILHUETA}</div></div>'
    carregar = ' loading="lazy"' if lazy else ""
    # A silhueta fica por baixo: enquanto a foto carrega, o cartão já tem forma.
    return (f'<div class="foto"><div class="silhueta">{SILHUETA}</div>'
            f'<img src="{_e(_foto_url(base, media_id))}" alt="{_e(alt)}"{carregar}></div>')


def _tem_promocao(v: dict) -> bool:
    return bool(v.get("preco_anterior") and v.get("preco") and v["preco_anterior"] > v["preco"])


def _mostra_preco(cfg: dict, v: dict) -> bool:
    return bool(cfg.get("mostrar_preco", True) and v.get("preco"))


def _cartao(cfg: dict, base: str, v: dict) -> str:
    fotos = v.get("fotos") or []
    if v.get("status") == "reservado":
        selo = '<span class="selo tl escuro">Reservado</span>'
    elif v.get("destaque"):
        selo = '<span class="selo tl destaque">Destaque</span>'
    else:
        selo = ""
    qtd = f'<span class="selo br num">{len(fotos)} fotos</span>' if len(fotos) > 1 else ""
    dados = [ano(v), km(v), ROTULOS["cambio"].get(v.get("cambio") or "", "")]
    dados = '<i>·</i>'.join(f"<span>{_e(d)}</span>" for d in dados if d)
    if _mostra_preco(cfg, v):
        de = f'<div class="de num">{reais(v["preco_anterior"])}</div>' if _tem_promocao(v) else ""
        preco = f'<div>{de}<div class="preco num">{reais(v["preco"])}</div></div>'
    else:
        preco = '<div class="consulte">Preço sob consulta</div>'
    foto = _foto(base, fotos[0] if fotos else None, nome_carro(v)).replace(
        '<div class="foto">', f'<div class="foto">{selo}{qtd}', 1)
    return (
        f'<a class="cartao" href="{_e(base)}/{_e(v["id"])}">{foto}<div class="corpo">'
        f'<div class="nome">{_e(nome_carro(v))}</div><div class="versao">{_e(v.get("versao") or "")}</div>'
        + (f'<div class="dados num">{dados}</div>' if dados else '<div class="dados"></div>')
        + f'<div class="preco-linha">{preco}<span class="ver">Ver detalhes →</span></div></div></a>')


def pagina_lista(cfg: dict, veiculos: list[dict], base: str, total: int,
                 q: str = "", categoria: str = "", ordem: str = "recentes",
                 categorias: list[str] | None = None, marca: str = "logos") -> str:
    wa = link_whatsapp(cfg, None, base)
    filtrando = bool(q or categoria)

    def url(**kw):
        params = {"q": q, "categoria": categoria, "ordem": ordem if ordem != "recentes" else ""}
        params.update(kw)
        qs = "&".join(f"{k}={quote(str(v))}" for k, v in params.items() if v)
        return f"{base}?{qs}" if qs else base

    chips = ""
    if categorias and len(categorias) > 1:
        chips = '<nav class="chips" aria-label="Categorias">' + "".join(
            f'<a class="chip{" ativo" if c == categoria else ""}" href="{_e(url(categoria=c))}">'
            f'{_e(r)}</a>'
            for c, r in [("", "Todos")] + [(c, ROTULOS["categoria"].get(c, c)) for c in categorias]) + "</nav>"
    ords = "".join(f'<option value="{k}"{" selected" if k == ordem else ""}>{r}</option>'
                   for k, r in ORDENS.items())
    filtros = (
        f'<form class="filtros" method="get" action="{_e(base)}" role="search">'
        f'<label class="busca">{ICONE_BUSCA}<input class="campo" type="search" name="q" value="{_e(q)}" '
        f'placeholder="Buscar marca, modelo, ano, cor…" aria-label="Buscar"></label>'
        + (f'<input type="hidden" name="categoria" value="{_e(categoria)}">' if categoria else "")
        + f'<select class="campo" name="ordem" aria-label="Ordenar">{ords}</select>'
        '<button class="btn" type="submit">Buscar</button></form>')

    if filtrando:
        qtd = f"{len(veiculos)} de {total} veículos"
    else:
        qtd = f"{total} veículo{'s' if total != 1 else ''} disponíve{'is' if total != 1 else 'l'}"
    if veiculos:
        lista = f'<div class="vitrine">{"".join(_cartao(cfg, base, v) for v in veiculos)}</div>'
    else:
        lista = (f'<div class="vazio">{SILHUETA}<h2>Nenhum veículo encontrado</h2>'
                 '<p>Tente outra busca, ou fale com a gente: o carro que você procura pode estar chegando.</p>'
                 + (f'<a class="btn" href="{_e(base)}">Ver todos os veículos</a>' if filtrando else "")
                 + "</div>")
    abertura = (f'<section class="abre"><div class="sobre">Estoque</div>'
                f'<h1>Veículos à venda</h1><p>Fotos, ficha e preço de cada carro. Gostou de algum? '
                f'Chame a gente no WhatsApp.</p></section>')
    corpo = (_topo(cfg, base, wa)
             + f'<main class="wrap">{abertura}{filtros}{chips}<div class="qtd num">{qtd}</div>{lista}</main>'
             + _rodape(cfg))
    primeira = next((v["fotos"][0] for v in veiculos if v.get("fotos")), None)
    og = {"title": f"Estoque {cfg.get('nome') or ''}".strip(), "type": "website", "url": base,
          "description": f"{total} veículos à venda. Veja fotos, preços e fale com a gente no WhatsApp.",
          "image": _foto_url(base, primeira) if primeira else None}
    return _pagina(og["title"], corpo, og, marca)


def pagina_veiculo(cfg: dict, v: dict, base: str, marca: str = "logos") -> str:
    link = f"{base}/{v['id']}"
    wa = link_whatsapp(cfg, v, link)
    fotos = v.get("fotos") or []
    nome = nome_carro(v)
    if fotos:
        slides = "".join(
            f'<div class="slide" id="f{i + 1}">{_foto(base, m, f"{nome} — foto {i + 1}", lazy=i > 0)}'
            + (f'<span class="selo br num">{i + 1} / {len(fotos)}</span>' if len(fotos) > 1 else "")
            + "</div>" for i, m in enumerate(fotos))
        minis = ('<div class="miniaturas">' + "".join(
            f'<a href="#f{i + 1}" aria-label="Foto {i + 1}">{_foto(base, m, "")}</a>'
            for i, m in enumerate(fotos)) + "</div>") if len(fotos) > 1 else ""
        galeria = f'<div class="galeria"><div class="slides">{slides}</div>{minis}</div>'
    else:
        galeria = f'<div class="galeria">{_foto(base, None, nome)}</div>'

    specs = [("Ano", ano(v)), ("Quilometragem", km(v)),
             ("Câmbio", ROTULOS["cambio"].get(v.get("cambio") or "", "")),
             ("Combustível", ROTULOS["combustivel"].get(v.get("combustivel") or "", "")),
             ("Motor", v.get("motor")), ("Portas", v.get("portas")),
             ("Cor", v.get("cor")), ("Categoria", ROTULOS["categoria"].get(v.get("categoria") or "", "")),
             ("Condição", ROTULOS["condicao"].get(v.get("condicao") or "", ""))]
    dl = "".join(f"<div><dt>{k}</dt><dd class=\"num\">{_e(val)}</dd></div>" for k, val in specs if val)
    opc = ('<div class="bloco"><div class="sobre">Opcionais</div><div class="tags">'
           + "".join(f'<span class="tag">{_e(o)}</span>' for o in v["opcionais"]) + "</div></div>"
           if v.get("opcionais") else "")
    desc = (f'<div class="bloco"><div class="sobre">Sobre o veículo</div><p class="desc">{_e(v["observacoes"])}</p></div>'
            if v.get("observacoes") else "")
    if _mostra_preco(cfg, v):
        de = (f'<div class="de-grande num">de <s>{reais(v["preco_anterior"])}</s> por</div>'
              if _tem_promocao(v) else '<div class="de-grande"></div>')
        preco = f'{de}<div class="preco-grande num">{reais(v["preco"])}</div>'
    else:
        preco = '<div class="de-grande"></div><div class="preco-grande" style="font-size:1.4rem">Preço sob consulta</div>'
    reservado = '<span class="reservado">Reservado</span><br>' if v.get("status") == "reservado" else ""
    acao = (f'<div class="acao"><a class="btn btn-zap" href="{_e(wa)}" rel="noopener">{ICONE_ZAP}'
            'Tenho interesse — chamar no WhatsApp</a></div>') if wa else ""
    painel = (
        f'<div><div class="painel">{reservado}<div class="sobre">'
        + _e(" · ".join(p for p in (ROTULOS["categoria"].get(v.get("categoria") or "", ""),
                                    ROTULOS["condicao"].get(v.get("condicao") or "", "")) if p) or "Veículo")
        + f'</div><h1>{_e(nome)}</h1>'
        + (f'<div class="versao">{_e(v["versao"])}</div>' if v.get("versao") else "")
        + preco + (f'<dl class="specs">{dl}</dl>' if dl else "") + opc + desc + acao
        + f'</div><a class="voltar" href="{_e(base)}">← Ver todos os veículos</a></div>')
    corpo = (_topo(cfg, base, link_whatsapp(cfg, None, base))
             + f'<main class="wrap"><div class="ficha">{galeria}{painel}</div></main>' + _rodape(cfg))
    preco_txt = reais(v["preco"]) if _mostra_preco(cfg, v) else ""
    titulo = " ".join(p for p in (nome, ano(v)) if p)
    og = {"title": f"{titulo}{' · ' + preco_txt if preco_txt else ''}", "type": "product", "url": link,
          "description": " · ".join(p for p in (v.get("versao"), km(v),
                                                ROTULOS["cambio"].get(v.get("cambio") or "", ""),
                                                cfg.get("nome")) if p),
          "image": _foto_url(base, fotos[0]) if fotos else None}
    return _pagina(f"{titulo} — {cfg.get('nome') or 'Catálogo'}", corpo, og, marca)


def pagina_aviso(cfg: dict | None, base: str | None, titulo: str, texto: str, marca: str = "logos") -> str:
    voltar = f'<a class="btn" href="{_e(base)}">Ver os veículos disponíveis</a>' if base else ""
    corpo = ((_topo(cfg, base, None) if cfg and base else "")
             + f'<main class="wrap"><div class="vazio">{SILHUETA}<h2>{_e(titulo)}</h2>'
             f'<p>{_e(texto)}</p>{voltar}</div></main>')
    return _pagina(titulo, corpo, {"title": titulo}, marca)


def url_base(publica: str, slug: str) -> str:
    return f"{publica.rstrip('/')}/c/{slug}"
