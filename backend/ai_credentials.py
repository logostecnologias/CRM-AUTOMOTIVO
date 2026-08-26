"""Cifra da chave de IA de cada empresa, em repouso.

Por que existe: a chave de API do cliente é a credencial de uma conta que ele
paga. Ela chega pela tela, fica guardada em `ai_connections` e é lida a cada
resposta do agente. Guardá-la em texto puro no Mongo significaria que um dump
do banco — backup, réplica, acesso de leitura de um terceiro — entrega a conta
de todos os clientes de uma vez.

O modelo é o mesmo do resto do projeto: o segredo mestre mora em variável de
ambiente (`AI_CREDENTIALS_KEY`), nunca no banco e nunca no código. Quem tem o
banco não tem as chaves; quem tem o `.env` não tem o banco.

Duas regras que não podem ser afrouxadas:

  - **A chave em claro nunca sai daqui para o frontend.** A tela recebe só
    `mascara()` — os quatro últimos caracteres, o suficiente para o cliente
    reconhecer qual chave ele cadastrou e nada além disso. Devolver a chave
    "para preencher o campo de edição" é o erro clássico: ela passaria a
    trafegar em toda abertura de tela e a viver no cache do navegador.

  - **`chave_versao` é gravado junto do texto cifrado.** Se um dia a chave
    mestra for trocada, os segredos antigos não são mais decifráveis — e é
    preciso saber *quais* são antigos para pedir ao cliente que reconecte, em
    vez de o agente falhar em silêncio com "credencial inválida".
"""
import os

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

# Versão da chave mestra em uso. Subir este número (e trocar a env) é o que
# marca as credenciais antigas como irrecuperáveis, de propósito.
CHAVE_VERSAO = 1


class CredencialError(Exception):
    """Falha ao cifrar/decifrar. Nunca carrega o segredo na mensagem."""


def _fernet() -> Fernet:
    """Lido sob demanda, não no import: o `.env` é carregado pelo server.py
    depois que este módulo já pode ter sido importado por um teste.

    Rotação da chave mestra (ZZ-21): devolve um `MultiFernet`. Cifra sempre com
    a chave **primária** (`AI_CREDENTIALS_KEY`); decifra tentando a primária e
    depois as **anteriores** (`AI_CREDENTIALS_KEY_PREV`, uma ou mais separadas
    por vírgula). Assim dá para trocar a chave mestra sem quebrar as credenciais
    já gravadas: promove-se a nova a primária e mantém-se a antiga em PREV
    durante a janela de recifragem. Sem isto, trocar a chave fazia toda
    credencial antiga falhar de uma vez, e o único caminho era pedir a cada
    cliente que reconectasse."""
    primaria = os.environ.get("AI_CREDENTIALS_KEY")
    if not primaria:
        raise CredencialError(
            "AI_CREDENTIALS_KEY não configurada — sem ela não é possível "
            "guardar chave de IA. Gere uma com: "
            "python -c \"from cryptography.fernet import Fernet; "
            "print(Fernet.generate_key().decode())\""
        )
    brutas = [primaria] + [
        k.strip() for k in os.environ.get("AI_CREDENTIALS_KEY_PREV", "").split(",") if k.strip()
    ]
    try:
        return MultiFernet([Fernet(k.encode("utf-8")) for k in brutas])
    except Exception as e:
        raise CredencialError(f"AI_CREDENTIALS_KEY inválida: {e}")


def cifrar(chave_api: str) -> dict:
    """Devolve o bloco que vai para o documento — cifrado, versão e máscara.

    A máscara é calculada aqui, e não na tela, porque é o único ponto do
    sistema que enxerga a chave em claro."""
    if not chave_api or not chave_api.strip():
        raise CredencialError("Chave vazia")
    chave_api = chave_api.strip()
    return {
        "cifrada": _fernet().encrypt(chave_api.encode("utf-8")).decode("utf-8"),
        "chave_versao": CHAVE_VERSAO,
        "mascara": mascara(chave_api),
    }


def decifrar(bloco: dict) -> str:
    """Recupera a chave para uso imediato numa chamada. O retorno não deve ser
    guardado em lugar nenhum — nem em cache, nem em log, nem em variável de
    módulo."""
    if not bloco or not bloco.get("cifrada"):
        raise CredencialError("Conexão de IA sem credencial guardada")
    if bloco.get("chave_versao") != CHAVE_VERSAO:
        raise CredencialError(
            "Credencial cifrada com uma chave mestra anterior — o cliente "
            "precisa reconectar a conta de IA"
        )
    try:
        return _fernet().decrypt(bloco["cifrada"].encode("utf-8")).decode("utf-8")
    except InvalidToken:
        # Acontece quando a AI_CREDENTIALS_KEY do ambiente não é a que cifrou.
        # Dizer isso explicitamente evita horas perseguindo um "401 do
        # provedor" que na verdade é a env errada no deploy.
        raise CredencialError(
            "Não foi possível decifrar a credencial: AI_CREDENTIALS_KEY não "
            "corresponde à que gravou este registro"
        )


def mascara(chave_api: str) -> str:
    """`sk-ant-api03-...abcd` — prefixo do provedor + últimos 4.

    Mostra o bastante para o cliente distinguir duas chaves dele e nada que
    ajude a reconstruir uma."""
    chave_api = (chave_api or "").strip()
    if len(chave_api) <= 8:
        return "•" * len(chave_api)
    return f"{chave_api[:7]}…{chave_api[-4:]}"
