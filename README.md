# Cronos CLI - Time Tracking TUI

A powerful Terminal User Interface (TUI) application for tracking time and managing tasks, built with Python and Textual.

## Features

- ⏱️ **Time Tracking**: Start, pause, and stop timers for tasks
- 📋 **Task Management**: Create, edit, and delete tasks
- 📊 **Daily Summary**: View total time spent on each task today
- 💾 **Persistent Storage**: All data stored in JSON files
- ⌨️ **Keyboard Shortcuts**: Efficient navigation and control
- 🎨 **Beautiful TUI**: Clean, colorful terminal interface

## Installation

### Prerequisites

- Python 3.13+
- uv package manager

### Setup

1. Clone or navigate to the project directory:
```bash
cd cronos_cli
```

2. Install dependencies:
```bash
make install
```

## Usage

### Running the Application

```bash
make run
```

Or install and run in one command:
```bash
make dev
```

### Keyboard Shortcuts

| Key | Action | Description |
|-----|--------|-------------|
| `↑` / `↓` / `k` / `j`| Navigate | Move through task list |
| `Enter` | Select | Select a task |
| `Space` | Start/Pause | Start or pause timer for selected task |
| `s` | Stop | Stop the current timer and save |
| `n` | New Task | Create a new task |
| `e` | Edit Task | Edit the selected task |
| `d` | Delete Task | Delete the selected task |
| `r` | Refresh | Refresh task list and summary |
| `q` | Quit | Exit the application |

### Task Form Shortcuts

When creating or editing a task:

| Key | Action |
|-----|--------|
| `Ctrl+s` | Save task |
| `Esc` | Cancel |

### Confirmation Dialog

| Key | Action |
|-----|--------|
| `y` | Confirm (Yes) |
| `n` | Cancel (No) |
| `Esc` | Cancel |

## Data Storage

All data is stored in the `data/` directory:

- **tasks.json**: Contains all your tasks
- **YYYY-MM-DD.json**: Daily time tracking entries (one file per day)

Example file structure:
```
data/
├── tasks.json
├── 2026-03-13.json
├── 2026-03-14.json
└── ...
```

### Task Data Format

```json
[
  {
    "id": "unique-uuid",
    "name": "Task Name",
    "description": "Task description",
    "created_at": "2026-03-13T10:30:00"
  }
]
```

### Daily Time Entry Format

```json
[
  {
    "id": "unique-uuid",
    "task_id": "task-uuid",
    "task_name": "Task Name",
    "start_time": "2026-03-13T10:30:00",
    "end_time": "2026-03-13T11:30:00",
    "paused_at": null,
    "total_seconds": 3600.0
  }
]
```

## Workflow

1. **Create Tasks**: Press `n` to create a new task
2. **Select Task**: Use arrow keys or the vim j and k and Enter to select a task
3. **Start Tracking**: Press `Space` to start the timer
4. **Pause/Resume**: Press `Space` again to pause/resume
5. **Stop Timer**: Press `s` to stop and save the time entry

## Development

### Make Commands

- `make help` - Show available commands
- `make install` - Install dependencies
- `make run` - Run the application
- `make dev` - Install and run
- `make clean` - Clean up generated files

## Tips

- Tasks persist across days, so you can reuse them in displaying statistics on a stats screen
- Each day gets its own JSON file for historical tracking
- The timer of a task that has been started continues to count even when switching between tasks
- Total time shown next to task names is for today only

## Requirements

- textual>=8.1.1
- Python>=3.13

## License

MIT
