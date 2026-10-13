"""Agente de IA lendo o anexo do contato: audio transcrito e foto vista.

Exercita o caminho inteiro, por dentro de `handle_incoming_message`: a midia e
baixada (download da Meta dublado), gravada em disco de verdade, e so entao o
agente decide. O provedor de conversa e o de transcricao sao dublados; o que
fica provado e o que este sistema faz com o que eles devolvem:

  - o audio vira texto uma vez so, gravado na mensagem, e entra no historico;
  - a foto vai como imagem so para modelo que enxerga, e so as ultimas;
  - nenhum anexo ilegivel e respondido como se tivesse sido entendido;
  - quem paga a transcricao e medido como quem paga a resposta.
"""
import asyncio
import io
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

import test_ia_agentes as base  # andaime: Mongo falso, IA dublada, envio dublado

from PIL import Image

import ai_client
import ai_credentials
import ai_midia
import ai_runtime
import flow_runtime
import routes.ai as rai

DB, IA, TENANT, ADMIN = base.DB, base.IA, base.TENANT, base.ADMIN
check, receber, sessao, sistemas, semear = (base.check, base.receber, base.sessao,
                                            base.sistemas, base.semear)

# media_id da Meta -> (mime, bytes). O download dublado devolve daqui.
ARQUIVOS: dict[str, tuple[str, bytes]] = {}
TRANSCRICOES: list[dict] = []


def _png(cor=(200, 30, 30), tamanho=(2400, 1600)) -> bytes:
    saida = io.BytesIO()
    Image.new("RGB", tamanho, cor).save(saida, "PNG")
    return saida.getvalue()


async def fake_baixar_midia(cred, media_id):
    mime, dados = ARQUIVOS[media_id]

    async def pedacos():
        yield dados

    return {"mime_type": mime}, pedacos()


class _Transcritor:
    """Substitui `ai_client.transcrever`: a resolucao de credencial e a medicao
    em `ai_runtime` rodam de verdade."""

    def __init__(self):
        self.texto = "oi, queria saber o preco do onix prata"
        self.erro = None

    async def __call__(self, provedor, chave, caminho, nome_arquivo):
        TRANSCRICOES.append({"provedor": provedor, "chave": chave,
                             "nome": nome_arquivo, "existe": os.path.exists(caminho)})
        if self.erro:
            raise self.erro
        return ai_client.Transcricao(texto=self.texto, modelo="whisper-large-v3-turbo",
                                     segundos=42.0)


TRANSCRITOR = _Transcritor()


def _conectar():
    base._conectar_fake()
    flow_runtime.whatsapp.baixar_midia = fake_baixar_midia
    ai_client.transcrever = TRANSCRITOR


_seq = 0


async def mandar(kind, mime, dados, legenda="", numero=base.NUM):
    global _seq
    _seq += 1
    mid = f"meta-{_seq}"
    ARQUIVOS[mid] = (mime, dados)
    await receber(legenda, numero=numero,
                  media={"kind": kind, "media_id": mid, "mime": mime})


def _agente(provedor="groq", modelo="openai/gpt-oss-120b", chave="gsk_CHAVE", **extra):
    return {"provedor": provedor, "modelo": modelo,
            "credencial": ai_credentials.cifrar(chave), "credencial_status": "ok", **extra}


async def _semear(agente):
    await semear(agente=agente)
    TRANSCRICOES.clear()
    TRANSCRITOR.erro = None
    TRANSCRITOR.texto = "oi, queria saber o preco do onix prata"
    for k in ("AI_TRANSCRICAO_KEY", "AI_TRANSCRICAO_PROVIDER", "AI_PLATFORM_KEY",
              "AI_PLATFORM_PROVIDER"):
        os.environ.pop(k, None)


async def _recebidas(session_id):
    return await DB.messages_log.find(
        {"session_id": session_id, "direction": "recebida"}).to_list(50)


# ---------------------------------------------------------------------------

