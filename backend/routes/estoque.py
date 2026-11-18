"""Estoque de veículos: o pátio da revenda.

Cada carro é um documento em `veiculos`, cadastrado à mão pela loja: marca,
modelo, versão, a ficha técnica, preço, placa e as fotos. É a base da vitrine
(tela de Estoque), da ficha do veículo e, depois, do catálogo público e do
"encaminhar" no atendimento.

Decisões:

  - **Listas fechadas onde o dado vira filtro.** Câmbio, combustível,
    categoria, condição e situação são escolhas de uma lista (`OPCOES`), não
    texto livre: "Automático", "automatico" e "AT" na mesma loja quebrariam o
    filtro e a contagem. Marca, modelo, versão e cor são livres, porque a lista
    de verdade é a do mercado e muda todo ano.

  - **A busca é feita aqui, em Python, sobre o estoque da empresa.** Um pátio
    tem dezenas ou centenas de carros, não milhões; trazer tudo e filtrar evita
    montar regex com o que o usuário digitou e permite buscar sem acento.

  - **Dias no pátio vêm da data de entrada**, que a loja pode corrigir (o
    carro que entrou antes de o sistema existir). Para vendido, conta até a
    data da venda. É o número que faz o dono girar o estoque.

  - **Foto é comprimida na entrada** (`comprimir_foto`): 1600px, JPEG, sem
    o EXIF da câmera. O que fica guardado já é o que a vitrine mostra.

  - **Foto é mídia comum, marcada `uso: "veiculo"`.** O binário vai para o
    mesmo armazenamento das conversas, e a marcação tira a foto da retenção de
    90 dias (`media_retention`): o anúncio não pode perder a foto sozinho. A
    primeira da lista é a capa; a ordem é a da loja.

  - **Escrever é do admin; ler é de todo mundo da empresa.** O vendedor
    precisa achar o carro e mandar para o cliente, mas preço e situação são
    decisão da gerência.
"""
import io
import re
import unicodedata
import uuid
from datetime import date, datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import BaseModel, Field, field_validator

import media_store
from auth import require_tenant_admin, require_tenant_member
from db import get_db

router = APIRouter(prefix="/api/estoque", tags=["estoque"])

MAX_FOTOS = 30
PARADO_DIAS = 60

# Foto de anúncio: o lado maior até 1600px, em JPEG. É o que a vitrine e o
# catálogo precisam, e JPEG porque a foto vai ser encaminhada no WhatsApp, que
# só aceita JPEG e PNG como imagem. Uma foto de celular (4000px, 4 a 8MB) sai
# com 150 a 350KB.
FOTO_LADO_MAX = 1600
FOTO_QUALIDADE = 82
# Teto do arquivo que chega, antes de comprimir: cabe a foto crua de qualquer
# celular, e ainda barra quem tente subir um arquivo enorme.
FOTO_ORIGINAL_MAX = 25 * 1024 * 1024

Cambio = Literal["manual", "automatico", "cvt", "automatizado"]
Combustivel = Literal["flex", "gasolina", "etanol", "diesel", "hibrido", "eletrico", "gnv"]
Categoria = Literal["hatch", "sedan", "suv", "picape", "minivan", "esportivo", "utilitario", "moto"]
Condicao = Literal["novo", "seminovo", "usado"]
Situacao = Literal["disponivel", "reservado", "vendido"]

# O mesmo que os Literal acima, com o rótulo de tela. A tela pede isto em vez de
# repetir a lista: opção nova entra aqui e no Literal, e só.
OPCOES = {
    "cambio": [("manual", "Manual"), ("automatico", "Automático"), ("cvt", "CVT"),
               ("automatizado", "Automatizado")],
    "combustivel": [("flex", "Flex"), ("gasolina", "Gasolina"), ("etanol", "Etanol"),
                    ("diesel", "Diesel"), ("hibrido", "Híbrido"), ("eletrico", "Elétrico"),
                    ("gnv", "GNV")],
    "categoria": [("hatch", "Hatch"), ("sedan", "Sedã"), ("suv", "SUV"), ("picape", "Picape"),
                  ("minivan", "Minivan"), ("esportivo", "Esportivo"),
                  ("utilitario", "Utilitário"), ("moto", "Moto")],
    "condicao": [("novo", "Novo"), ("seminovo", "Seminovo"), ("usado", "Usado")],
    "status": [("disponivel", "Disponível"), ("reservado", "Reservado"), ("vendido", "Vendido")],
}

