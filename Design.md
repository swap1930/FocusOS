# FocusOS — Prototype Project Specification

## 1. Project Overview

**FocusOS** is a task-focused operating system prototype designed to automatically prioritize system resources for the user's **currently active task**.

### Core Principle

> **Give maximum resources to what the user is doing now, while keeping everything else lightweight, dormant, or deferred.**

The first version is a **desktop prototype**, not a complete operating-system kernel. The prototype will prove the resource-management concept before moving toward deeper OS-level development.

---

## 2. Problem Statement

Modern operating systems often keep many applications, services, synchronization processes, caches, and background tasks active even when the user is focused on one application.

This can cause:

- Unnecessary RAM consumption
- CPU usage by background processes
- Reduced performance of the active application
- Slower ML model training
- Too many unnecessary background processes
- Accumulation of temporary/cache files
- Manual resource-management overhead

FocusOS aims to solve this by making resource management **task-aware**.

---

## 3. Prototype Objectives

The prototype should:

1. Detect the user's currently active application.
2. Monitor CPU, RAM, GPU where available, disk, and processes.
3. Identify the current focus task.
4. Give higher priority to the active task.
5. Reduce resource usage of unnecessary background processes.
6. Safely throttle or suspend selected idle processes.
7. Restore processes when they are needed again.
8. Identify unnecessary temporary/cache files.
9. Provide an AI-powered natural-language terminal.
10. Provide a desktop performance dashboard.
11. Provide an ML Training Mode.
12. Compare system performance before and after FocusOS optimization.
13. Start automatically with the system.

---

# 4. Prototype Architecture

```text
                         FocusOS
                            |
             +--------------+--------------+
             |              |              |
       Focus Engine     AI Terminal    Dashboard
             |              |              |
             +--------------+--------------+
                            |
                    FocusOS Core API
                            |
          +-----------------+-----------------+
          |                 |                 |
     RAM Manager       CPU Manager      Process Manager
          |                 |                 |
          +-----------------+-----------------+
                            |
                     System Resources
```

---

# 5. Main Prototype Modules

## 5.1 Focus Engine

The Focus Engine is the core of the prototype.

It detects:

- Active application
- Active window
- User activity
- CPU usage
- Process relationships
- Current workload

Example:

```text
VS Code       -> Coding Mode
Chrome        -> Browsing Mode
PyTorch       -> ML Training Mode
Blender       -> Rendering Mode
PowerPoint    -> Presentation Mode
```

The first prototype should focus on **active application/window detection**. Exact browser-tab detection can be added later because it is more platform-specific.

---

## 5.2 Resource Manager

The Resource Manager controls and monitors:

- CPU
- RAM
- GPU where available
- Disk
- Running processes

Example:

```text
Current Task: ML Training

Python/PyTorch     -> HIGH
GPU workload       -> HIGH
Dataset loader     -> HIGH

Browser            -> LOW
Music player       -> LOW
Updates            -> DEFERRED
Unused apps        -> SUSPENDED
```

### Safety rule

Do not blindly kill processes.

Use this order:

```text
Normal
  |
  v
Lower Priority
  |
  v
Throttle
  |
  v
Suspend
  |
  v
Terminate only when explicitly allowed
```

System-critical processes must never be terminated by the prototype.

---

# 6. RAM Manager

The RAM Manager aims to reduce unnecessary active memory usage.

Important concept:

```text
Installed Application
        !=
Continuously Running Application
```

Prototype flow:

```text
Application becomes idle
        |
        v
Check whether it is safe to suspend
        |
        v
Save required state if possible
        |
        v
Suspend process
        |
        v
Release resources where safely possible
        |
        v
Restore when user needs it
```

The prototype must always protect user data and critical system processes.

---

# 7. Background Process Manager

The Background Process Manager classifies processes as:

- Active
- Important
- Idle
- Resource-intensive
- Background
- Safe-to-defer

Flow:

```text
Monitor
   |
   v
Classify
   |
   v
Prioritize
   |
   v
Throttle / Suspend
   |
   v
Restore when required
```

---

# 8. Smart Application Concept

FocusOS should follow:

> **Install applications once, but do not keep unnecessary applications actively consuming resources.**

Example applications:

- PyTorch
- TensorFlow
- Blender
- Android Studio
- Docker

The prototype should demonstrate the concept through process suspension/loading rather than attempting to redesign application packaging immediately.

---

# 9. Smart Storage Manager

The Storage Manager scans for:

- Temporary files
- Application caches
- Old logs
- Crash dumps
- Safe-to-remove generated files

Flow:

```text
Scan
  |
  v
Classify
  |
  v
Safety Check
  |
  v
Show Recommendation
  |
  v
User Approval / Safe Automatic Cleanup
  |
  v
Cleanup
```

The prototype must **never blindly delete files**.

---

# 10. AI Terminal

FocusOS should provide a natural-language command interface.

Instead of only using technical commands:

```text
focus vscode
```

the user can write:

```text
Give VS Code maximum resources.

Prepare my system for machine learning training.

Close unnecessary background applications.

How much RAM is being used?

Why is my system slow?

Free unused memory safely.

Show me what is consuming CPU.
```

### AI Command Architecture

```text
User Prompt
     |
     v
AI Command Interpreter
     |
     v
Intent Detection
     |
     v
Command Validation
     |
     v
Permission / Safety Check
     |
     v
FocusOS API
     |
     v
System Action
     |
     v
Result
```

The AI must not receive unrestricted shell access.

It should call a controlled set of predefined FocusOS operations.

---

# 11. ML Training Mode

ML Training Mode is an important feature of the prototype.

When a training workload starts:

```text
ML Training Detected
        |
        v
ML Mode
        |
        v
Analyze CPU / RAM / GPU
        |
        v
Reserve Resources
        |
        v
Reduce Background Workloads
        |
        v
Run Training
        |
        v
Monitor Resources
        |
        v
Restore Normal Mode
```

Example:

```text
GPU       -> HIGH PRIORITY
CPU       -> HIGH PRIORITY
RAM       -> RESERVED
Dataset   -> HIGH I/O PRIORITY

Background Apps -> LOW
Updates         -> DEFERRED
Unused Apps     -> SUSPENDED
```

The prototype should monitor system limits and avoid unsafe hardware usage.

---

# 12. Desktop Dashboard

Create a desktop application that shows real-time system performance.

Example:

```text
+----------------------------------+
|            FocusOS              |
+----------------------------------+
| CPU       [███████---] 72%      |
| RAM       [██████----] 61%      |
| GPU       [████████--] 84%      |
| Disk      [███-------] 31%      |
+----------------------------------+
| CURRENT FOCUS                   |
| VS Code - Coding                |
+----------------------------------+
| Active Processes: 8             |
| Background Processes: 21        |
| Suspended Processes: 7          |
| Estimated RAM Saved: 2.1 GB     |
+----------------------------------+
| Mode: Focus / ML / Normal       |
+----------------------------------+
```

Dashboard should display:

- CPU usage
- RAM usage
- GPU usage where available
- Disk usage
- Network usage
- Active application
- Current focus mode
- Top resource-consuming processes
- Suspended processes
- Estimated resources saved
- ML training statistics

---

# 13. Technology Stack

## Programming

```text
Python
C/C++ later
```

## System Monitoring

```text
psutil
```

Used for:

- CPU
- RAM
- Processes
- Disk
- Network

## Windows Integration

```text
pywin32
```

Used for active-window and Windows process integration.

## Desktop UI

```text
PySide6
```

## Local API

```text
FastAPI
```

## Database

```text
SQLite
```

## Machine Learning

```text
PyTorch
```

## AI

Use an LLM API or a local LLM for natural-language command interpretation.

## Packaging

```text
PyInstaller
```

The prototype can be packaged as:

```text
FocusOS.exe
```

---

# 14. Recommended Prototype Project Structure

```text
FocusOS/
|
+-- core/
|   +-- focus_engine.py
|   +-- resource_manager.py
|   +-- ram_manager.py
|   +-- process_manager.py
|   +-- app_manager.py
|   +-- storage_manager.py
|
+-- ai/
|   +-- command_parser.py
|   +-- intent_manager.py
|   +-- llm_client.py
|
+-- ml/
|   +-- ml_mode.py
|   +-- resource_optimizer.py
|
+-- dashboard/
|   +-- main_window.py
|   +-- performance_monitor.py
|   +-- widgets/
|
+-- api/
|   +-- focus_api.py
|
+-- database/
|   +-- database.py
|
+-- tests/
|
+-- config/
|
+-- main.py
+-- requirements.txt
+-- README.md
```

---

# 15. Startup Behaviour

The prototype should be able to start automatically when the computer starts.

```text
Computer Starts
      |
      v
FocusOS Service/Application Starts
      |
      v
System Monitoring Starts
      |
      v
Focus Engine Starts
      |
      +----> Dashboard Available
      |
      +----> AI Terminal Available
```

For the first prototype, implement this as a **Windows startup application/service**.

Later, the functionality can move deeper into the operating system.

---

# 16. Testing Strategy

