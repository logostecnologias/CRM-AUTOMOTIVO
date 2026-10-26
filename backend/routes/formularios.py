"""Formulários de site: o endereço público que recebe o lead e a configuração.

Dois públicos num arquivo, como o telefone:

  - **O site** (qualquer um: página feita à mão, Elementor, Webflow, n8n)
    manda o formulário preenchido para `POST /api/f/{chave}`. Sem login: a
    chave está no código da página e é tudo o que identifica o formulário. Em
    `GET /api/f/{chave}/script.js` há um script opcional que guarda a origem
    (UTM, clique de anúncio) e envia sozinho os `<form data-zappzen>`.

  - **O admin da empresa** cria e configura em `/api/formularios/*`: o que
    acontece com o lead (etiquetas, responsável, funil, tarefa, WhatsApp) e de
    quais domínios o envio é aceito.

O CORS de `/api/f/` é aberto (`*`, sem credencial) e mora em `server.py`: o
resto da API só aceita a origem do painel, e o site do cliente é outra.
"""
import json
import logging
import os
import re
import uuid
from datetime import datetime, timezone
from urllib.parse import parse_qsl, urlparse

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from pydantic import BaseModel, Field

import datas
import formularios
from auth import _client_ip, require_tenant_admin
from db import get_db

logger = logging.getLogger("zappzen.formularios.rotas")

router = APIRouter(tags=["formularios"])


def _now():
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Endereço público
# ---------------------------------------------------------------------------

