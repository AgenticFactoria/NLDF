# Factory Agent System

A complete AI-powered factory automation system that processes orders and commands AGVs using OpenAI Agent SDK with session-based memory.

## System Architecture

```
Order MQTT → OrderMQTTHandler → SharedOrderManager → FactoryAgentManager → AGV Commands
                ↓                       ↓                      ↓              ↓
            Store Orders          Track Products         AI Decision      MQTT Publish
                                                         (with memory)
```

## Key Components

### 1. **OrderMQTTHandler** (`src/order_mqtt_handler.py`)

- Listens to order MQTT messages
- Validates and processes order data
- Stores orders in SharedOrderManager
- **Input Format**:

```json
{
  "order_id": "order_c88d7023",
  "created_at": 90.0,
  "items": [
    { "product_type": "P1", "quantity": 1 },
    { "product_type": "P2", "quantity": 1 }
  ],
  "priority": "medium",
  "deadline": 810.0
}
```

### 2. **FactoryAgentManager** (`src/factory_agent_manager.py`)

- **Core AI agent** powered by OpenAI Agent SDK
- **Session-based memory** using SQLiteSession for conversation history
- Processes **max 2 orders** per cycle
- Generates AGV commands based on factory state
- **Command history storage** and response tracking

### 3. **AgentCommandHistory**

- Stores all agent commands and system responses
- Provides recent history for context
- Enables learning from previous actions

### 4. **Main Integration** (`main_factory_system.py`)

- Combines order handling + AI processing
- Concurrent operation using threading + asyncio
- Complete system lifecycle management

## Features

### 🧠 **AI Agent with Memory**

```python
# OpenAI Agent SDK with persistent sessions
session = SQLiteSession("factory_agent_line1_session")
result = await Runner.run(agent, query, session=session)
```

### 📋 **Order Processing**

- **Max 2 orders** processed simultaneously
- Priority-based order selection
- Product type workflow handling (P1/P2 vs P3)

### 🤖 **AGV Command Generation**

The AI agent generates JSON commands:

```json
[
  {
    "command_id": "move_001",
    "action": "move",
    "target": "AGV_1",
    "params": { "target_point": "P1" }
  },
  {
    "command_id": "load_002",
    "action": "load",
    "target": "AGV_2",
    "params": { "product_id": "prod_p1_123" }
  }
]
```

### 📊 **History & Context Management**

- Command execution history
- System response tracking
- Session-based conversation memory
- Recent context for decision making

## Available AGV Actions

| Action   | Description             | Parameters                      |
| -------- | ----------------------- | ------------------------------- |
| `move`   | Move AGV to location    | `target_point`: P0-P9           |
| `load`   | Load product onto AGV   | `product_id`: (for RawMaterial) |
| `unload` | Unload product from AGV | None                            |
| `charge` | Charge AGV battery      | `target_level`: 80.0 (default)  |

## Location Mapping

| Point | Location     | Description          |
| ----- | ------------ | -------------------- |
| P0    | RawMaterial  | Raw material storage |
| P1    | StationA     | Processing station A |
| P2    | Conveyor_AB  | Conveyor A→B         |
| P3    | StationB     | Processing station B |
| P4    | Conveyor_BC  | Conveyor B→C         |
| P5    | StationC     | Processing station C |
| P6    | Conveyor_CQ  | Conveyor C→Quality   |
| P7-P8 | QualityCheck | Quality control      |
| P9    | Warehouse    | Finished goods       |

## Product Workflows

### P1/P2 Products:

```
RawMaterial → [AGV] → StationA → Conveyor_AB → StationB →
Conveyor_BC → StationC → Conveyor_CQ → QualityCheck → [AGV] → Warehouse
```

### P3 Products (Double Processing):

```
RawMaterial → [AGV] → StationA → Conveyor_AB → StationB → Conveyor_BC →
StationC → Conveyor_CQ → [AGV] → StationB → Conveyor_BC → StationC →
Conveyor_CQ → QualityCheck → [AGV] → Warehouse
```

## Usage

### 1. **Complete System**

```bash
# Set OpenAI API key
export OPENAI_API_KEY='your-key-here'

# Run complete system (order listening + AI processing)
python main_factory_system.py
```

### 2. **Test System**

```bash
# Test with sample data
python test_factory_system.py
```

### 3. **Order Handler Only**

```bash
# Just listen for orders
python src/order_mqtt_handler.py
```

### 4. **Agent Manager Only**

```bash
# Just AI processing (requires pre-loaded orders)
python src/factory_agent_manager.py
```

## Configuration

### Environment Variables

```bash
# Required
OPENAI_API_KEY=your-openai-api-key

# MQTT Settings
MQTT_BROKER_HOST=ec2-13-212-179-9.ap-southeast-1.compute.amazonaws.com
MQTT_BROKER_PORT=1883

# Agent Settings
AGENT_DECISION_INTERVAL=5.0
AGV_BATTERY_THRESHOLD=30.0
```

### Agent Behavior

- **Processing Interval**: 5 seconds between cycles
- **Max Orders**: 2 orders per processing cycle
- **AGV Management**: 2 AGVs per production line
- **Session Persistence**: SQLite-based conversation memory

## MQTT Topics

### Subscribed (Input)

- `AgenticFactoria/line1/orders/status` - New orders
- `AgenticFactoria/line1/response/line1` - Command responses

### Published (Output)

- `AgenticFactoria/line1/command/line1` - AGV commands

## Agent Instructions

The AI agent is configured with comprehensive factory knowledge:

- **Production line management** for line1
- **AGV coordination** (AGV_1, AGV_2)
- **Order processing** strategy (max 2 at once)
- **KPI optimization** focus
- **Product workflow** understanding
- **Resource management** (battery, capacity)

## Session Memory Example

```python
# First interaction
result = await Runner.run(agent, "Move AGV_1 to RawMaterial", session=session)

# Later interaction - agent remembers previous context
result = await Runner.run(agent, "What's the status of that AGV?", session=session)
# Agent knows which AGV and its previous state
```

## Error Handling

- **MQTT connection** retry logic
- **Command validation** before execution
- **Session recovery** on restart
- **Order processing** error isolation
- **Agent response** parsing with fallbacks

## Monitoring & Logging

- **Structured logging** for all components
- **Command history** tracking
- **Response correlation** with command IDs
- **Performance metrics** (processing time, success rate)
- **Session state** persistence

This system provides a complete, production-ready factory agent that can intelligently process orders, manage AGVs, and maintain conversation history for continuous learning and optimization.