_PLACA = re.compile(r"^[A-Z]{3}[0-9][A-Z0-9][0-9]{2}$")
_ANO_MAX = date.today().year + 1


def _agora() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hoje() -> str:
    return date.today().isoformat()


def _texto(v: str | None) -> str | None:
    if v is None:
        return None
    v = re.sub(r"\s+", " ", v).strip()
    return v or None


def _placa(v: str | None) -> str | None:
    """Placa sem traço e sem espaço, em maiúscula, no formato antigo ou Mercosul."""
    if not v:
        return None
    p = re.sub(r"[^A-Za-z0-9]", "", v).upper()
    if not p:
        return None
    if not _PLACA.match(p):
        raise ValueError("Placa inválida. Use o formato ABC1234 ou ABC1D23.")
    return p


class _Campos(BaseModel):
    """Os campos da ficha, todos opcionais: a criação exige os seus à parte."""
    marca: str | None = Field(None, max_length=60)
    modelo: str | None = Field(None, max_length=80)
    versao: str | None = Field(None, max_length=120)
    ano_fabricacao: int | None = Field(None, ge=1950, le=_ANO_MAX)
    ano_modelo: int | None = Field(None, ge=1950, le=_ANO_MAX + 1)
    km: int | None = Field(None, ge=0, le=2_000_000)
    preco: float | None = Field(None, ge=0, le=100_000_000)
    # O "de" do "de R$ 74.990 por R$ 71.990": aparece riscado quando é maior
    # que o preço. Vazio = sem promoção.
    preco_anterior: float | None = Field(None, ge=0, le=100_000_000)
    cambio: Cambio | None = None
    combustivel: Combustivel | None = None
    motor: str | None = Field(None, max_length=30)
    portas: int | None = Field(None, ge=0, le=6)
    cor: str | None = Field(None, max_length=40)
    categoria: Categoria | None = None
    condicao: Condicao | None = None
    placa: str | None = Field(None, max_length=10)
    localizacao: str | None = Field(None, max_length=120)
    observacoes: str | None = Field(None, max_length=4000)
    opcionais: list[str] | None = Field(None, max_length=60)
    destaque: bool | None = None
    status: Situacao | None = None
    entrada_em: date | None = None

    @field_validator("marca", "modelo", "versao", "motor", "cor", "localizacao")
    @classmethod
    def _limpa(cls, v):
        return _texto(v)

    @field_validator("observacoes")
    @classmethod
    def _limpa_obs(cls, v):
        return (v or "").strip() or None

    @field_validator("placa")
    @classmethod
    def _valida_placa(cls, v):
        return _placa(v)

    @field_validator("opcionais")
    @classmethod
    def _limpa_opcionais(cls, v):
        if v is None:
            return None
        vistos, saida = set(), []
        for item in v:
            t = _texto(item)
            if t and t.lower() not in vistos and len(t) <= 60:
                vistos.add(t.lower())
                saida.append(t)
        return saida


class VeiculoIn(_Campos):
    marca: str = Field(..., min_length=1, max_length=60)
    modelo: str = Field(..., min_length=1, max_length=80)


class VeiculoPatch(_Campos):
    pass


class OrdemFotos(BaseModel):
    ids: list[str]


def _sem_acento(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s or "") if unicodedata.category(c) != "Mn").lower()


def _dias_no_patio(v: dict) -> int | None:
    try:
        inicio = date.fromisoformat((v.get("entrada_em") or "")[:10])
    except ValueError:
        return None
    fim = date.today()
    if v.get("status") == "vendido" and v.get("vendido_em"):
        try:
            fim = date.fromisoformat(v["vendido_em"][:10])
        except ValueError:
            pass
    return max(0, (fim - inicio).days)


def _saida(v: dict) -> dict:
    v = {k: val for k, val in v.items() if k != "_id"}
    v["dias_no_patio"] = _dias_no_patio(v)
    v["parado"] = v.get("status") != "vendido" and (v["dias_no_patio"] or 0) >= PARADO_DIAS
    return v