async def etapa_audio_transcrito():
    print("\n[audio vira texto e o agente responde]")
    await _semear(_agente())
    await mandar("audio", "audio/ogg", b"OggS-nota-de-voz")
    s = await sessao()
    check("o agente respondeu", len(IA.chamadas) == 1, IA.chamadas)
    ultimo = IA.chamadas[-1]["historico"][-1]
    check("a fala transcrita chega ao modelo",
          "onix prata" in ultimo["content"] and "transcrito" in ultimo["content"], ultimo)
    check("transcrito com a chave do proprio agente (Groq transcreve)",
          TRANSCRICOES[-1]["chave"] == "gsk_CHAVE" and TRANSCRICOES[-1]["provedor"] == "groq",
          TRANSCRICOES)
    check("arquivo mandado com a extensao que o provedor reconhece",
          TRANSCRICOES[-1]["nome"].endswith(".ogg") and TRANSCRICOES[-1]["existe"], TRANSCRICOES)
    msg = (await _recebidas(s["id"]))[-1]
    check("transcricao gravada na mensagem (a Central le a mesma)",
          msg["meta"].get("transcricao") == TRANSCRITOR.texto, msg["meta"])

    uso = await DB.ai_usage.find({"tenant_id": TENANT, "modelo": "whisper-large-v3-turbo"}).to_list(5)
    check("transcricao medida em segundos e custo, na conta do cliente",
          len(uso) == 1 and uso[0]["segundos_audio"] == 42.0 and uso[0]["custo_usd"] > 0
          and uso[0]["origem"] == ai_runtime.ORIGEM_CLIENTE, uso)

    await receber("e tem em azul?")
    check("o audio antigo nao e transcrito de novo", len(TRANSCRICOES) == 1, TRANSCRICOES)
    hist = IA.chamadas[-1]["historico"]
    check("mas continua no historico como texto",
          any("onix prata" in t["content"] for t in hist), hist)


async def etapa_audio_ilegivel():
    print("\n[audio que nao da para entender vai para uma pessoa]")
    await _semear(_agente())
    TRANSCRITOR.erro = ai_client.IAError("A conta no provedor está sem saldo")
    await mandar("audio", "audio/ogg", b"OggS")
    s = await sessao()
    check("o agente nao responde", len(IA.chamadas) == 0, IA.chamadas)
    check("vai para a fila", s["status_atendimento"] == "aguardando", s)
    check("com o motivo da falha no historico",
          any("não transcrito" in m and "sem saldo" in m for m in await sistemas(s["id"])),
          await sistemas(s["id"]))
    msg = (await _recebidas(s["id"]))[-1]
    check("falha marcada, para nao cobrar de novo a cada resposta",
          "sem saldo" in (msg["meta"].get("transcricao_erro") or ""), msg["meta"])

    print("\n[pedido de gente feito em audio]")
    await _semear(_agente())
    TRANSCRITOR.texto = "quero falar com um atendente por favor"
    await mandar("audio", "audio/ogg", b"OggS")
    s = await sessao()
    check("atalhado antes do provedor", len(IA.chamadas) == 0, IA.chamadas)
    check("e vai para a fila", s["status_atendimento"] == "aguardando", s)

    print("\n[sem conta que transcreva]")
    await _semear(_agente(provedor="anthropic", modelo="claude-haiku-4-5", chave="sk-ant-x"))
    await mandar("audio", "audio/ogg", b"OggS")
    s = await sessao()
    check("chave da Anthropic nao e mandada a transcricao", len(TRANSCRICOES) == 0, TRANSCRICOES)
    check("e o motivo diz o que falta",
          any("OpenAI ou da Groq" in m for m in await sistemas(s["id"])),
          await sistemas(s["id"]))

    print("\n[chave de transcricao da plataforma]")
    await _semear(_agente(provedor="anthropic", modelo="claude-haiku-4-5", chave="sk-ant-x"))
    os.environ["AI_TRANSCRICAO_KEY"] = "gsk_PLATAFORMA"
    await mandar("audio", "audio/ogg", b"OggS")
    check("a plataforma transcreve quando o agente nao consegue",
          TRANSCRICOES and TRANSCRICOES[-1]["chave"] == "gsk_PLATAFORMA", TRANSCRICOES)
    check("e o agente responde", len(IA.chamadas) == 1, IA.chamadas)
    uso = await DB.ai_usage.find({"tenant_id": TENANT, "modelo": "whisper-large-v3-turbo"}).to_list(5)
    check("medida como consumo da plataforma",
          uso and uso[0]["origem"] == ai_runtime.ORIGEM_PLATAFORMA, uso)

    print("\n[audio desligado no agente]")
    await _semear(_agente(audio_ativo=False))
    await mandar("audio", "audio/ogg", b"OggS")
    s = await sessao()
    check("nao transcreve", len(TRANSCRICOES) == 0, TRANSCRICOES)
    check("vai para a fila dizendo por que",
          any("não ouvir" in m for m in await sistemas(s["id"])), await sistemas(s["id"]))


