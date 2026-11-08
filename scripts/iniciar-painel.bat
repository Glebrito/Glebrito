@echo off
setlocal EnableExtensions
REM Inicia o painel local Colih Hourglass (loopback). Env em scripts\hourglass.env (KEY=valor).

set "ROOT=%~dp0.."
set "ENVFILE=%~dp0hourglass.env"
if not exist "%ENVFILE%" set "ENVFILE=%ROOT%\hourglass.env"
if not exist "%ENVFILE%" set "ENVFILE=%ROOT%\.env"

cd /d "%ROOT%"
if errorlevel 1 (
  echo Nao foi possivel acessar: %ROOT%
  exit /b 1
)

set "PYTHONPATH=."

if exist "%ENVFILE%" (
  echo Usando env-file: %ENVFILE%
  python -m colih_hourglass serve --env-file "%ENVFILE%"
) else (
  echo Aviso: nenhum hourglass.env ou .env encontrado; defina SUPABASE_* no ambiente.
  python -m colih_hourglass serve
)

endlocal
