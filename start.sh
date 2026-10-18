#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

echo "=== Время рядом ==="
echo

if ! command -v python3 >/dev/null 2>&1; then
  echo "[ERROR] Python 3 не найден. Установите Python 3.10+."
  exit 1
fi

if [ ! -x ".venv/bin/python" ]; then
  echo "Создаём виртуальное окружение..."
  python3 -m venv .venv
fi

# shellcheck disable=SC1091
source ".venv/bin/activate"

echo "Устанавливаем зависимости..."
python -m pip install --upgrade pip >/dev/null
python -m pip install -r requirements.txt

echo
echo "Сервер: http://127.0.0.1:5000"
echo "Остановка: Ctrl+C"
echo
python main.py
