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

## Fluxo rápido (Windows — terminal, recomendado)

1. **Credenciais** — `scripts\hourglass.env` no Agent Store (ou `scripts\hourglass.env` no clone Glebrito):

```ini
SUPABASE_URL=https://xvriolmnmuezzarpwvwn.supabase.co
SUPABASE_SERVICE_ROLE_KEY=sua_service_role_key
HOURGLASS_LGROUP=43741
```

2. **Sessão Hourglass** (uma vez, ou quando der HTTP 401) — na pasta `scripts` do Project:

```cmd
python hourglass_cli.py session save --curl-file hourglass.curl.txt
```

Grava `scripts\.hourglass-session.json`.

3. **Rodízio** — duplo clique em `scripts\rodizio.bat` (Store) ou `scripts\rodizio.bat` (repo):

```cmd
scripts\rodizio.bat
scripts\rodizio.bat 2026-11-09
```

Equivale a `python -m colih_hourglass atualizar --env-file scripts\hourglass.env --suggest` (próxima segunda) ou `--week` com data.

O comando baixa meeting + schedule + privileges + users da API (cabeçalhos iguais ao `hourglass_cli.py`), grava no Supabase e imprime tabela markdown com nomes reais.

**Fallback (sem sessão):** snippet `hourglass-browser-export-snippet.js` + `import-rotation mm-export.json`, ou painel local opcional (`iniciar-painel.bat`, só `127.0.0.1`).

**Chrome (um clique):** com o painel ligado, Tampermonkey ou favorito (`hourglass-colih-userscript.js` / `hourglass-colih-bookmarklet.url`) → botão **Atualizar Supabase** em app.hourglass-app.com.

Documentação: `docs/configuracao-passo-a-passo.md` no Project store.

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
