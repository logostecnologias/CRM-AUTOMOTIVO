"""Teste do estoque de veículos, com Mongo falso.

Onde estão os riscos, e por isso o que se testa:

- **Carro de uma loja aparecendo para outra.** Toda rota filtra por
  `tenant_id`; a etapa de isolamento tenta ler, editar, apagar e subir foto no
  carro de outra empresa.
- **Foto do anúncio sumindo sozinha.** A foto é mídia comum, e a retenção de
  90 dias apaga mídia comum. A etapa de fotos confere que a foto nasce marcada
  `uso: "veiculo"` e que a varredura da retenção não a pega.
- **Número errado no topo da tela.** "Parados há +60 dias" e "valor em pátio"
  são o que o dono olha; a etapa de resumo monta um pátio conhecido e confere.
"""
import asyncio
import io
import os
import sys
import tempfile
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for k, v in {"MONGO_URL": "mongodb://x/", "DB_NAME": "x", "JWT_SECRET": "x",
             "META_PLATFORM_TOKEN": "token-de-teste"}.items():
    os.environ.setdefault(k, v)
os.environ["MEDIA_DIR"] = tempfile.mkdtemp(prefix="auto-estoque-")

from fakedb import FakeDB
from fastapi import HTTPException
from pydantic import ValidationError
from starlette.datastructures import Headers, UploadFile

import db as db_mod
DB = FakeDB()
db_mod.get_db = lambda: DB

import media_retention
import routes.estoque as re_

_MODULOS_FAKE = (re_, media_retention)


def _conectar_fake():
    db_mod.get_db = lambda: DB
    for _m in _MODULOS_FAKE:
        _m.get_db = lambda: DB


A = {"id": "u-a", "tenant_id": "t-a", "role": "tenant_admin", "name": "Ana", "email": "a@x"}
B = {"id": "u-b", "tenant_id": "t-b", "role": "tenant_admin", "name": "Beto", "email": "b@x"}
ok = 0


def check(nome, cond, extra=""):
    global ok
    if cond:
        ok += 1
        print(f"  OK  {nome}")
    else:
        print(f"  FALHOU  {nome}  -> {extra}")
        raise AssertionError(nome)


async def erro(coro):
    try:
        await coro
    except HTTPException as e:
        return e.status_code
    return None


def png():
    # Uma imagem pequena de verdade: o upload abre e comprime o arquivo, então
    # bytes que só "parecem" PNG não passam mais.
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (40, 30), (120, 120, 120)).save(buf, "PNG")
    return buf.getvalue()


def upload(nome="foto.png", tipo="image/png", dados=None):
    return UploadFile(file=io.BytesIO(dados or png()), filename=nome,
                      headers=Headers({"content-type": tipo}))


async def etapa_cadastro():
    print("\n[cadastro]")
    DB._cols.clear()
    v = await re_.criar(re_.VeiculoIn(
        marca="  Volkswagen ", modelo="Taos", versao="1.4 250 TSI  Highline",
        ano_fabricacao=2025, ano_modelo=2025, km=15856, preco=168990,
        cambio="automatico", combustivel="flex", categoria="suv", condicao="seminovo",
        placa="kuo-3e52", cor="Cinza", opcionais=["Teto solar", "teto solar", " ", "ACC"]), A)
    check("espaço em volta e repetido some", v["marca"] == "Volkswagen" and v["versao"] == "1.4 250 TSI Highline", v)
    check("placa normalizada", v["placa"] == "KUO3E52", v["placa"])
    check("opcional repetido e vazio saem", v["opcionais"] == ["Teto solar", "ACC"], v["opcionais"])
    check("nasce disponivel, entrando hoje", v["status"] == "disponivel" and v["entrada_em"] == date.today().isoformat())
    check("zero dia no patio", v["dias_no_patio"] == 0 and v["parado"] is False)

    for nome, kw in [("placa invalida", {"placa": "12345"}),
                     ("cambio fora da lista", {"cambio": "AT"}),
                     ("ano absurdo", {"ano_modelo": 1800}),
                     ("km negativo", {"km": -1})]:
        try:
            re_.VeiculoIn(marca="Fiat", modelo="Argo", **kw)
            check(f"{nome} recusado", False, "passou")
        except ValidationError:
            check(f"{nome} recusado", True)
    check("marca so de espaco recusada",
          await erro(re_.criar(re_.VeiculoIn(marca=" ", modelo="Argo"), A)) == 400)
    return v


