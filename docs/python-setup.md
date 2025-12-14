# Python Environment Setup

## Виртуальное окружение Python 3.12

Проект использует Python 3.12 с виртуальным окружением в папке `.venv`.

### Автоматическая активация в Cursor/VS Code

Настройки в `.vscode/settings.json` обеспечивают автоматическое использование правильного интерпретатора.

При открытии терминала в Cursor виртуальное окружение должно активироваться автоматически.

### Ручная активация

Если автоматическая активация не работает:

**macOS/Linux:**
```bash
source .venv/bin/activate
```

или используйте скрипт:
```bash
source activate.sh
```

**Windows (PowerShell):**
```powershell
.\.venv\Scripts\Activate.ps1
```

**Windows (CMD):**
```cmd
.venv\Scripts\activate.bat
```

### Проверка активации

После активации должен отображаться префикс `(.venv)` в командной строке.

Проверить версию Python:
```bash
python --version  # должно быть Python 3.12.0
which python      # должно указывать на .venv/bin/python
```

### Установка зависимостей

Если виртуальное окружение пустое или нужно обновить зависимости:

```bash
# Установка основных зависимостей
pip install --trusted-host pypi.org --trusted-host files.pythonhosted.org -r requirements.txt

# Установка проекта в режиме разработки
pip install --trusted-host pypi.org --trusted-host files.pythonhosted.org -e .

# Установка dev зависимостей (опционально)
pip install --trusted-host pypi.org --trusted-host files.pythonhosted.org -e ".[dev]"
```

### Запуск тестов

```bash
pytest tests/ -v
```

### Создание виртуального окружения с нуля

Если нужно пересоздать виртуальное окружение:

```bash
# Удалить старое окружение
rm -rf .venv

# Создать новое с Python 3.12
python3.12 -m venv .venv

# Активировать
source .venv/bin/activate

# Обновить pip
pip install --upgrade pip

# Установить зависимости
pip install --trusted-host pypi.org --trusted-host files.pythonhosted.org -r requirements.txt

# Установить проект в режиме разработки
pip install --trusted-host pypi.org --trusted-host files.pythonhosted.org -e .
```

### Файл .python-version

Файл `.python-version` содержит версию Python (3.12) для совместимости с pyenv и другими инструментами управления версиями Python.

### Проблемы и решения

**Проблема: SSL Certificate Verification Error**

Если возникают ошибки SSL при установке пакетов, используйте флаги:
```bash
pip install --trusted-host pypi.org --trusted-host files.pythonhosted.org <package>
```

**Проблема: ModuleNotFoundError при запуске тестов**

Убедитесь, что проект установлен в режиме разработки:
```bash
pip install -e .
```

**Проблема: Cursor не видит правильный интерпретатор**

1. Откройте Command Palette (Cmd+Shift+P)
2. Выберите "Python: Select Interpreter"
3. Выберите интерпретатор из `.venv/bin/python`

Или нажмите на версию Python в статус-баре внизу окна Cursor.
