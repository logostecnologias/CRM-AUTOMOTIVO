"""Conversões do funil devolvidas ao Meta, com Mongo falso e `_request` espionado."""
import asyncio
import hashlib
from datetime import datetime, timedelta, timezone

from fakedb import FakeDB
from fastapi import HTTPException

import db as db_mod
import cripto
import deals as dominio
import meta_conversoes as mc
import routes.deals as rd
import routes.meta_conversoes as rmc
import whatsapp_client as whatsapp

DB = FakeDB()
TENANT = "t-meta"
ADMIN = {"id": "u-1", "tenant_id": TENANT, "name": "Admin", "email": "a@x.com"}
enviados: list[dict] = []
recusar = {"sim": False}


def _conectar_fake():
    db_mod.get_db = lambda: DB
    rd.get_db = lambda: DB
    rmc.get_db = lambda: DB


async def espiao(metodo, caminho, token, *, json=None, **kw):
    if recusar["sim"]:
        raise whatsapp.WhatsAppError("Cloud API 400: permissão ausente")
    enviados.append({"caminho": caminho, "token": token, "corpo": json})
    return {"events_received": len(json["data"])}


def _h(v):
    return hashlib.sha256(v.encode()).hexdigest()


async def semear():
    DB._cols.clear()
    enviados.clear()
    await DB.tenants.insert_one({"id": TENANT})
    await DB.contacts.insert_one({
        "id": "c-anuncio", "tenant_id": TENANT, "nome": "Veio do anúncio",
        "numero_whatsapp": "5585999998888",
        "anuncio": {"ctwa_clid": "CLIQUE123", "waba_id": "WABA1",
                    "em": datetime.now(timezone.utc).isoformat()}})
    await DB.contacts.insert_one({
        "id": "c-site", "tenant_id": TENANT, "nome": "Veio do site",
        "numero_whatsapp": "5511988887777", "email": " Pessoa@Exemplo.com "})
    await DB.formulario_respostas.insert_one({
        "id": "r-1", "tenant_id": TENANT, "clique": {"fbclid": "FBCLID9"},
        "created_at": "2026-11-10T12:00:00+00:00"})


def test_formato_do_evento():
    ctt = {"id": "c", "numero_whatsapp": "55 (85) 99999-8888",
           "anuncio": {"ctwa_clid": "X", "waba_id": "W",
                       "em": datetime.now(timezone.utc).isoformat()}}
    ev = mc.montar_evento("Purchase", {"id": "d", "valor": 1500}, ctt, None)
    assert ev["action_source"] == "business_messaging"
    assert ev["messaging_channel"] == "whatsapp"
    assert ev["user_data"] == {"whatsapp_business_account_id": "W", "ctwa_clid": "X"}
    assert ev["custom_data"] == {"currency": "BRL", "value": 1500.0}
    assert ev["event_id"] == "d:Purchase"

    # Clique velho: o Meta não atribui mais, então casa pela pessoa.
    ctt["anuncio"]["em"] = (datetime.now(timezone.utc) - timedelta(days=8)).isoformat()
    ev = mc.montar_evento("LeadSubmitted", {"id": "d", "valor": 0}, ctt, None)
    assert ev["action_source"] == "system_generated"
    assert ev["event_name"] == "Lead"
    assert ev["user_data"]["ph"] == [_h("5585999998888")]
    assert "custom_data" not in ev


def test_evento_padrao_da_etapa():
    etapas = dominio.etapas_padrao()
    p = {"etapas": etapas}
    nomes = {e["nome"]: mc.evento_da_etapa(p, e) for e in etapas}
    assert nomes["Novo lead"] == "LeadSubmitted"
    assert nomes["Ganho"] == "Purchase"
    assert nomes["Perdido"] is None
    assert nomes["Proposta enviada"] is None
    escolhida = dict(etapas[2], evento_meta="InitiateCheckout")
    assert mc.evento_da_etapa(p, escolhida) == "InitiateCheckout"
    assert mc.evento_da_etapa(p, dict(etapas[0], evento_meta="")) is None


