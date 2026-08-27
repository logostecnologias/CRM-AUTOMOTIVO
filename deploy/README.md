# Produção

Subido em 27/08/2026 em `zappzen.atendimentoautomatizado.com.br`.

## Onde as coisas estão

| Peça | Onde |
|---|---|
| Aplicação | Instância Oracle `siaa-evolution`, alias SSH `WuzAPI`, IP `167.126.21.20` (privado `10.0.0.154`) |
| Código | `/opt/zappzen/backend`, com o venv em `/opt/zappzen/venv` |
| Frontend | `/opt/zappzen/frontend` (o `build/` do CRA, servido pelo Caddy) |
| Mídia | `/var/lib/zappzen/media`, fora da árvore do código |
| Segredos | `/opt/zappzen/backend/.env`, modo 600 |
| Banco | Instância `bancos-de-dados`, alias SSH `bancos-db`, privado `10.0.0.162` |

Três serviços do systemd, nesta ordem de dependência:

- `zappzen-db-tunnel` abre o túnel SSH até o Mongo, que escuta só em loopback
  na outra máquina;
- `zappzen` roda o uvicorn em `127.0.0.1:8000`, **um worker**;
- `caddy` faz TLS, serve o estático e repassa `/api/*`.

## Por que assim

**O banco não está nesta máquina.** Ela tem 954MB de RAM, e um `mongod` ao
lado do backend viveria em swap. O banco já existia no `bancos-db`, com os
dados reais, então produção usa o mesmo. O acesso é por túnel SSH porque é o
que dá para montar sem abrir o console da Oracle; o passo de endurecimento é
`mongod` escutando no IP privado com regra de Security List para a VCN, e aí o
túnel sai.

**A chave do túnel é restrita.** No `authorized_keys` do banco ela vai com
`restrict,permitopen="127.0.0.1:27017"`: não abre shell e não encaminha mais
nada. Uma chave comum daria à máquina da aplicação acesso completo ao servidor
de banco.

**Um worker só, e isso é requisito.** Os workers de fundo (lembrete de agenda,
disparo de campanha, retenção de mídia, monitor de conexões) sobem dentro do
processo, e a trava que serializa mensagens da mesma conversa vale dentro dele.
Dois workers mandam o lembrete duas vezes.

**Produção e desenvolvimento compartilham o banco.** Foi a escolha do cliente,
para a empresa e os robôs já configurados subirem junto. A consequência é
operacional: **não deixe o `npm run dev` local rodando enquanto a produção
está no ar**, senão dois backends processam a mesma agenda e as mesmas
campanhas. As travas do sistema (claim atômico de destinatário, marca de
lembrete gravada antes do envio) evitam o pior, mas não são desenhadas para
isso.

**Frontend e API no mesmo domínio.** O cookie de sessão é httpOnly com
SameSite=Lax, que o navegador não manda em requisição cross-site. Front num
domínio e API noutro não loga, por mais correto que esteja o CORS. É também por
isso que o build vai com `REACT_APP_BACKEND_URL` vazio: o `api.js` monta
`/api`, relativo.

## Publicar uma versão nova

```powershell
.\deploy\publicar.ps1           # código
.\deploy\publicar.ps1 -Infra    # código + Caddyfile/units/dependências
```

Faz o build, empacota, envia e reinicia. São alguns segundos fora do ar, o que
é o certo aqui: a alternativa (dois processos no mesmo banco durante a troca)
reintroduz a duplicação de worker.

Mudou só o `.env`? Não precisa publicar:

```bash
ssh WuzAPI "sudo systemctl restart zappzen"
```

## O que ainda depende de você

1. **DNS.** `zappzen.atendimentoautomatizado.com.br` precisa apontar para
   `167.126.21.20`. O domínio está na Cloudflare, então é lá. **DNS only**
   (nuvem cinza) para o primeiro deploy: o Caddy emite o certificado sozinho e
   a Meta fala direto com a origem. Com a nuvem laranja, o modo de SSL tem de
   ser **Full (strict)**, senão dá laço de redirecionamento, e as regras de WAF
   podem barrar os POSTs do webhook.
2. **Chaves da Meta** no `.env`: `META_APP_SECRET` e
   `META_WEBHOOK_VERIFY_TOKEN`. Enquanto estiverem vazias o webhook responde
   503 e recusa tudo, que é o comportamento correto: sem assinatura dá para
   forjar mensagem em qualquer conversa.
3. **Webhook no painel da Meta**:
   `https://zappzen.atendimentoautomatizado.com.br/api/webhooks/whatsapp`, com o
   campo **messages** assinado.

A porta 80 já responde da internet, então a Security List da Oracle está
liberada. A 443 só abre quando o Caddy tiver certificado, o que depende do
item 1.

## Diagnóstico

```bash
ssh WuzAPI "systemctl status zappzen zappzen-db-tunnel caddy --no-pager"
ssh WuzAPI "journalctl -u zappzen -n 50 --no-pager"
ssh WuzAPI "curl -s localhost:8000/api/health"
```

Sintomas e causa provável:

- **Login não passa, sem erro claro**: cookie. Confira se o acesso é pelo
  domínio (não pelo IP) e por HTTPS.
- **Manda mensagem e não recebe nada**: o app não está assinado na WABA do
  cliente. Recadastre as credenciais da conexão na tela de Conexões, que o
  passo de assinatura acontece ali.
- **Webhook devolvendo 503**: `META_APP_SECRET` vazio no `.env`.
- **Backend não sobe**: quase sempre o túnel do banco. `systemctl status
  zappzen-db-tunnel`.

## Backup

Ainda não existe, e é a lacuna mais séria deste ambiente. Precisa de
`mongodump` diário no `bancos-db`, cópia de `/var/lib/zappzen/media` e uma
cópia **fora da Oracle** da `AI_CREDENTIALS_KEY`: sem ela, as credenciais de IA
gravadas no banco são irrecuperáveis.

Vale também subir a conta da Oracle para Pay As You Go. Instância Always Free
ociosa pode ser recuperada, e esta agora tem produção em cima.

## Migrar para outra máquina

O desenho foi feito para isso custar uma troca de DNS, porque a intenção é
mudar para uma VPS paga:

1. provisione a máquina e rode os mesmos passos (venv, dependências, units,
   Caddyfile);
2. copie o `.env`;
3. gere a chave do túnel e autorize-a no `bancos-db`, ou aponte a `MONGO_URL`
   direto para o banco novo;
4. `publicar.ps1` com o alias novo;
5. troque o registro A. O certificado não migra: o Caddy emite outro na
   máquina nova sozinho.