async def _do_tenant(db, veiculo_id: str, tenant_id: str) -> dict:
    v = await db.veiculos.find_one({"id": veiculo_id, "tenant_id": tenant_id}, {"_id": 0})
    if not v:
        raise HTTPException(status_code=404, detail="Veículo não encontrado")
    return v


def _transicao_status(atual: dict, novo: str | None) -> dict:
    """O que muda junto com a situação: a data da venda nasce e some com ela."""
    if novo is None or novo == atual.get("status"):
        return {}
    if novo == "vendido":
        return {"vendido_em": _hoje()}
    return {"vendido_em": None}


def comprimir_foto(dados: bytes) -> bytes:
    """A foto pronta para o anúncio: girada, reduzida, sem metadados, em JPEG.

    - **Girada pelo EXIF.** O celular grava a foto "deitada" e anota a rotação;
      sem aplicar a anotação, a foto aparece de lado na vitrine.
    - **Sem metadados.** O EXIF da câmera traz a posição GPS de onde a foto foi
      tirada (o endereço da loja, ou da casa de quem fotografou). Foto de
      anúncio é pública; o metadado não vai junto.
    - **Fundo branco onde era transparente.** JPEG não tem transparência, e um
      PNG recortado viraria um carro sobre fundo preto.

    A tela já reduz a foto antes de enviar; aqui é a garantia, para o que
    chegar sem essa redução. Levanta `ValueError` se não for uma imagem.
    """
    try:
        img = Image.open(io.BytesIO(dados))
        img.load()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as e:
        raise ValueError("Não consegui ler essa imagem. Envie JPG, PNG ou WebP.") from e
    img = ImageOps.exif_transpose(img)
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        fundo = Image.new("RGB", img.size, (255, 255, 255))
        fundo.paste(img, mask=img.getchannel("A"))
        img = fundo
    elif img.mode != "RGB":
        img = img.convert("RGB")
    img.thumbnail((FOTO_LADO_MAX, FOTO_LADO_MAX), Image.LANCZOS)
    saida = io.BytesIO()
    # Sem `exif=`: o arquivo novo nasce sem metadado nenhum.
    img.save(saida, "JPEG", quality=FOTO_QUALIDADE, optimize=True, progressive=True)
    return saida.getvalue()


@router.get("/opcoes")
async def opcoes(user=Depends(require_tenant_member)):
    return {k: [{"valor": v, "rotulo": r} for v, r in lista] for k, lista in OPCOES.items()}


@router.get("/veiculos")
async def listar(q: str = "", categoria: str = "", status: str = "", ordem: str = "recentes",
                 user=Depends(require_tenant_member)):
    db = get_db()
    todos = await db.veiculos.find({"tenant_id": user["tenant_id"]}, {"_id": 0}).to_list(5000)
    termos = _sem_acento(q).split()

    def casa(v):
        if categoria and v.get("categoria") != categoria:
            return False
        if status == "estoque":
            if v.get("status") == "vendido":
                return False
        elif status and v.get("status") != status:
            return False
        if termos:
            alvo = _sem_acento(" ".join(str(v.get(c) or "") for c in
                                        ("marca", "modelo", "versao", "placa", "cor", "ano_modelo")))
            return all(t in alvo for t in termos)
        return True

    lista = [_saida(v) for v in todos if casa(v)]
    chaves = {
        "recentes": (lambda v: v.get("created_at") or "", True),
        "preco_menor": (lambda v: v.get("preco") or 0, False),
        "preco_maior": (lambda v: v.get("preco") or 0, True),
        "km_menor": (lambda v: v.get("km") or 0, False),
        "mais_parados": (lambda v: v.get("dias_no_patio") or 0, True),
        "ano_maior": (lambda v: v.get("ano_modelo") or 0, True),
    }
    chave, desc = chaves.get(ordem, chaves["recentes"])
    lista.sort(key=chave, reverse=desc)
    # Destaque sobe para o começo sem desfazer a ordem escolhida entre os demais.
    lista.sort(key=lambda v: not v.get("destaque"))
    return lista


