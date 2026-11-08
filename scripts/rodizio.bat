@echo off
setlocal EnableExtensions
REM Rodízio Colih: sync Hourglass -> Supabase + sugestão (terminal).
REM Agent Store: scripts\rodizio.bat (mesmo conteúdo). Glebrito: scripts\Glebrito ou clone GitHub.

set "SCRIPTSDIR=%~dp0"
set "GLEBRITO=%SCRIPTSDIR%"
set "ENVFILE=%SCRIPTSDIR%hourglass.env"

if exist "%SCRIPTSDIR%Glebrito\pyproject.toml" (
  set "GLEBRITO=%SCRIPTSDIR%Glebrito"
)

cd /d "%GLEBRITO%"
if errorlevel 1 (
  echo Nao foi possivel acessar Glebrito em: %GLEBRITO%
  exit /b 1
)

set "PYTHONPATH=."

if not exist "%ENVFILE%" set "ENVFILE=%GLEBRITO%\scripts\hourglass.env"
if not exist "%ENVFILE%" set "ENVFILE=%GLEBRITO%\hourglass.env"

if "%~1"=="" (
  python -m colih_hourglass atualizar --env-file "%ENVFILE%" --suggest
) else (
  python -m colih_hourglass atualizar --env-file "%ENVFILE%" --week %~1
)

set "ERR=%ERRORLEVEL%"
endlocal & exit /b %ERR%
