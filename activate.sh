#!/bin/bash
# Скрипт для активации виртуального окружения Python 3.12

# Определяем директорию проекта
PROJECT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# Активируем виртуальное окружение
source "$PROJECT_DIR/.venv/bin/activate"

# Выводим информацию о текущем окружении
echo "✓ Виртуальное окружение активировано"
echo "Python: $(python --version)"
echo "Путь: $(which python)"
