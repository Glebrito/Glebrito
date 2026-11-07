# Glebrito — Hourglass + Supabase (Colih)

Automação de designações da reunião do meio de semana para **Congregação Planalto Natal RN** (`lgroup=43741`), com histórico e regras no Supabase **Colih**.

Documentação de arquitetura (Project store): `/cursor/stores/self/docs/supabase-hourglass-architecture.md`.

## Requisitos

- Python 3.10+
- Projeto Supabase: `https://xvriolmnmuezzarpwvwn.supabase.co`
- Sessão Hourglass no PC (opcional na VM): ver `hourglass_cli.py` na pasta `scripts` do Project

## Configuração

1. Aplicar a migration em `supabase/migrations/20251107120000_hourglass_core.sql` (SQL Editor do Supabase ou Supabase CLI).

2. Variáveis de ambiente (Cursor Secrets ou `.env` local — **nunca** commitar):

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
PYTHONPATH=. python -m unittest tests.test_rules_engine -v
```

## Estrutura

```
colih_hourglass/     # sync, regras, CLI
supabase/migrations/ # schema Colih
tests/               # testes do motor de regras
```