The main goal is to prove that FocusOS actually improves resource management.

## Test A — Normal System

Run the same workload without FocusOS optimization:

```text
VS Code
Chrome
Music
Python / ML workload
Background applications
```

Record:

- RAM usage
- CPU usage
- GPU usage
- Background process count
- ML training time
- Application response time

## Test B — FocusOS Enabled

Run exactly the same workload with FocusOS enabled.

Record the same metrics.

### Comparison

```text
Metric                  Normal      FocusOS
------------------------------------------------
RAM Usage               XX GB       XX GB
CPU Usage               XX %        XX %
Background RAM          XX GB       XX GB
Process Count           XX          XX
ML Training Time        XX min      XX min
Response Time           XX ms       XX ms
```

The project should report actual measured values rather than claiming improvement without testing.

---

# 17. Development Environment

For the first prototype:

```text
VirtualBox
     |
     v
Ubuntu / Linux VM
     |
     v
FocusOS Prototype
```

For Windows-specific features, use a controlled Windows test environment where possible.

Do not test aggressive process management on the main machine initially.

---

# 18. Development Phases

## Phase 1 — System Monitoring

Build:

- CPU monitor
- RAM monitor
- Process monitor
- Active-window detector
- Dashboard

## Phase 2 — Focus Engine

Implement:

- Active application detection
- Task classification
- Focus score
- Current-task detection

## Phase 3 — Resource Management

Implement:

- Process priority
- CPU throttling
- Safe suspension
- RAM optimization

## Phase 4 — AI Terminal

Implement:

```text
Natural Language
      |
      v
Intent
      |
      v
Safe FocusOS Command
      |
      v
Execution
```

## Phase 5 — ML Mode

Implement:

- ML workload detection
- Resource optimization
- Training monitoring

## Phase 6 — Storage Manager

Implement:

- Temporary-file scanning
- Cache analysis
- Safe cleanup

## Phase 7 — Startup Application

Package:

```text
FocusOS.exe
```

and configure it to start with the system.

## Phase 8 — Deeper OS Development

After the prototype is proven:

```text
Python Prototype
      |
      v
C/C++ Core
      |
      v
Linux System Services
      |
      v
Kernel-Level Resource Management
      |
      v
Custom FocusOS Distribution
```

---

# 19. Final Vision

The final system should combine:

```text
                    FOCUS OS
                       |
        +--------------+--------------+
        |              |              |
     Focus AI      Resource AI    AI Terminal
        |              |              |
    User Intent    CPU/RAM/GPU      Commands
        |              |              |
        +--------------+--------------+
                       |
                       v
                Intelligent OS
                       |
                       v
                Current Task First
```

## Core Philosophy

> **The computer should adapt to the user's current work instead of making the user constantly manage the computer.**

FocusOS should become:

- Task-aware
- Resource-efficient
- AI-controlled
- ML-friendly
- Performance-focused
- Safe
- Reversible
- Measurable

---

# 20. First Prototype Goal

Do not attempt to build the complete operating system first.

The first working milestone should be:

```text
Detect active application
        |
        v
Monitor CPU + RAM + processes
        |
        v
Identify current focus task
        |
        v
Prioritize the active task
        |
        v
Reduce background resource usage safely
        |
        v
Show results in FocusOS Dashboard
        |
        v
Compare performance before/after
```

Once this works reliably, add the AI terminal, ML mode, storage manager, and deeper OS-level components.


# 21. FocusOS Desktop Control Application

The FocusOS prototype must include a dedicated **desktop application** that acts as the main control center for the system.

The user must be able to control FocusOS from this application without needing to manually terminate its processes.

## Desktop Application Responsibilities

The application should provide:

- Real-time system performance monitoring
- Current focused application/task
- Current FocusOS mode
- CPU/RAM/GPU usage
- Active and background processes
- Resource-saving statistics
- AI Terminal
- FocusOS settings
- Start / Pause / Resume / Stop controls

## FocusOS Control States

The desktop application should support:

```text
RUNNING
   |
   +--> PAUSED
   |
   +--> STOPPED
   |
   +--> RESUMED
```

### RUNNING

FocusOS actively:

- Detects the current task
- Monitors resources
- Manages background processes
- Applies focus priorities
- Runs configured optimization rules

### PAUSED

FocusOS remains open, but automatic optimization is temporarily disabled.

```text
Monitoring → ON
Optimization → OFF
```

This is useful when the user wants to temporarily prevent FocusOS from changing process priorities.

### STOPPED

The FocusOS resource-management engine is stopped.

```text
Focus Engine       → OFF
Resource Manager   → OFF
Background Manager → OFF
Automatic Actions  → OFF
```