@router.get("/resumo")
async def resumo(user=Depends(require_tenant_member)):
    """Os números do pátio que o dono olha: o que tem, quanto vale, o que parou."""
    db = get_db()
    todos = [_saida(v) for v in await db.veiculos.find(
        {"tenant_id": user["tenant_id"]}, {"_id": 0}).to_list(5000)]
    no_patio = [v for v in todos if v.get("status") != "vendido"]
    vendidos = [v for v in todos if v.get("status") == "vendido"]
    mes = _hoje()[:7]
    valor = sum(v.get("preco") or 0 for v in no_patio)
    giro = [v["dias_no_patio"] for v in vendidos if v.get("dias_no_patio") is not None]
    por_categoria = {}
    for v in no_patio:
        c = v.get("categoria") or "outros"
        por_categoria[c] = por_categoria.get(c, 0) + 1
    return {
        "em_estoque": len(no_patio),
        "reservados": sum(1 for v in no_patio if v.get("status") == "reservado"),
        "entradas_mes": sum(1 for v in todos if (v.get("entrada_em") or "")[:7] == mes),
        "vendidos_mes": sum(1 for v in vendidos if (v.get("vendido_em") or "")[:7] == mes),
        "parados": sum(1 for v in no_patio if v["parado"]),
        "valor_parado": sum(v.get("preco") or 0 for v in no_patio if v["parado"]),
        "valor_patio": valor,
        "ticket_medio": (valor / len(no_patio)) if no_patio else 0,
        "giro_medio_dias": round(sum(giro) / len(giro)) if giro else None,
        "dias_medio_patio": (round(sum(v["dias_no_patio"] or 0 for v in no_patio) / len(no_patio))
                             if no_patio else None),
        "por_categoria": por_categoria,
        "parado_dias": PARADO_DIAS,
    }


@router.get("/veiculos/{veiculo_id}")
async def obter(veiculo_id: str, user=Depends(require_tenant_member)):
    return _saida(await _do_tenant(get_db(), veiculo_id, user["tenant_id"]))


@router.post("/veiculos")
async def criar(body: VeiculoIn, user=Depends(require_tenant_admin)):
    if not body.marca or not body.modelo:
        raise HTTPException(status_code=400, detail="Marca e modelo são obrigatórios.")
    db = get_db()
    dados = body.model_dump()
    dados["entrada_em"] = (body.entrada_em or date.today()).isoformat()
    dados["status"] = body.status or "disponivel"
    dados["destaque"] = bool(body.destaque)
    dados["opcionais"] = body.opcionais or []
    agora = _agora()
    v = {
        **dados,
        "id": str(uuid.uuid4()),
        "tenant_id": user["tenant_id"],
        "fotos": [],
        "vendido_em": _hoje() if dados["status"] == "vendido" else None,
        "created_at": agora,
        "updated_at": agora,
        "criado_por": user["id"],
    }
    await db.veiculos.insert_one(dict(v))
    return _saida(v)


@router.patch("/veiculos/{veiculo_id}")
async def editar(veiculo_id: str, body: VeiculoPatch, user=Depends(require_tenant_admin)):
    db = get_db()
    atual = await _do_tenant(db, veiculo_id, user["tenant_id"])
    # `exclude_unset`: só o que veio no corpo muda. Mandar `versao: null` apaga a
    # versão; não mandar deixa como está.
    mudancas = body.model_dump(exclude_unset=True)
    for obrigatorio in ("marca", "modelo"):
        if obrigatorio in mudancas and not mudancas[obrigatorio]:
            raise HTTPException(status_code=400, detail=f"{obrigatorio.capitalize()} é obrigatório.")
    if "entrada_em" in mudancas:
        mudancas["entrada_em"] = (mudancas["entrada_em"] or date.today()).isoformat()
    if "destaque" in mudancas:
        mudancas["destaque"] = bool(mudancas["destaque"])
    if "opcionais" in mudancas:
        mudancas["opcionais"] = mudancas["opcionais"] or []
    if "status" in mudancas and mudancas["status"] is None:
        mudancas.pop("status")
    mudancas.update(_transicao_status(atual, mudancas.get("status")))
    mudancas["updated_at"] = _agora()
    await db.veiculos.update_one({"id": veiculo_id, "tenant_id": user["tenant_id"]}, {"$set": mudancas})
    return _saida({**atual, **mudancas})


