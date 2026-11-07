# Glebrito — Hourglass + Supabase (Colih)

Automação de designações da reunião do meio de semana para **Congregação Planalto Natal RN** (`lgroup=43741`), com histórico e regras no Supabase **Colih**.

Documentação de arquitetura (Project store): `/cursor/stores/self/docs/supabase-hourglass-architecture.md`.

## Requisitos

- Python 3.10+
- Projeto Supabase: `https://xvriolmnmuezzarpwvwn.supabase.co`
- Sessão Hourglass no PC (opcional na VM): ver `hourglass_cli.py` na pasta `scripts` do Project

## Configuração

1. Aplicar a migration em `supabase/migrations/20251107120000_hourglass_core.sql` (SQL Editor do Supabase ou Supabase CLI).

2. Variáveis de ambiente (Cursor Secrets, arquivo local `.env` / `hourglass.env` — **nunca** commitar):

```bash
export SUPABASE_URL=https://xvriolmnmuezzarpwvwn.supabase.co
export SUPABASE_SERVICE_ROLE_KEY=sua_service_role_key
# opcional
export HOURGLASS_LGROUP=43741
export HG_SESSION=/caminho/.hourglass-session.json
```

3. Instalação opcional em modo editável:

```bash
cd /agent/repos/Glebrito
pip install -e .
```

Ou execute com `PYTHONPATH=.`:

```bash
PYTHONPATH=. python -m colih_hourglass --help
```

## Painel local (Windows — coordenador)

Substitui parte do fluxo manual em CMD por uma interface web em **português**, escutando apenas em `127.0.0.1` (não exponha na internet nem use em rede pública).

1. Coloque as credenciais Supabase em um arquivo ao lado do clone, por exemplo `hourglass.env`:

```ini
SUPABASE_URL=https://xvriolmnmuezzarpwvwn.supabase.co
SUPABASE_SERVICE_ROLE_KEY=sua_service_role_key
HOURGLASS_LGROUP=43741
```

2. Na pasta do repositório Glebrito (CMD):

```cmd
cd C:\caminho\para\Glebrito
set PYTHONPATH=.
python -m colih_hourglass serve --env-file hourglass.env
```

Ou, se instalou com `pip install -e .`:

```cmd
colih-hourglass serve --env-file hourglass.env --port 8765
```

3. Abra no navegador: `http://127.0.0.1:8765/`

O painel mostra o status das variáveis, permite **importar** o `mm-export.json` (mesma lógica de `import-rotation`), **sugerir** uma semana (com opção de gravar rascunho no Supabase) e **baixar** `sugestao.json` / rascunho. Partes 1–3 da reunião (regra das irmãs) aparecem destacadas na tabela.

Para gerar o JSON no Hourglass, use o snippet do navegador `hourglass-browser-export-snippet.js` na pasta `scripts` do Project (ver `docs/hourglass-cli.md` no Agent Store).

**Segurança:** o servidor aceita somente loopback; não faça port-forward nem publique esta porta.

## Primeiro sync (recomendado no Windows)

Na pasta onde está o `hourglass_cli.py` do Project:

```cmd
python hourglass_cli.py session save --curl-file hourglass.curl
python hourglass_cli.py whoami
python hourglass_cli.py fetch all --from 2025-04-01 --to 2026-12-31 --lgroup 43741 --out mm-export.json
```

No repositório Glebrito (com secrets Supabase):

```bash
PYTHONPATH=. python -m colih_hourglass import-rotation /caminho/mm-export.json
```

Sync direto pela API (mesma máquina com sessão válida):

```bash
PYTHONPATH=. python -m colih_hourglass sync --from 2025-04-01 --to 2026-12-31
```

## Sugestão da próxima semana

```bash
PYTHONPATH=. python -m colih_hourglass suggest-next --week 2026-11-02 --persist --out sugestao.json
PYTHONPATH=. python -m colih_hourglass export-draft --week 2026-11-02 --out draft.json
```

Regras codificadas:

- Rodízio por menor contagem no histórico
- Partes **4–6** da reunião (`apply1`–`apply3` + assistentes): **apenas irmãs**
- Espaçamento configurável em `spacing_constraints` (padrão: 2 semanas mesma função; 3 semanas entre partes FM para irmãs)

Ajuste `rules_config` e `spacing_constraints` no Supabase sem redeploy.

## Publicar no Hourglass

O pacote **não** envia `PUT` automaticamente sem payload capturado no DevTools. Após aprovar o rascunho:

```cmd
python hourglass_cli.py draft assign --date 2026-11-02 --role chairman --user-id ... --out patch.json
python hourglass_cli.py schedule put-core --date 2026-11-02 --apply --body-file devtools-payload.json --lgroup 43741
```

## Testes

```bash
cd /agent/repos/Glebrito
PYTHONPATH=. python -m unittest discover -s tests -v
```

## Estrutura

```
colih_hourglass/     # sync, regras, CLI, painel web local
supabase/migrations/ # schema Colih
tests/               # testes do motor de regras e painel
```

### Cursor App (futuro)

O painel local cobre o fluxo do coordenador no PC. Uma versão publicada no Cursor poderia reutilizar a mesma lógica (`import_rotation_file`, `run_suggest_week`) por trás de rotas HTTP no app publicado, com `bind-app-secrets` para Supabase — fora do escopo desta entrega.