async def etapa_foto_vista():
    print("\n[foto vai como imagem para modelo que enxerga]")
    await _semear(_agente(provedor="anthropic", modelo="claude-haiku-4-5", chave="sk-ant-x"))
    await mandar("image", "image/png", _png())
    s = await sessao()
    check("o agente respondeu a foto sem legenda", len(IA.chamadas) == 1, IA.chamadas)
    turno = IA.chamadas[-1]["historico"][-1]
    imgs = turno.get("imagens") or []
    check("com a imagem no turno", len(imgs) == 1, turno.keys())
    check("reduzida e em JPEG", imgs and imgs[0]["mime"] == "image/jpeg", imgs[:1])
    if imgs:
        import base64
        reduzida = Image.open(io.BytesIO(base64.b64decode(imgs[0]["b64"])))
        check("lado maior no teto", max(reduzida.size) == ai_midia.LADO_MAX, reduzida.size)
    check("o prompt diz que ele ve a foto",
          "você a vê" in IA.chamadas[-1]["instrucoes"], "")

    print("\n[so as ultimas fotos vao como imagem]")
    for cor in ((1, 2, 3), (4, 5, 6), (7, 8, 9)):
        await mandar("image", "image/png", _png(cor, (50, 50)), legenda="e essa?")
    hist = IA.chamadas[-1]["historico"]
    total = sum(len(t.get("imagens") or []) for t in hist)
    check(f"no maximo {ai_midia.MAX_IMAGENS} imagens", total == ai_midia.MAX_IMAGENS, total)
    check("a mais antiga vira aviso de texto",
          any("não consegue ver" in t["content"] for t in hist), [t["content"] for t in hist])

    print("\n[modelo que nao enxerga]")
    await _semear(_agente(provedor="deepseek", modelo="deepseek-chat", chave="sk-x"))
    await mandar("image", "image/png", _png())
    s = await sessao()
    check("foto sem legenda nao e respondida", len(IA.chamadas) == 0, IA.chamadas)
    check("vai para a fila dizendo que o modelo nao enxerga",
          any("não enxerga" in m for m in await sistemas(s["id"])), await sistemas(s["id"]))

    await _semear(_agente(provedor="deepseek", modelo="deepseek-chat", chave="sk-x"))
    await mandar("image", "image/png", _png(), legenda="quanto custa esse?")
    turno = IA.chamadas[-1]["historico"][-1]
    check("com legenda responde, sem imagem e com o aviso",
          not turno.get("imagens") and "não consegue ver" in turno["content"]
          and "quanto custa" in turno["content"], turno)
    check("e o prompt nao promete que ele ve",
          "você a vê" not in IA.chamadas[-1]["instrucoes"], "")

    print("\n[foto desligada no agente]")
    await _semear(_agente(provedor="anthropic", modelo="claude-haiku-4-5", chave="sk-ant-x",
                          imagem_ativa=False))
    await mandar("image", "image/png", _png())
    s = await sessao()
    check("nao responde", len(IA.chamadas) == 0, IA.chamadas)
    check("motivo no historico",
          any("não ver fotos" in m for m in await sistemas(s["id"])), await sistemas(s["id"]))

    print("\n[video e documento continuam com gente]")
    await _semear(_agente(provedor="anthropic", modelo="claude-haiku-4-5", chave="sk-ant-x"))
    await mandar("document", "application/pdf", b"%PDF-1.4")
    s = await sessao()
    check("documento sem legenda vai para a fila", len(IA.chamadas) == 0, IA.chamadas)
    check("dizendo que o agente nao analisa",
          any("não analisa" in m for m in await sistemas(s["id"])), await sistemas(s["id"]))


