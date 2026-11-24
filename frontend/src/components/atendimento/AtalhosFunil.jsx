import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { CurrencyCircleDollar, MapPinLine } from "@phosphor-icons/react";
import api from "@/lib/api";
import Modal from "@/components/ui/Modal";
import { useAcao } from "@/hooks/useAcao";
import { formatBRL, parseBRLInput } from "@/lib/currency";
import { t } from "@/lib/textos";

// "Visita realizada" e "Venda" ao lado de Assumir/Finalizar.
//
// Pedido do Atalaia: o vendedor está na conversa quando o cliente chega à
// loja ou fecha, e ir ao funil achar o cartão era o passo que ninguém dava.
// O servidor decide qual etapa é cada uma (`_etapas_atalho`): a visita pelo
// nome da etapa, a venda pela primeira etapa de Ganho. Funil sem etapa de
// visita realizada não mostra o botão.
export default function AtalhosFunil({ sessionId, onFeito }) {
  const [info, setInfo] = useState(null);
  const [vendendo, setVendendo] = useState(false);
  const [valor, setValor] = useState("");

  const carregar = useCallback(() => {
    if (!sessionId) return;
    api.get(`/atendimento/sessions/${sessionId}/funil`)
      .then((r) => setInfo(r.data))
      .catch(() => setInfo(null));
  }, [sessionId]);
  useEffect(() => { setInfo(null); carregar(); }, [carregar]);

  const enviar = async (acao, valorReais) => {
    try {
      const { data } = await api.post(`/atendimento/sessions/${sessionId}/funil`,
        { acao, ...(valorReais != null ? { valor: valorReais } : {}) });
      toast.success(data.mudou ? `${t("Negócio")} movido para "${data.etapa}"` : `O ${t("negócio")} já estava em "${data.etapa}"`);
      carregar();
      onFeito && onFeito();
      return true;
    } catch (e) {
      toast.error(e.response?.data?.detail || "Não foi possível atualizar");
      return false;
    }
  };

  const [visita, marcandoVisita] = useAcao(() => enviar("visita"));

  if (!info || !info.tem_contato || (!info.visita && !info.venda)) return null;
  const etapaAtual = info.negocio?.etapa_id;

  return (
    <>
      {info.visita && etapaAtual !== info.visita.id && (
        <button onClick={visita} disabled={marcandoVisita}
          title={`Move o ${t("negócio")} deste contato para "${info.visita.nome}"`}
          className="zz-btn zz-btn-secondary text-xs" data-testid="visita-realizada-btn">
          <MapPinLine size={12} weight="bold" /> Visita realizada
        </button>
      )}
      {info.venda && (
        <button onClick={() => { setValor(info.negocio?.valor ? formatBRL(info.negocio.valor) : ""); setVendendo(true); }}
          title={`Move o ${t("negócio")} deste contato para "${info.venda.nome}"`}
          className="zz-btn zz-btn-secondary text-xs" data-testid="venda-btn">
          <CurrencyCircleDollar size={12} weight="bold" /> Venda
        </button>
      )}
      {vendendo && (
        <Modal
          titulo="Registrar venda"
          descricao={info.negocio
            ? `"${info.negocio.titulo}" vai para "${info.venda.nome}".`
            : `Um ${t("negócio")} novo é criado em "${info.venda.nome}".`}
          salvarLabel="Registrar venda"
          salvandoLabel="Registrando…"
          onFechar={() => setVendendo(false)}
          onSalvar={async () => {
            const reais = valor.trim() ? parseBRLInput(valor) : null;
            if (await enviar("venda", reais)) setVendendo(false);
          }}
          testId="venda-modal">
          <label className="block">
            <span className="text-xs font-bold text-ink-2">Valor da venda</span>
            <input className="zz-input h-9 w-full mt-1" inputMode="numeric" placeholder="R$ 0,00"
              value={valor} autoFocus
              onChange={(e) => setValor(e.target.value ? formatBRL(parseBRLInput(e.target.value)) : "")}
              data-testid="venda-valor" />
            <span className="text-[11px] text-ink-3">
              Vai para os relatórios e, se a Conversions API estiver ligada, para o Meta Ads como compra.
            </span>
          </label>
        </Modal>
      )}
    </>
  );
}
