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

## Focus engine prototype

The current runtime can read system CPU/RAM/process information, detect the
foreground application and window on Windows, classify the focus task, and
publish one shared state to the dashboard and local API. Run the API with:

```bash
uvicorn main:app --host 127.0.0.1 --port 8000
```

The local API exposes `/health`, `/state`, and `/start`, `/pause`, `/resume`,
`/stop`, and `/emergency-disable` controls. Process priorities are currently
recommendations only; the prototype does not change process priorities,
suspend processes, or terminate applications.
