"""As marcas do painel do AUTO.

O sistema é um só e é revendido por mais de um parceiro, cada um para a própria
carteira, e o cliente final enxerga as cores de quem vendeu (`tenants.marca`).
Desde 18/11/2026 são só duas: Logos, a padrão, e R3. Marca nova entra aqui e em
`frontend/src/lib/marca.js`, junto com os tokens dela em `index.css`.

Módulo à parte, sem dependência nenhuma, porque quem precisa dele (`auth`,
`routes.tenants`, `plataforma`) já importa um do outro.
"""
from typing import Literal

Marca = Literal["logos", "r3"]
MARCA_PADRAO = "logos"
MARCAS = ("logos", "r3")


def normaliza_marca(marca: str | None) -> str:
    """A marca gravada, traduzida para uma que ainda existe.

    Empresas criadas antes de 18/11/2026 podem ter `zappzen` ou `nexa`
    gravado, ou nada. A tradução é feita na leitura, e não no banco, de
    propósito: há cliente em produção, e voltar atrás não pode depender de
    desfazer uma migração de dados.
    """
    return marca if marca in MARCAS else MARCA_PADRAO
