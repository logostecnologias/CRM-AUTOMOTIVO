import { Sparkle } from "@phosphor-icons/react";

export default function AIAgentsPage() {
  return (
    <div className="p-8 max-w-4xl" data-testid="ai-agents-page">
      <div className="mb-8">
        <div className="text-[10px] font-bold tracking-[0.25em] uppercase text-slate-500 mb-2">Automação</div>
        <h1 className="font-heading text-4xl font-black tracking-tighter">Agentes de IA</h1>
        <p className="text-slate-600 mt-2 text-sm">Configure agentes inteligentes para atender e responder automaticamente.</p>
      </div>

      <div className="border border-slate-200 bg-white p-12 flex flex-col items-center justify-center text-center gap-3">
        <div className="w-12 h-12 bg-slate-900 text-white flex items-center justify-center">
          <Sparkle size={22} weight="bold" />
        </div>
        <p className="text-slate-600 text-sm max-w-sm">Em breve você poderá criar e configurar agentes de IA por aqui.</p>
      </div>
    </div>
  );
}
