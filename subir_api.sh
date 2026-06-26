#!/usr/bin/env bash
# ============================================================================
# subir_api.sh — resolve o 405 do "importar-ecf" de uma vez.
#
# O que ele faz:
#   1) Descobre o Python certo (o do .venv, se já tiver o fastapi; senão o do sistema)
#   2) Instala o python-multipart NESSE Python (com fallback p/ --break-system-packages)
#   3) Confere fastapi + multipart
#   4) Confirma que o app/api/routes/emissoes.py importa sem erro
#   5) Encerra qualquer uvicorn preso e sobe de novo NO MESMO Python
#
# Uso:
#   cd ~/Desktop/ERP15042
#   bash subir_api.sh
# ============================================================================
set -e
cd "$(dirname "$0")"

# 1) Escolhe o Python: usa o do .venv só se ele existir E já tiver o fastapi.
PY=python3
if [ -x .venv/bin/python ] && .venv/bin/python -c "import fastapi" >/dev/null 2>&1; then
  PY=.venv/bin/python
fi
echo ">> Python em uso: $($PY -c 'import sys; print(sys.executable)')"

# 2) Instala o python-multipart. Tenta o modo normal; se o ambiente for
#    'externally managed', refaz com o override que o próprio erro sugere.
if ! $PY -m pip install python-multipart >/dev/null 2>&1; then
  echo ">> Ambiente externally-managed — reinstalando com --break-system-packages..."
  $PY -m pip install python-multipart --break-system-packages
fi

# 3) Confere as dependências críticas para o upload da ECF.
$PY -c "import fastapi, multipart; print('>> deps OK (fastapi + multipart)')"

# 4) Confirma que o arquivo novo importa sem erro (pega IndentationError, etc.).
$PY -c "import app.api.routes.emissoes; print('>> emissoes.py importa sem erro')"

# 5) Encerra qualquer uvicorn preso e sobe de novo no MESMO Python.
pkill -f "uvicorn" >/dev/null 2>&1 && echo ">> uvicorn anterior encerrado" || true
sleep 1
echo ">> Subindo a API em http://localhost:8000   (Ctrl+C para parar)"
echo ">> Abra http://localhost:8000/docs e procure POST /api/v1/emissoes/importar-ecf"
exec $PY -m uvicorn app.api.main:app --host 0.0.0.0 --port 8000