async def etapa_lista(taos):
    print("\n[lista e busca]")
    await re_.criar(re_.VeiculoIn(marca="Chevrolet", modelo="Ônix", versao="1.0 Turbo Premier",
                                  categoria="hatch", preco=92900, km=31402, ano_modelo=2024), A)
    hilux = await re_.criar(re_.VeiculoIn(marca="Toyota", modelo="Hilux", categoria="picape",
                                          preco=279900, destaque=True, ano_modelo=2023), A)
    await re_.criar(re_.VeiculoIn(marca="Fiat", modelo="Argo", preco=70000), B)

    todos = await re_.listar(user=A)
    check("so os da propria loja", len(todos) == 3, len(todos))
    check("destaque vem primeiro", todos[0]["id"] == hilux["id"], [v["modelo"] for v in todos])
    achou = await re_.listar(q="onix premier", user=A)
    check("busca sem acento e com varias palavras", [v["modelo"] for v in achou] == ["Ônix"], achou)
    check("busca pela placa", [v["id"] for v in await re_.listar(q="kuo3e52", user=A)] == [taos["id"]])
    check("filtro de categoria", [v["modelo"] for v in await re_.listar(categoria="suv", user=A)] == ["Taos"])
    precos = [v["preco"] for v in await re_.listar(ordem="preco_menor", user=A) if not v["destaque"]]
    check("ordem por preco", precos == sorted(precos), precos)
    return hilux


async def etapa_situacao(hilux):
    print("\n[situacao e edicao]")
    v = await re_.editar(hilux["id"], re_.VeiculoPatch(status="vendido"), A)
    check("vendido ganha a data da venda", v["vendido_em"] == date.today().isoformat())
    check("vendido sai do filtro de estoque",
          hilux["id"] not in [x["id"] for x in await re_.listar(status="estoque", user=A)])
    v = await re_.editar(hilux["id"], re_.VeiculoPatch(status="disponivel"), A)
    check("voltar a disponivel limpa a data", v["vendido_em"] is None)
    v = await re_.editar(hilux["id"], re_.VeiculoPatch(versao=None, preco=275000), A)
    check("so o que veio muda", v["versao"] is None and v["preco"] == 275000 and v["modelo"] == "Hilux", v)
    v = await re_.editar(hilux["id"], re_.VeiculoPatch(preco_anterior=289900), A)
    check("preco de/por guardado", v["preco_anterior"] == 289900 and v["preco"] == 275000, v)
    check("apagar a marca nao pode",
          await erro(re_.editar(hilux["id"], re_.VeiculoPatch(marca=""), A)) == 400)


async def etapa_resumo():
    print("\n[resumo do patio]")
    velho = (date.today() - timedelta(days=75)).isoformat()
    parado = await re_.criar(re_.VeiculoIn(marca="Honda", modelo="Civic", preco=128500,
                                           entrada_em=date.fromisoformat(velho)), A)
    check("75 dias no patio e parado", parado["dias_no_patio"] == 75 and parado["parado"] is True)
    r = await re_.resumo(user=A)
    no_patio = [v for v in await re_.listar(user=A) if v["status"] != "vendido"]
    check("em estoque", r["em_estoque"] == len(no_patio), r)
    check("valor em patio", r["valor_patio"] == sum(v["preco"] or 0 for v in no_patio), r)
    check("parados e valor parado", r["parados"] == 1 and r["valor_parado"] == 128500, r)
    check("ordem mais parados poe o Civic na frente",
          [v for v in await re_.listar(ordem="mais_parados", user=A) if not v["destaque"]][0]["id"] == parado["id"])


async def etapa_fotos(taos):
    print("\n[fotos]")
    r1 = await re_.subir_foto(taos["id"], upload("1.png"), A)
    r2 = await re_.subir_foto(taos["id"], upload("2.png"), A)
    check("fotos na ordem de envio", r2["fotos"] == [r1["id"], r2["id"]], r2)
    doc = await DB.media_files.find_one({"id": r1["id"]})
    check("foto marcada como de veiculo", doc["uso"] == "veiculo" and doc["veiculo_id"] == taos["id"], doc)
    check("documento nao e imagem recusado",
          await erro(re_.subir_foto(taos["id"], upload("a.pdf", "application/pdf", b"%PDF-1.4"), A)) == 400)

    nova = await re_.ordenar_fotos(taos["id"], re_.OrdemFotos(ids=[r2["id"], r1["id"]]), A)
    check("capa trocada", nova["fotos"][0] == r2["id"])
    check("ordem com foto estranha recusada",
          await erro(re_.ordenar_fotos(taos["id"], re_.OrdemFotos(ids=[r2["id"], "x"]), A)) == 400)

    # A retenção de 90 dias não pode pegar foto de anúncio, por mais velha que seja.
    await DB.media_files.update_many({"uso": "veiculo"}, {"$set": {"created_at": "2000-01-01T00:00:00+00:00"}})
    # Controle: uma mídia de conversa igualmente velha É recolhida, senão o
    # teste passaria com a varredura simplesmente desligada.
    await DB.media_files.insert_one({"id": "conversa", "tenant_id": "t-a", "stored_name": "x.png",
                                     "created_at": "2000-01-01T00:00:00+00:00", "purged_at": None})
    await DB.media_files.update_many({"uso": "veiculo"}, {"$set": {"purged_at": None}})
    await media_retention._purge_window(DB, ["t-a"], 30)
    check("a varredura recolhe midia de conversa velha",
          bool((await DB.media_files.find_one({"id": "conversa"})).get("purged_at")))
    check("retencao nao marca foto de veiculo",
          all(not d.get("purged_at") for d in await DB.media_files.find({"uso": "veiculo"}).to_list(None)))

    fotos = await re_.apagar_foto(taos["id"], r1["id"], A)
    check("foto apagada sai da lista e do banco",
          fotos["fotos"] == [r2["id"]] and not await DB.media_files.find_one({"id": r1["id"]}))
    return r2["id"]