def test_funil_dispara_eventos():
    _conectar_fake()
    original = whatsapp._request
    whatsapp._request = espiao

    async def _tudo():
        await semear()
        funil = (await rd.list_pipelines(ADMIN))[0]
        etapa = {e["nome"]: e for e in funil["etapas"]}

        # Desligado: nada sai.
        d = await rd.create_deal(rd.DealIn(titulo="A", contact_id="c-anuncio",
                                           pipeline_id=funil["id"], valor=900), ADMIN)
        await mc.aguardar_pendentes()
        assert enviados == []

        try:
            await rmc.salvar(rmc.ConfigIn(ativo=True, dataset_id=""), ADMIN)
            assert False, "ativou sem dataset"
        except HTTPException as e:
            assert e.status_code == 400

        cfg = await rmc.salvar(rmc.ConfigIn(ativo=True, dataset_id="123456789",
                                            token="EAAtokenlongo123456"), ADMIN)
        assert cfg["token"].startswith("EAAtoke") and "123456" not in cfg["token"][8:]

        # Ganho de quem veio do anúncio: Purchase ligado ao clique, com valor.
        await rd.update_deal(d["id"], rd.DealPatch(etapa_id=etapa["Ganho"]["id"]), ADMIN)
        await mc.aguardar_pendentes()
        assert len(enviados) == 1
        env = enviados[0]
        assert env["caminho"] == "/123456789/events"
        assert env["token"] == "EAAtokenlongo123456"
        ev = env["corpo"]["data"][0]
        assert ev["event_name"] == "Purchase"
        assert ev["user_data"]["ctwa_clid"] == "CLIQUE123"
        assert ev["custom_data"]["value"] == 900.0

        # Voltar e ganhar de novo não vira segunda venda.
        await rd.update_deal(d["id"], rd.DealPatch(etapa_id=etapa["Negociação"]["id"]), ADMIN)
        await rd.update_deal(d["id"], rd.DealPatch(etapa_id=etapa["Ganho"]["id"]), ADMIN)
        await mc.aguardar_pendentes()
        assert len(enviados) == 1

        # Lead do site: entra em "Novo lead" e sai como Lead com hash e fbc.
        await rd.create_deal(rd.DealIn(titulo="B", contact_id="c-site",
                                       pipeline_id=funil["id"]), ADMIN)
        await mc.aguardar_pendentes()
        assert len(enviados) == 2
        ev = enviados[1]["corpo"]["data"][0]
        assert ev["event_name"] == "Lead"
        assert ev["user_data"]["em"] == [_h("pessoa@exemplo.com")]
        assert ev["user_data"]["ph"] == [_h("5511988887777")]

        # fbc vem do formulário que gerou o negócio.
        await DB.deals.insert_one({"id": "d-form", "tenant_id": TENANT,
                                   "pipeline_id": funil["id"], "contact_id": "c-site",
                                   "etapa_id": etapa["Ganho"]["id"], "valor": 50,
                                   "formulario_resposta_id": "r-1"})
        await mc.ao_mudar_etapa(DB, TENANT, "d-form")
        ev = enviados[2]["corpo"]["data"][0]
        assert ev["user_data"]["fbc"].endswith(".FBCLID9")

        # Perdido não dispara nada por padrão.
        d3 = await rd.create_deal(rd.DealIn(titulo="C", contact_id="c-anuncio",
                                            pipeline_id=funil["id"],
                                            etapa_id=etapa["Contato feito"]["id"]), ADMIN)
        await rd.update_deal(d3["id"], rd.DealPatch(etapa_id=etapa["Perdido"]["id"]), ADMIN)
        await mc.aguardar_pendentes()
        assert len(enviados) == 3

        # Falha do Meta fica registrada e não impede a mudança de etapa.
        recusar["sim"] = True
        d4 = await rd.create_deal(rd.DealIn(titulo="D", contact_id="c-site",
                                            pipeline_id=funil["id"],
                                            etapa_id=etapa["Ganho"]["id"]), ADMIN)
        await mc.aguardar_pendentes()
        recusar["sim"] = False
        assert d4["status"] == "ganho"
        log = (await rmc.eventos(ADMIN))["items"]
        erro = [x for x in log if x["deal_id"] == d4["id"]][0]
        assert erro["status"] == "erro" and "permissão" in erro["erro"]

        # Etapa configurada como "nenhum" deixa de disparar.
        etapas = [rd.EtapaIn(**{**e, "evento_meta": "" if e["nome"] == "Novo lead"
                                else e.get("evento_meta")}) for e in funil["etapas"]]
        await rd.update_pipeline(funil["id"], rd.PipelineIn(nome=funil["nome"], etapas=etapas),
                                 None, ADMIN)
        antes = len(enviados)
        await rd.create_deal(rd.DealIn(titulo="E", contact_id="c-anuncio",
                                       pipeline_id=funil["id"]), ADMIN)
        await mc.aguardar_pendentes()
        assert len(enviados) == antes

        # Isolamento: a configuração de uma empresa não aparece para outra.
        outra = await rmc.ler({"id": "u-2", "tenant_id": "t-outra"})
        assert outra["ativo"] is False and outra["dataset_id"] == ""

    try:
        asyncio.run(_tudo())
    finally:
        whatsapp._request = original


def test_referral_do_webhook():
    assert mc.anuncio_do_referral({"source_type": "post"}, "W") is None
    a = mc.anuncio_do_referral({"ctwa_clid": "ABC", "source_id": "120",
                                "source_type": "ad", "headline": "Promo"}, "W")
    assert a["ctwa_clid"] == "ABC" and a["waba_id"] == "W" and a["titulo"] == "Promo"


def test_token_cifrado():
    bloco = cripto.cifrar("EAAsegredo")
    assert "EAAsegredo" not in str(bloco)