def etapa_formatos_por_protocolo():
    print("\n[cada protocolo recebe a imagem no formato dele]")
    t = {"role": "user", "content": "e essa?", "imagens": [{"mime": "image/jpeg", "b64": "QUJD"}]}
    a = ai_client._turno_anthropic(t)
    check("anthropic: bloco image base64 antes do texto",
          a["content"][0]["type"] == "image" and a["content"][0]["source"]["data"] == "QUJD"
          and a["content"][-1] == {"type": "text", "text": "e essa?"}, a)
    r = ai_client._turno_responses(t)
    check("responses: input_image com data URI",
          r["content"][0] == {"type": "input_image", "image_url": "data:image/jpeg;base64,QUJD"}, r)
    c = ai_client._turno_chat(t)
    check("chat: image_url com data URI",
          c["content"][0]["image_url"]["url"] == "data:image/jpeg;base64,QUJD", c)
    so_foto = ai_client._turno_anthropic({**t, "content": ""})
    check("foto sem legenda nao leva bloco de texto vazio (a Anthropic recusa)",
          all(p["type"] != "text" for p in so_foto["content"]), so_foto)
    check("turno sem imagem continua string, sem a chave `imagens`",
          ai_client._turno_chat({"role": "user", "content": "oi"}) == {"role": "user", "content": "oi"})
    check("catalogo marca quem nao enxerga",
          ai_client.aceita_imagem("deepseek", "deepseek-chat") is False
          and ai_client.aceita_imagem("anthropic", "claude-haiku-4-5") is True
          and ai_client.aceita_imagem("groq", "um-modelo-novo") is None)


async def etapa_chat_de_teste():
    print("\n[chat de teste com foto e audio]")
    await _semear(_agente(provedor="openai", modelo="gpt-5-mini", chave="sk-x"))
    foto = await rai.anexo_de_teste("ag-1", base._upload("peca.png", "image/png", _png()), ADMIN)
    check("foto aceita no teste", foto["kind"] == "image", foto)
    r = await rai.testar_agente("ag-1", rai.TesteIn(mensagens=[
        {"role": "user", "content": "", "anexo": {"id": foto["id"]}}]), ADMIN)
    check("o agente responde a foto", not r["transferiu"], r)
    check("e a imagem chegou ao modelo", IA.chamadas[-1]["historico"][-1].get("imagens"),
          IA.chamadas[-1]["historico"])

    audio = await rai.anexo_de_teste("ag-1", base._upload("gravacao.webm", "audio/webm",
                                                            b"webm"), ADMIN)
    check("audio do navegador (webm) e aceito e transcrito",
          audio["kind"] == "audio" and audio.get("transcricao") == TRANSCRITOR.texto, audio)
    check("transcrito com a chave da OpenAI do agente",
          TRANSCRICOES[-1]["chave"] == "sk-x" and TRANSCRICOES[-1]["nome"].endswith(".webm"),
          TRANSCRICOES)
    r = await rai.testar_agente("ag-1", rai.TesteIn(mensagens=[
        {"role": "user", "content": "", "anexo": {"id": audio["id"],
                                                  "transcricao": audio["transcricao"]}}]), ADMIN)
    check("o agente responde ao audio", not r["transferiu"], r)
    check("ouvindo a transcricao", "onix prata" in IA.chamadas[-1]["historico"][-1]["content"],
          IA.chamadas[-1]["historico"])

    st, det = await base.erro(rai.anexo_de_teste(
        "ag-1", base._upload("contrato.pdf", "application/pdf", b"%PDF"), ADMIN))
    check("documento e recusado dizendo por que", st == 400 and "documento" in det, (st, det))

    await _semear(_agente(provedor="deepseek", modelo="deepseek-chat", chave="sk-x"))
    foto = await rai.anexo_de_teste("ag-1", base._upload("peca.png", "image/png", _png()), ADMIN)
    r = await rai.testar_agente("ag-1", rai.TesteIn(mensagens=[
        {"role": "user", "content": "", "anexo": {"id": foto["id"]}}]), ADMIN)
    check("no teste, modelo sem visao transfere igual ao real",
          r["transferiu"] and "não enxerga" in r["motivo"] and not IA.chamadas, r)

    p = await rai.ver_poderes("ag-1", ADMIN)
    check("a tela sabe que a foto nao vai funcionar com este modelo",
          p["imagem_ativa"] and p["imagem_pronta"] is False, p)
    check("nem o audio (DeepSeek nao transcreve, sem chave da plataforma)",
          p["audio_pronto"] is False, p)


