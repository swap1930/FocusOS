# FocusOS

FocusOS is a task-aware operating system prototype designed to prioritize the active application and defer background work. The project follows the architecture described in `Design.md`.

## Project structure

```text
FocusOS/
|-- core/
|   |-- focus_engine.py
|   |-- resource_manager.py
|   |-- ram_manager.py
|   |-- process_manager.py
|   |-- app_manager.py
|   |-- storage_manager.py
|-- ai/
|   |-- command_parser.py
|   |-- intent_manager.py
|   |-- llm_client.py
|-- ml/
|   |-- ml_mode.py
|   |-- resource_optimizer.py
|-- dashboard/
|   |-- main_window.py
|   |-- performance_monitor.py
|   |-- widgets/
|-- api/
|   |-- focus_api.py
|-- database/
|   |-- database.py
|-- config/
|   |-- settings.py
|-- tests/
|-- main.py
|-- requirements.txt
|-- README.md
```

## Getting started

```bash
python -m venv venv
source venv/bin/activate
python -m pip install -r requirements.txt
python main.py
```
