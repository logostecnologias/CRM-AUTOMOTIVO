"""Flow execution engine (used for simulated test chat).

Advances the conversation through connected nodes until it reaches
a node that must wait for user input (Menu) or the flow ends.
Persists ephemeral test sessions in-memory (module-level dict) — this
is fine because it's only for the test chat inside the editor.
"""
import re
import uuid
import asyncio
import httpx
from datetime import datetime, timezone

_test_sessions: dict[str, dict] = {}


def _now():
    return datetime.now(timezone.utc).isoformat()


def _interp(text: str, variables: dict) -> str:
    if not isinstance(text, str):
        return text
    def repl(m):
        key = m.group(1).strip()
        return str(variables.get(key, m.group(0)))
    return re.sub(r"\{([a-zA-Z0-9_]+)\}", repl, text)


def _find_node(nodes, node_id):
    for n in nodes:
        if n["id"] == node_id:
            return n
    return None


def _find_next(edges, source_id, handle=None):
    for e in edges:
        if e["source"] == source_id:
            if handle is None or e.get("sourceHandle") == handle:
                return e["target"]
    return None


def _find_start(nodes):
    for n in nodes:
        if n["type"] == "start":
            return n
    return None


async def _process_node(node, flow, session, outputs):
    """Process a single node and return next_node_id or None (waiting)."""
    ntype = node["type"]
    data = node.get("data", {})
    edges = flow["edges"]
    variables = session["variables"]

    if ntype == "start":
        return _find_next(edges, node["id"])

    if ntype == "text":
        text = _interp(data.get("text", ""), variables)
        outputs.append({"type": "text", "content": text})
        return _find_next(edges, node["id"])

    if ntype == "menu":
        question = _interp(data.get("text", ""), variables)
        options = data.get("options", [])
        outputs.append({
            "type": "menu",
            "content": question,
            "options": [o.get("label", "") for o in options],
        })
        session["awaiting"] = {"node_id": node["id"]}
        return None  # wait for user input

    if ntype == "save_variable":
        name = data.get("variable_name") or "var"
        source = data.get("source", "last_response")
        if source == "fixed":
            value = data.get("value", "")
        else:
            value = session.get("last_user_message", "")
        variables[name] = value
        return _find_next(edges, node["id"])

    if ntype == "condition":
        var_name = data.get("variable_name", "")
        op = data.get("operator", "equals")
        cmp_val = data.get("value", "")
        actual = str(variables.get(var_name, ""))
        result = False
        if op == "equals":
            result = actual == str(cmp_val)
        elif op == "contains":
            result = str(cmp_val) in actual
        elif op == "greater_than":
            try:
                result = float(actual) > float(cmp_val)
            except Exception:
                result = False
        elif op == "less_than":
            try:
                result = float(actual) < float(cmp_val)
            except Exception:
                result = False
        return _find_next(edges, node["id"], "true" if result else "false")

    if ntype == "media":
        outputs.append({
            "type": "media",
            "media_type": data.get("media_type", "image"),
            "url": data.get("url", ""),
            "caption": _interp(data.get("caption", ""), variables),
        })
        return _find_next(edges, node["id"])

    if ntype == "delay":
        seconds = int(data.get("seconds", 1))
        outputs.append({"type": "delay", "seconds": min(seconds, 3)})
        # in test mode we do not actually sleep for long
        await asyncio.sleep(min(seconds, 1) * 0.2)
        return _find_next(edges, node["id"])

    if ntype == "webhook":
        url = _interp(data.get("url", ""), variables)
        method = (data.get("method") or "GET").upper()
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                if method == "GET":
                    r = await client.get(url)
                else:
                    r = await client.request(method, url, json=data.get("body", {}))
                try:
                    variables["webhook_response"] = r.json()
                except Exception:
                    variables["webhook_response"] = r.text
                outputs.append({"type": "system", "content": f"Webhook {method} {r.status_code}"})
                return _find_next(edges, node["id"], "success")
        except Exception as e:
            outputs.append({"type": "system", "content": f"Erro no webhook: {e}"})
            return _find_next(edges, node["id"], "error")

    if ntype == "human_handoff":
        outputs.append({"type": "system", "content": "Conversa transferida para atendimento humano"})
        session["status"] = "aguardando_humano"
        return None

    if ntype == "end":
        outputs.append({"type": "system", "content": "Fluxo encerrado"})
        session["status"] = "finalizada"
        return None

    return _find_next(edges, node["id"])


async def _run_from(node_id, flow, session, outputs, guard=0):
    while node_id and guard < 50:
        node = _find_node(flow["nodes"], node_id)
        if node is None:
            break
        next_id = await _process_node(node, flow, session, outputs)
        session["node_atual_id"] = node["id"]
        if next_id is None:
            break
        node_id = next_id
        guard += 1


async def run_test_message(flow, session_id, message, start):
    outputs: list[dict] = []
    if start or not session_id or session_id not in _test_sessions:
        session_id = str(uuid.uuid4())
        start_node = _find_start(flow["nodes"])
        if not start_node:
            return {"session_id": session_id, "outputs": [{"type": "system", "content": "Fluxo sem nó de Início"}], "status": "erro"}
        session = {
            "id": session_id,
            "flow_id": flow["id"],
            "node_atual_id": start_node["id"],
            "variables": {},
            "status": "ativa",
            "awaiting": None,
            "last_user_message": "",
        }
        _test_sessions[session_id] = session
        await _run_from(start_node["id"], flow, session, outputs)
        return {"session_id": session_id, "outputs": outputs, "status": session["status"], "variables": session["variables"]}

    session = _test_sessions[session_id]
    session["last_user_message"] = message or ""

    awaiting = session.get("awaiting")
    if awaiting and awaiting.get("node_id"):
        # Determine chosen handle from Menu
        menu_node = _find_node(flow["nodes"], awaiting["node_id"])
        if menu_node and menu_node["type"] == "menu":
            options = menu_node.get("data", {}).get("options", [])
            handle = None
            msg = (message or "").strip()
            # try number
            if msg.isdigit():
                idx = int(msg) - 1
                if 0 <= idx < len(options):
                    handle = options[idx].get("id") or f"opt_{idx}"
            # try label match
            if handle is None:
                for i, o in enumerate(options):
                    if o.get("label", "").strip().lower() == msg.lower():
                        handle = o.get("id") or f"opt_{i}"
                        break
            if handle is None:
                # invalid response -> fallback handle
                next_id = _find_next(flow["edges"], menu_node["id"], "invalid")
                if next_id is None:
                    outputs.append({"type": "text", "content": "Resposta inválida. Tente novamente."})
                    return {"session_id": session_id, "outputs": outputs, "status": "ativa", "variables": session["variables"]}
                session["awaiting"] = None
                await _run_from(next_id, flow, session, outputs)
            else:
                next_id = _find_next(flow["edges"], menu_node["id"], handle)
                session["awaiting"] = None
                if next_id:
                    await _run_from(next_id, flow, session, outputs)
        else:
            session["awaiting"] = None

    return {
        "session_id": session_id,
        "outputs": outputs,
        "status": session["status"],
        "variables": session["variables"],
    }