async def etapa_audio_pela_wuzapi():
    """O caso de producao de 13/10/2026: pela ponte nao existe `media_id`, e a
    midia era descartada sem log antes de chegar ao agente."""
    print("\n[audio que chega pela WuzAPI]")
    import base64
    import cripto
    import wuzapi_client

    await _semear(_agente())
    await DB.whatsapp_connections.update_one(
        {"id": base.CONN_A}, {"$set": {"canal": "wuzapi", "wuzapi_id": "inst-1",
                                       "token_cifrado": cripto.cifrar("tok-instancia")}})

    # Sem -skipmedia: o binario vem no proprio evento, as vezes como data URI.
    dados = b"OggS-nota-pela-ponte"
    await receber("", media={
        "kind": "audio", "mime": "audio/ogg; codecs=opus",
        "base64": "data:audio/ogg;base64," + base64.b64encode(dados).decode(),
        "download": {}})
    s = await sessao()
    msg = (await _recebidas(s["id"]))[-1]
    media = (msg.get("meta") or {}).get("media") or {}
    check("o audio da ponte vira arquivo nosso", media.get("kind") == "audio", msg)
    check("com o mime sem o parametro de codec", media.get("mime") == "audio/ogg", media)
    check("e e transcrito e respondido pelo agente",
          TRANSCRICOES and len(IA.chamadas) == 1
          and "onix prata" in IA.chamadas[-1]["historico"][-1]["content"], IA.chamadas)

    # Com -skipmedia: so os dados de decifragem; quem baixa e a ponte.
    pedidos = []

    async def fake_download(token, kind, info):
        pedidos.append((token, kind, info.get("DirectPath")))
        return b"OggS-baixado-pela-ponte"

    original = wuzapi_client.download_media
    wuzapi_client.download_media = fake_download
    try:
        await receber("", media={
            "kind": "audio", "mime": "audio/ogg; codecs=opus", "base64": None,
            "download": {"DirectPath": "/v/t62/abc", "MediaKey": "k", "Url": None}})
    finally:
        wuzapi_client.download_media = original
    check("sem base64, pede a ponte com o token da instancia",
          pedidos == [("tok-instancia", "audio", "/v/t62/abc")], pedidos)
    msg = (await _recebidas(s["id"]))[-1]
    check("e o arquivo baixado e gravado", (msg.get("meta") or {}).get("media"), msg)

    await receber("", media={"kind": "audio", "mime": "audio/ogg", "base64": None,
                             "download": {}})
    s = await sessao()
    check("sem origem nenhuma, vai para a fila dizendo que nao baixou",
          any("baixá-lo" in m for m in await sistemas(s["id"])), await sistemas(s["id"]))


def test_suite():
    _conectar()

    async def _tudo():
        await etapa_audio_pela_wuzapi()
        await etapa_audio_transcrito()
        await etapa_audio_ilegivel()
        await etapa_foto_vista()
        etapa_formatos_por_protocolo()
        await etapa_chat_de_teste()
        print(f"\n=== {base.ok} verificacoes passaram ===")
    asyncio.run(_tudo())