The desktop application itself may remain open so the user can start/resume FocusOS again.

### RESUMED

When the user selects **Resume**, FocusOS should safely restart its monitoring and optimization components.

```text
Resume
  |
  v
Check system state
  |
  v
Start monitoring
  |
  v
Detect current task
  |
  v
Resume optimization
```

## Main Dashboard Controls

The dashboard should have a clearly visible control section:

```text
+--------------------------------------+
|             FocusOS                 |
+--------------------------------------+
| Status: RUNNING                     |
|                                      |
| Current Focus: VS Code              |
| CPU: 72%                            |
| RAM: 61%                            |
| GPU: 84%                            |
|                                      |
| [ PAUSE ]  [ STOP ]  [ RESUME ]    |
|                                      |
| AI Terminal                          |
| > Prepare system for ML training     |
|                                      |
+--------------------------------------+
```

Only the controls that make sense for the current state should be enabled.

For example:

```text
RUNNING:
[Pause] [Stop]

PAUSED:
[Resume] [Stop]

STOPPED:
[Start/Resume]
```

## Safe Stop Requirement

Stopping FocusOS must **not** stop or kill the user's applications.

It should only stop FocusOS's own optimization and monitoring services.

For example:

```text
User clicks STOP
       |
       v
FocusOS confirms action
       |
       v
Stop FocusOS optimization
       |
       v
Restore managed processes to safe/default state
       |
       v
FocusOS remains available for restart
```

The user should never lose unsaved work because FocusOS was stopped.

## Emergency Disable

Include an **Emergency Disable** option for situations where the user believes FocusOS is causing unwanted system behavior.

```text
Emergency Disable
       |
       v
Disable automatic optimization
       |
       v
Stop FocusOS background service
       |
       v
Leave normal OS operation untouched
```

This is an important safety feature during development and testing.

---

# 22. Desktop Application Architecture

```text
                       FocusOS Desktop App
                              |
          +-------------------+-------------------+
          |                   |                   |
     Dashboard           AI Terminal         Settings
          |                   |                   |
          +-------------------+-------------------+
                              |
                       FocusOS Controller
                              |
                 +------------+------------+
                 |            |            |
           Focus Engine   Resource     Process
                         Manager       Manager
                 |            |            |
                 +------------+------------+
                              |
                       Operating System
```

The desktop application should communicate with the FocusOS core through a controlled local API rather than directly manipulating every system component.

Recommended prototype architecture:

```text
PySide6 Desktop App
        |
        v
FastAPI / Local IPC
        |
        v
FocusOS Core
        |
        +--> Focus Engine
        +--> Resource Manager
        +--> Process Manager
        +--> RAM Manager
        +--> ML Manager
```

---

# 23. FocusOS State Management

The application should maintain a central state:

```text
FocusOSState =
{
    status: RUNNING | PAUSED | STOPPED,
    focus_application: "...",
    focus_mode: "...",
    cpu_usage: 0,
    ram_usage: 0,
    gpu_usage: 0,
    active_processes: 0,
    background_processes: 0,
    suspended_processes: 0
}
```

Every dashboard component should read from this state instead of independently controlling FocusOS.

This prevents conflicting commands.

---

# 24. User Control Principle

FocusOS should always follow:

> **Automatic optimization, but complete user control.**

The user must always be able to:

```text
View what FocusOS is doing
        |
        v
Pause it
        |
        v
Stop it
        |
        v
Resume it
```

The system should not lock the user into automatic optimization.

---

# 25. Updated First Prototype Goal

The first usable prototype should now contain:

```text
                  FocusOS Prototype
                         |
        +----------------+----------------+
        |                |                |
  Focus Engine     Resource Manager   Desktop App
        |                |                |
        +----------------+----------------+
                         |
                 System Monitoring
                         |
        +----------------+----------------+
        |                |                |
       CPU              RAM            Processes
                         |
                         v
                 FocusOS Dashboard
                         |
        +----------------+----------------+
        |                |                |
     AI Terminal    Pause/Stop/Resume   Settings
```

The prototype is considered successful when the user can:

1. Start FocusOS.
2. See live system performance.
3. Detect the currently active application.
4. Identify the current task.
5. Automatically prioritize the current task.
6. Reduce background resource usage safely.
7. See the effect on CPU/RAM/processes.
8. Pause FocusOS from the desktop application.
9. Stop FocusOS from the desktop application.
10. Resume FocusOS from the desktop application.
11. Use the AI Terminal to request supported system actions.
12. Compare system performance with FocusOS enabled and disabled.