async def etapa_compressao(taos):
    print("\n[compressao das fotos]")
    from PIL import Image
    import media_store

    # Foto de celular: 4000x3000, gravada deitada (EXIF 6 = girar 90°) e com GPS.
    img = Image.effect_noise((4000, 3000), 60).convert("RGB")
    exif = Image.Exif()
    exif[0x0112] = 6
    exif[0x8825] = {1: "S", 2: (3.0, 43.0, 0.0)}
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=97, exif=exif.tobytes())
    crua = buf.getvalue()
    r = await re_.subir_foto(taos["id"], upload("IMG_0001.HEIC.jpeg", "image/jpeg", crua), A)
    doc = await DB.media_files.find_one({"id": r["id"]})
    salvo = Image.open(media_store.file_path(doc))
    check("lado maior reduzido a 1600px", max(salvo.size) == re_.FOTO_LADO_MAX, salvo.size)
    check("girada pelo EXIF (fica em pe)", salvo.size[1] > salvo.size[0], salvo.size)
    check("sem EXIF nenhum (nem GPS)", len(salvo.getexif()) == 0, dict(salvo.getexif()))
    check("guardada em JPEG", salvo.format == "JPEG" and doc["mime"] == "image/jpeg" and doc["filename"].endswith(".jpg"), doc)
    check("bem menor que a original", doc["size"] < len(crua) / 4, (doc["size"], len(crua)))

    # PNG recortado: o transparente vira branco, não preto.
    png_t = Image.new("RGBA", (800, 600), (0, 0, 0, 0))
    png_t.paste((200, 0, 0, 255), (300, 200, 500, 400))
    buf = io.BytesIO(); png_t.save(buf, "PNG")
    r = await re_.subir_foto(taos["id"], upload("recorte.png", "image/png", buf.getvalue()), A)
    salvo = Image.open(media_store.file_path(await DB.media_files.find_one({"id": r["id"]}))).convert("RGB")
    check("transparencia vira fundo branco", salvo.getpixel((5, 5)) > (240, 240, 240), salvo.getpixel((5, 5)))
    check("foto pequena nao e ampliada", salvo.size == (800, 600), salvo.size)

    check("arquivo que diz ser imagem mas nao e: recusado",
          await erro(re_.subir_foto(taos["id"], upload("falsa.jpg", "image/jpeg", b"nao sou imagem"), A)) == 400)


async def etapa_isolamento(taos, foto):
    print("\n[isolamento]")
    check("outra loja nao le", await erro(re_.obter(taos["id"], B)) == 404)
    check("outra loja nao edita", await erro(re_.editar(taos["id"], re_.VeiculoPatch(preco=1), B)) == 404)
    check("outra loja nao sobe foto", await erro(re_.subir_foto(taos["id"], upload(), B)) == 404)
    check("outra loja nao apaga", await erro(re_.excluir(taos["id"], B)) == 404)

    await re_.excluir(taos["id"], A)
    check("excluido some", await erro(re_.obter(taos["id"], A)) == 404)
    check("e leva o documento das fotos", not await DB.media_files.find_one({"id": foto}))


def test_suite():
    _conectar_fake()

    async def _tudo():
        taos = await etapa_cadastro()
        hilux = await etapa_lista(taos)
        await etapa_situacao(hilux)
        await etapa_resumo()
        foto = await etapa_fotos(taos)
        await etapa_compressao(taos)
        await etapa_isolamento(taos, foto)
        print(f"\n=== {ok} verificacoes passaram ===")
    asyncio.run(_tudo())


if __name__ == "__main__":
    test_suite()
