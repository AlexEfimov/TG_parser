# Настройка интерпретатора Python в Cursor

## Текущая конфигурация

✅ Python 3.12.0 установлен в `.venv/`
✅ Все зависимости установлены
✅ Проект установлен в режиме разработки
✅ Все тесты проходят (29/29)

## Если Cursor не видит интерпретатор

### Способ 1: Через Command Palette (рекомендуется)

1. Нажмите `Cmd+Shift+P` (macOS) или `Ctrl+Shift+P` (Windows/Linux)
2. Введите: `Python: Select Interpreter`
3. Выберите: `Python 3.12.0 (.venv)`
   - Путь: `${workspaceFolder}/.venv/bin/python`

### Способ 2: Через статус-бар

Нажмите на версию Python в нижнем правом углу Cursor и выберите `.venv/bin/python`

### Способ 3: Проверка настроек

Файл `.vscode/settings.json` должен содержать:

```json
{
  "python.defaultInterpreterPath": "${workspaceFolder}/.venv/bin/python",
  "python.terminal.activateEnvironment": true,
  "python.pythonPath": "${workspaceFolder}/.venv/bin/python"
}
```

## Проверка работоспособности

В терминале Cursor выполните:

```bash
# Должен показать Python 3.12.0
python --version

# Должен показать путь к .venv
which python

# Должен показать установленный пакет
python -c "import tg_parser; print('✓ OK')"

# Запустить тесты
pytest tests/ -v
```

## Если виртуальное окружение не активируется автоматически

Активируйте вручную в каждом новом терминале:

```bash
source .venv/bin/activate  # macOS/Linux
# или
.venv\Scripts\activate  # Windows
```

Или используйте скрипт:

```bash
source activate.sh
```

## Переустановка окружения (если что-то сломалось)

```bash
# Удалить старое окружение
rm -rf .venv

# Создать новое
python3.12 -m venv .venv

# Активировать
source .venv/bin/activate

# Установить зависимости
pip install --upgrade pip
pip install --trusted-host pypi.org --trusted-host files.pythonhosted.org -r requirements.txt
pip install --trusted-host pypi.org --trusted-host files.pythonhosted.org -e .
```

## Полезные ссылки

- Подробная документация: `docs/python-setup.md`
- Конфигурация проекта: `pyproject.toml`
- Зависимости: `requirements.txt`