@router.delete("/veiculos/{veiculo_id}")
async def excluir(veiculo_id: str, user=Depends(require_tenant_admin)):
    db = get_db()
    v = await _do_tenant(db, veiculo_id, user["tenant_id"])
    await db.veiculos.delete_one({"id": veiculo_id, "tenant_id": user["tenant_id"]})
    # O documento da foto sai junto; o binário fica para a varredura de órfãos
    # do `media_retention`, que o recolhe em 24h. Apagar disco aqui trocaria uma
    # exclusão de banco por uma operação que pode falhar no meio.
    if v.get("fotos"):
        await db.media_files.delete_many(
            {"tenant_id": user["tenant_id"], "id": {"$in": v["fotos"]}, "uso": "veiculo"})
    return {"ok": True}


@router.post("/veiculos/{veiculo_id}/fotos")
async def subir_foto(veiculo_id: str, file: UploadFile = File(...), user=Depends(require_tenant_admin)):
    db = get_db()
    v = await _do_tenant(db, veiculo_id, user["tenant_id"])
    if len(v.get("fotos") or []) >= MAX_FOTOS:
        raise HTTPException(status_code=400, detail=f"Máximo de {MAX_FOTOS} fotos por veículo.")
    if media_store.classify(file.content_type, file.filename) != "image":
        raise HTTPException(status_code=400, detail="Envie uma imagem (JPG, PNG ou WebP).")
    original = await file.read(FOTO_ORIGINAL_MAX + 1)
    if len(original) > FOTO_ORIGINAL_MAX:
        raise HTTPException(status_code=400, detail="Foto acima de 25MB.")
    try:
        comprimida = comprimir_foto(original)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    nome = re.sub(r"\.[^.]+$", "", file.filename or "foto") + ".jpg"
    try:
        doc = await media_store.store_upload(
            db, user["tenant_id"], None, user["id"], nome, "image/jpeg", comprimida, kind="image")
    except media_store.MediaError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await db.media_files.update_one(
        {"id": doc["id"]}, {"$set": {"uso": "veiculo", "veiculo_id": veiculo_id}})
    await db.veiculos.update_one(
        {"id": veiculo_id, "tenant_id": user["tenant_id"]},
        {"$push": {"fotos": doc["id"]}, "$set": {"updated_at": _agora()}})
    return {"id": doc["id"], "fotos": (v.get("fotos") or []) + [doc["id"]]}


@router.delete("/veiculos/{veiculo_id}/fotos/{foto_id}")
async def apagar_foto(veiculo_id: str, foto_id: str, user=Depends(require_tenant_admin)):
    db = get_db()
    v = await _do_tenant(db, veiculo_id, user["tenant_id"])
    if foto_id not in (v.get("fotos") or []):
        raise HTTPException(status_code=404, detail="Foto não encontrada")
    fotos = [f for f in v["fotos"] if f != foto_id]
    await db.veiculos.update_one(
        {"id": veiculo_id, "tenant_id": user["tenant_id"]},
        {"$set": {"fotos": fotos, "updated_at": _agora()}})
    await db.media_files.delete_one({"id": foto_id, "tenant_id": user["tenant_id"], "uso": "veiculo"})
    return {"fotos": fotos}


@router.put("/veiculos/{veiculo_id}/fotos/ordem")
async def ordenar_fotos(veiculo_id: str, body: OrdemFotos, user=Depends(require_tenant_admin)):
    db = get_db()
    v = await _do_tenant(db, veiculo_id, user["tenant_id"])
    atuais = v.get("fotos") or []
    # A nova ordem tem de ser uma permutação da atual: nem foto de outro carro
    # entra, nem foto some por um id esquecido no corpo.
    if sorted(body.ids) != sorted(atuais):
        raise HTTPException(status_code=400, detail="A lista de fotos não confere com a do veículo.")
    await db.veiculos.update_one(
        {"id": veiculo_id, "tenant_id": user["tenant_id"]},
        {"$set": {"fotos": body.ids, "updated_at": _agora()}})
    return {"fotos": body.ids}