async def _corpo(request: Request) -> dict:
    """O formulário enviado, em qualquer um dos formatos que um site manda.

    JSON (o `fetch` comum), `text/plain` com JSON dentro (o que o nosso script
    usa, porque não dispara preflight e sobrevive à troca de página com
    `keepalive`) e o POST de `<form>` puro, urlencoded ou multipart. O teto é
    aplicado durante a leitura, como no upload de mídia: com ele só no fim, um
    corpo gigante já teria passado inteiro pela memória.
    """
    declarado = request.headers.get("content-length")
    if declarado and declarado.isdigit() and int(declarado) > formularios.MAX_BYTES:
        raise HTTPException(status_code=413, detail="Envio grande demais")
    pedacos, total = [], 0
    async for pedaco in request.stream():
        total += len(pedaco)
        if total > formularios.MAX_BYTES:
            raise HTTPException(status_code=413, detail="Envio grande demais")
        pedacos.append(pedaco)
    bruto = b"".join(pedacos)
    # O `form()` do Starlette relê o corpo de `_body` quando ele já foi lido.
    request._body = bruto

    tipo = (request.headers.get("content-type") or "").lower()
    if "multipart/form-data" in tipo:
        form = await request.form()
        dados: dict = {}
        for k, v in form.multi_items():
            if isinstance(v, str):  # arquivo anexado é ignorado
                dados[k] = f"{dados[k]}, {v}" if k in dados else v
        return dados
    if "application/x-www-form-urlencoded" in tipo:
        dados = {}
        for k, v in parse_qsl(bruto.decode("utf-8", "replace"), keep_blank_values=True):
            dados[k] = f"{dados[k]}, {v}" if dados.get(k) else v
        return dados
    try:
        dados = json.loads(bruto.decode("utf-8") or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise HTTPException(status_code=400, detail="Envio ilegível: mande JSON ou formulário")
    if not isinstance(dados, dict):
        raise HTTPException(status_code=400, detail="Envio ilegível: o JSON precisa ser um objeto")
    # `{"campos": {...}}` é o formato de quem integra por automação e agrupa.
    if isinstance(dados.get("campos"), dict) and len(dados) <= 3:
        dados = {**{k: v for k, v in dados.items() if k != "campos"}, **dados["campos"]}
    return dados


def _quer_html(request: Request) -> bool:
    """POST de `<form>` sem JavaScript: o navegador espera uma página de volta."""
    tipo = (request.headers.get("content-type") or "").lower()
    return ("application/x-www-form-urlencoded" in tipo or "multipart/form-data" in tipo) \
        and "text/html" in (request.headers.get("accept") or "")


_OBRIGADO = """<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Recebido</title>
<style>body{font-family:system-ui,sans-serif;display:flex;min-height:100vh;align-items:center;
justify-content:center;margin:0;padding:16px;text-align:center}</style></head>
<body><div><h1>Recebemos seus dados</h1><p>Em breve entraremos em contato.</p></div></body></html>"""


@router.post("/api/f/{chave}")
async def receber(chave: str, request: Request, bg: BackgroundTasks):
    db = get_db()
    formulario = await db.formularios.find_one({"chave": chave}, {"_id": 0}) \
        if chave.startswith(formularios.PREFIXO_CHAVE) else None
    if not formulario:
        raise HTTPException(status_code=404, detail="Formulário não encontrado")
    if not formulario.get("ativo"):
        raise HTTPException(status_code=403, detail="Formulário desativado")

    origem = request.headers.get("origin") or request.headers.get("referer")
    if not formularios.dominio_permitido(formulario.get("dominios") or [], origem):
        raise HTTPException(status_code=403, detail="Domínio não autorizado para este formulário")
    if not formularios.freio(_client_ip(request), formulario["id"]):
        raise HTTPException(status_code=429, detail="Muitos envios. Tente de novo em alguns minutos.",
                            headers={"Retry-After": "600"})

    payload = await _corpo(request)
    if payload.get(formularios.HONEYPOT):
        # Robô: responde como se tivesse dado certo, para ele não aprender a
        # contornar, e não grava nada.
        return {"ok": True}

    resposta = await formularios.receber(db, formulario, payload)
    if resposta.get("whatsapp_status") == formularios.WPP_PENDENTE and not resposta.get("complemento"):
        bg.add_task(formularios.enviar_whatsapp, db, formulario["tenant_id"], resposta["id"])

    if resposta["status"] == formularios.RECUSADA:
        # O site precisa saber, para mostrar "confira o telefone" a quem digitou.
        return JSONResponse(status_code=422, content={"ok": False, "erro": resposta["erro"]})
    if _quer_html(request):
        destino = formulario.get("redirecionar_para")
        if destino:
            return RedirectResponse(destino, status_code=303)
        return HTMLResponse(_OBRIGADO)
    return {"ok": True}


_SCRIPT = r"""/* ZappZen: envio de formulário e origem do lead. */
(function () {
  var ENDPOINT = "__ENDPOINT__";
  var CHAVE = "zz_origem";
  var DIAS = 30;
  var PARAMS = ["utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
                "gclid", "gbraid", "wbraid", "fbclid", "ttclid", "msclkid"];

  // A origem é guardada no navegador: quem chega pelo anúncio e navega até a
  // página do formulário perde os parâmetros da URL no caminho.
  function daUrl() {
    var q = new URLSearchParams(location.search), o = {}, tem = false;
    PARAMS.forEach(function (p) { var v = q.get(p); if (v) { o[p] = v; tem = true; } });
    if (!tem) return null;
    o._em = Date.now(); o._entrada = location.href; o._referrer = document.referrer || "";
    return o;
  }
  var atual = daUrl();
  if (atual) { try { localStorage.setItem(CHAVE, JSON.stringify(atual)); } catch (e) {} }

  function origem() {
    var o = atual;
    if (!o) { try { o = JSON.parse(localStorage.getItem(CHAVE) || "null"); } catch (e) { o = null; } }
    if (o && o._em && Date.now() - o._em > DIAS * 864e5) o = null;
    return o || {};
  }

  function enviar(dados) {
    var corpo = {}, k, o = origem();
    for (k in dados) { if (Object.prototype.hasOwnProperty.call(dados, k)) corpo[k] = dados[k]; }
    PARAMS.forEach(function (p) { if (o[p] && !corpo[p]) corpo[p] = o[p]; });
    if (!corpo._pagina) corpo._pagina = location.href;
    if (!corpo._referrer) corpo._referrer = o._referrer || document.referrer || "";
    if (o._entrada && !corpo._entrada) corpo._entrada = o._entrada;
    // text/plain não dispara preflight, e keepalive deixa o envio terminar
    // mesmo que o formulário troque de página logo em seguida.
    return fetch(ENDPOINT, {
      method: "POST", keepalive: true,
      headers: { "Content-Type": "text/plain;charset=UTF-8" },
      body: JSON.stringify(corpo)
    }).then(function (r) {
      return r.json().catch(function () { return { ok: r.ok }; });
    });
  }

  function lerForm(form) {
    var o = {};
    new FormData(form).forEach(function (v, k) {
      if (typeof v !== "string") return;
      o[k] = o[k] ? o[k] + ", " + v : v;
    });
    return o;
  }

  // Só os formulários marcados: o site pode ter busca, newsletter e login na
  // mesma página, e nenhum deles é lead.
  document.addEventListener("submit", function (ev) {
    var f = ev.target;
    if (!f || !f.hasAttribute || !f.hasAttribute("data-zappzen")) return;
    enviar(lerForm(f)).catch(function () {});
  }, true);

  window.ZappZen = { enviar: enviar, origem: origem };
})();
"""


@router.get("/api/f/{chave}/script.js")
async def script(chave: str, request: Request):
    """O script que o site inclui. Sem segredo nenhum: só o endereço de envio.

    Não confere se a chave existe, de propósito: um 404 aqui viraria erro no
    console de toda página que o inclui, e quem precisa saber se a chave está
    certa é o envio, que já responde 404.
    """
    if not chave.startswith(formularios.PREFIXO_CHAVE) or len(chave) > 60:
        raise HTTPException(status_code=404, detail="Formulário não encontrado")
    # Atrás do Caddy o esquema visto é http; o público é o do PUBLIC_BASE_URL.
    publico = (os.environ.get("PUBLIC_BASE_URL") or "").rstrip("/")         or str(request.base_url).rstrip("/")
    corpo = _SCRIPT.replace("__ENDPOINT__", f"{publico}/api/f/{chave}")
    return Response(content=corpo, media_type="application/javascript", headers={
        "Cache-Control": "public, max-age=300",
    })


# ---------------------------------------------------------------------------
# Configuração (admin da empresa)
# ---------------------------------------------------------------------------

class NegocioIn(BaseModel):
    ativo: bool = False
    pipeline_id: str | None = None
    etapa_id: str | None = None
    valor: float = Field(0, ge=0)
    titulo: str = Field("", max_length=200)


class TarefaIn(BaseModel):
    ativo: bool = False
    # Até uma semana: "retornar o lead" depois disso já não é retorno.
    prazo_min: int = Field(30, ge=0, le=10080)
    titulo: str = Field("", max_length=200)


class TemplateIn(BaseModel):
    nome: str = ""
    idioma: str = "pt_BR"
    variaveis: list[str] = Field(default_factory=list, max_length=10)


class WhatsappIn(BaseModel):
    ativo: bool = False
    connection_id: str | None = None
    mensagem: str = Field("", max_length=1000)
    template: TemplateIn = Field(default_factory=TemplateIn)
    resposta_modo: str = "agente"
    bot_id: str | None = None


class FormularioIn(BaseModel):
    nome: str = Field(..., min_length=1, max_length=80)
    ativo: bool = True
    tags: list[str] = Field(default_factory=list, max_length=20)
    responsavel_id: str | None = None
    dominios: list[str] = Field(default_factory=list, max_length=20)
    redirecionar_para: str | None = Field(None, max_length=500)
    negocio: NegocioIn = Field(default_factory=NegocioIn)
    tarefa: TarefaIn = Field(default_factory=TarefaIn)
    whatsapp: WhatsappIn = Field(default_factory=WhatsappIn)


async def _validar(db, tenant_id: str, body: FormularioIn, formulario_id: str | None) -> dict:
    """O documento a gravar, ou recusa dizendo o que falta."""
    nome = body.nome.strip()
    if not nome:
        raise HTTPException(status_code=400, detail="Dê um nome ao formulário")
    # Nome repetido: a tela de respostas e o relatório separam por nome, e dois
    # "LP Lançamento" seriam indistinguíveis.
    repetido = await db.formularios.find_one({
        "tenant_id": tenant_id, "id": {"$ne": formulario_id},
        "nome": {"$regex": f"^{re.escape(nome)}$", "$options": "i"},
    }, {"_id": 0, "id": 1})
    if repetido:
        raise HTTPException(status_code=409, detail="Já existe um formulário com este nome")

    if body.responsavel_id and not await db.users.find_one(
            {"id": body.responsavel_id, "tenant_id": tenant_id}, {"_id": 0, "id": 1}):
        raise HTTPException(status_code=400, detail="Responsável inválido")
    if body.tarefa.ativo and not body.responsavel_id:
        raise HTTPException(
            status_code=400,
            detail="Escolha um responsável: a tarefa de retorno precisa de alguém para aparecer na agenda")

    if body.negocio.ativo:
        pipeline = await db.pipelines.find_one(
            {"id": body.negocio.pipeline_id, "tenant_id": tenant_id}, {"_id": 0}) \
            if body.negocio.pipeline_id else None
        if not pipeline:
            raise HTTPException(status_code=400, detail="Escolha o funil do negócio")
        if body.negocio.etapa_id and not any(
                e["id"] == body.negocio.etapa_id for e in pipeline.get("etapas") or []):
            raise HTTPException(status_code=400, detail="Etapa inválida para este funil")

    w = body.whatsapp
    if w.resposta_modo not in formularios.MODOS:
        raise HTTPException(status_code=400, detail="Escolha quem atende a resposta")
    if w.ativo and w.resposta_modo == "bot":
        if not w.bot_id or not await db.bots.find_one(
                {"id": w.bot_id, "tenant_id": tenant_id}, {"_id": 0, "id": 1}):
            raise HTTPException(status_code=400, detail="Escolha o robô que atende a resposta")
    if w.connection_id and not await db.whatsapp_connections.find_one(
            {"id": w.connection_id, "tenant_id": tenant_id}, {"_id": 0, "id": 1}):
        raise HTTPException(status_code=400, detail="Conexão de WhatsApp não encontrada")

    destino = (body.redirecionar_para or "").strip() or None
    if destino:
        partes = urlparse(destino)
        if partes.scheme not in ("http", "https") or not partes.netloc:
            raise HTTPException(status_code=400,
                                detail="O endereço de redirecionamento precisa começar com https://")

    dominios = []
    for d in body.dominios:
        limpo = formularios.normaliza_dominio(d)
        if limpo and limpo not in dominios:
            dominios.append(limpo)

    vistas, tags = set(), []
    for t in body.tags:
        limpa = (t or "").strip()
        if limpa and limpa.lower() not in vistas:
            vistas.add(limpa.lower())
            tags.append(limpa)

    doc = body.model_dump()
    doc.update(nome=nome, dominios=dominios, tags=tags, redirecionar_para=destino)
    doc["whatsapp"]["template"]["nome"] = doc["whatsapp"]["template"]["nome"].strip()
    if w.resposta_modo != "bot":
        doc["whatsapp"]["bot_id"] = None
    if not body.negocio.ativo:
        doc["negocio"].update(pipeline_id=None, etapa_id=None)
    return doc


async def _do_tenant(db, tenant_id: str, formulario_id: str) -> dict:
    formulario = await db.formularios.find_one(
        {"id": formulario_id, "tenant_id": tenant_id}, {"_id": 0})
    if not formulario:
        raise HTTPException(status_code=404, detail="Formulário não encontrado")
    return formulario


@router.get("/api/formularios")
async def listar(user=Depends(require_tenant_admin)):
    db = get_db()
    tenant_id = user["tenant_id"]
    lista = await db.formularios.find(
        {"tenant_id": tenant_id}, {"_id": 0}).sort("created_at", 1).to_list(200)
    # Contagem e última resposta de todos de uma vez, não uma consulta por
    # cartão: o banco está atrás de um túnel SSH e o que pesa é a ida e volta.
    contagem: dict[str, dict] = {}
    async for row in db.formulario_respostas.aggregate([
        {"$match": {"tenant_id": tenant_id, "status": formularios.RECEBIDA}},
        {"$group": {"_id": "$formulario_id", "n": {"$sum": 1},
                    "ultima": {"$max": "$created_at"}}},
    ]):
        contagem[row["_id"]] = row
    for f in lista:
        f["respostas"] = (contagem.get(f["id"]) or {}).get("n", 0)
        f["ultima_resposta"] = (contagem.get(f["id"]) or {}).get("ultima")
    return lista


@router.post("/api/formularios")
async def criar(body: FormularioIn, user=Depends(require_tenant_admin)):
    db = get_db()
    tenant_id = user["tenant_id"]
    doc = await _validar(db, tenant_id, body, None)
    doc.update({
        "id": str(uuid.uuid4()),
        "tenant_id": tenant_id,
        "chave": formularios.nova_chave(),
        "criado_por": user["id"],
        "created_at": _now(),
        "updated_at": _now(),
    })
    await db.formularios.insert_one(dict(doc))
    doc.pop("_id", None)
    return doc


@router.get("/api/formularios/resumo")
async def resumo(de: str | None = None, ate: str | None = None,
                 formulario_id: str | None = None, user=Depends(require_tenant_admin)):
    # Instante, não dia: o corte de "este mês" vem do navegador já no fuso de
    # quem olha, como no telefone e nos relatórios.
    return await formularios.resumo(get_db(), user["tenant_id"],
                                    datas.para_utc(de, "Início"), datas.para_utc(ate, "Fim"),
                                    formulario_id)


@router.get("/api/formularios/{formulario_id}")
async def detalhe(formulario_id: str, user=Depends(require_tenant_admin)):
    return await _do_tenant(get_db(), user["tenant_id"], formulario_id)


@router.put("/api/formularios/{formulario_id}")
async def salvar(formulario_id: str, body: FormularioIn, user=Depends(require_tenant_admin)):
    db = get_db()
    tenant_id = user["tenant_id"]
    atual = await _do_tenant(db, tenant_id, formulario_id)
    doc = await _validar(db, tenant_id, body, formulario_id)
    doc["updated_at"] = _now()
    await db.formularios.update_one({"id": formulario_id, "tenant_id": tenant_id}, {"$set": doc})
    return {**atual, **doc}


@router.post("/api/formularios/{formulario_id}/chave")
async def trocar_chave(formulario_id: str, user=Depends(require_tenant_admin)):
    """Gera uma chave nova; a anterior para de funcionar na hora.

    É a saída para chave abusada (alguém despejando lead falso). O site
    precisa ser atualizado com a nova, e a tela diz isso antes de trocar.
    """
    db = get_db()
    tenant_id = user["tenant_id"]
    atual = await _do_tenant(db, tenant_id, formulario_id)
    chave = formularios.nova_chave()
    await db.formularios.update_one({"id": formulario_id, "tenant_id": tenant_id},
                                    {"$set": {"chave": chave, "updated_at": _now()}})
    return {**atual, "chave": chave}


@router.delete("/api/formularios/{formulario_id}")
async def excluir(formulario_id: str, user=Depends(require_tenant_admin)):
    """Apaga o formulário. As respostas ficam.

    Elas são a origem de contatos e negócios que continuam existindo, e o
    relatório de campanha depende delas: apagar o formulário não pode mudar
    quanto a campanha de agosto vendeu.
    """
    db = get_db()
    tenant_id = user["tenant_id"]
    await _do_tenant(db, tenant_id, formulario_id)
    await db.formularios.delete_one({"id": formulario_id, "tenant_id": tenant_id})
    return {"ok": True}


@router.get("/api/formularios/{formulario_id}/respostas")
async def respostas(formulario_id: str, limite: int = 50, user=Depends(require_tenant_admin)):
    db = get_db()
    tenant_id = user["tenant_id"]
    await _do_tenant(db, tenant_id, formulario_id)
    linhas = await db.formulario_respostas.find(
        {"tenant_id": tenant_id, "formulario_id": formulario_id}, {"_id": 0},
    ).sort([("created_at", -1), ("_id", -1)]).limit(max(1, min(limite, 200))).to_list(200)
    ids = list({l["contact_id"] for l in linhas if l.get("contact_id")})
    nomes = {
        c["id"]: c.get("nome")
        async for c in db.contacts.find({"tenant_id": tenant_id, "id": {"$in": ids}},
                                        {"_id": 0, "id": 1, "nome": 1})
    } if ids else {}
    for l in linhas:
        l["contato_nome"] = nomes.get(l.get("contact_id"))
    return linhas
