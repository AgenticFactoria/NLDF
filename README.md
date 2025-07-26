# SUPCON NLDF (Natural Language Driven Factory) Simulator

[![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://python.org)
[![OpenAI](https://img.shields.io/badge/OpenAI-Agent%20SDK-green.svg)](https://github.com/openai/openai-python)
[![MQTT](https://img.shields.io/badge/MQTT-Industrial%20IoT-orange.svg)](https://mqtt.org)
[![License](https://img.shields.io/badge/License-Hackathon-red.svg)](LICENSE)

## 🏭 Overview

The NLDF project represents a cutting-edge fusion of artificial intelligence and industrial automation, creating an intelligent factory simulation system that demonstrates the future of Industry 4.0. This system uses natural language processing and AI agents to autonomously manage a multi-line production facility with real-time decision-making capabilities.

## 🚀 Key Features

- **AI-Driven Decision Making**: OpenAI Agent SDK powers intelligent production line management
- **Multi-Line Coordination**: Simultaneous operation of 3 production lines with 6 AGVs
- **Real-Time Communication**: MQTT-based IoT communication with industrial-grade reliability
- **Reactive Processing**: Sub-2-second response to critical factory events
- **Product Flow Intelligence**: Specialized handling of P1/P2 single-pass and P3 double-pass workflows
- **Industrial Integration**: Native supOS-CE platform compatibility

## 🏗️ Technical Architecture

### Core AI Framework

**OpenAI Agent SDK Integration**

- **Agent Engine**: `openai-agents>=0.2.3` provides the core AI decision-making capabilities
- **Specialized Agents**: `ProductFlowAgent` with deep understanding of factory workflows
- **Model Support**: GPT-4.1-mini for efficient natural language processing and command generation
- **Session Management**: SQLite-based context preservation and decision history tracking

### Communication & Messaging Layer

**Industrial MQTT Stack**

- **Protocol**: Paho MQTT (`paho-mqtt>=2.1.0`) for reliable industrial communication
- **Broker**: supOS-CE platform MQTT broker (`supos-ce-instance4.supos.app:1883`)
- **QoS Management**:
  - QoS 1 for critical commands (guaranteed delivery)
  - QoS 0 for status updates (optimized for throughput)
- **Resilience**: Automatic reconnection and message queuing

**Communication Patterns**

- **Subscribe Topics**: Device status, alerts, orders, KPI updates
- **Publish Topics**: AGV commands, system responses
- **Wildcard Support**: Flexible message filtering with MQTT wildcards
- **Topic Management**: Centralized topic namespace management

### Data Validation & Configuration

**Pydantic Data Models**

- **Strict Typing**: `pydantic>=2.11.7` ensures data integrity
- **Device Models**: `AGVStatus`, `StationStatus`, `ConveyorStatus`, `WarehouseStatus`
- **Validation**: Automatic data validation and type checking
- **Serialization**: JSON serialization for MQTT communication

**Configuration Management**

- **Environment Variables**: `python-dotenv` for flexible configuration
- **YAML Configuration**: `pyyaml>=6.0.2` for factory layout and game rules
- **Multi-Environment**: Support for development, testing, and production configs

### System Architecture Patterns

**Modular Design**

- **Separation of Concerns**: MQTT communication, AI decisions, and business logic are decoupled
- **Component Architecture**:
  - `MQTTListenerManager`: Message handling and factory state management
  - `LineCommander`: Central coordination and decision orchestration
  - `ProductFlowAgent`: Specialized AI for production workflow optimization
  - `SharedOrderManager`: Cross-line order coordination

**Asynchronous Concurrency**

- **AsyncIO Foundation**: High-performance async processing
- **Concurrent Lines**: All 3 production lines operate simultaneously
- **Event-Driven**: Reactive processing for critical factory events
- **Graceful Shutdown**: Proper resource cleanup and state preservation

**Event-Driven Architecture**

- **Priority Queue**: Critical, High, Medium, Low severity event processing
- **Reactive Events**: Battery alerts, equipment blockages, product completion
- **Pub-Sub Pattern**: Loose coupling between system components
- **Audit Trail**: Complete event tracking and decision logging

## 🎯 Production Workflow Intelligence

### Product Types & Processing

**P1/P2 Products (Single Processing)**

```
RawMaterial → [AGV] → StationA → [AUTO: Conveyor_AB → StationB → Conveyor_BC → StationC → Conveyor_CQ] → QualityCheck → [AGV] → Warehouse
```

**P3 Products (Double Processing)**

```
RawMaterial → [AGV] → StationA → [AUTO] → Conveyor_CQ[upper_buffer] → [AGV_2 ONLY] → StationB → [AUTO] → QualityCheck → [AGV] → Warehouse
```

### Critical Decision Priorities

1. **CRITICAL**: AGV battery < 20% → Emergency charging
2. **HIGH**: AGV with payload idle → Complete delivery immediately
3. **HIGH**: Finished products in QualityCheck → Deliver to warehouse
4. **HIGH**: P3 products in Conveyor_CQ upper_buffer → AGV_2 second processing
5. **HIGH**: Raw materials available → Start new production
6. **MEDIUM**: AGV battery < 40% and idle → Preventive charging

### AGV Coordination Rules

- **AGV_1**: Can access Conveyor_CQ lower_buffer only
- **AGV_2**: Can access Conveyor_CQ upper_buffer (required for P3 second processing)
- **Payload Priority**: Loaded AGVs take precedence over empty AGV operations
- **Battery Management**: Proactive charging to prevent production interruptions

## 🚀 Quick Start

### Prerequisites

- Python 3.11.9+
- OpenAI API key
- UV package manager

### Installation

```bash
# Install UV package manager
curl -LsSf https://astral.sh/uv/install.sh | sh

# Clone repository
https://github.com/AgenticFactoria/NLDF
cd nldf

# Install dependencies
uv sync
```

### Configuration and Set Up

```bash
# Set OpenAI API key in .env, follow .env.example
OPENAI_API_KEY='your-api-key-here'
```

**Start NLDF Agents**

```bash
uv run main.py
```

**Start the Factory Simulation**

```bash
# simulation system
git clone https://github.com/supcon-international/25-AdventureX-SUPCON-Hackathon.git
cd 25-AdventureX-SUPCON-Hackathon
uv sync
uv run run_multi_line_simulation.py
```

### Unity Frontend

1. Configure `StreamingAssets/MQTTBroker.json`:

```json
{
  "wss": {
    "port": 8084,
    "host": "supos-ce-instance4.supos.app",
    "client_id": "YOUR_UNIQUE_CLIENT_ID"
  },
  "common_topic": {
    "Root_Topic_Head": "YOUR_TOPIC_ROOT"
  }
}
```

2. Use VSCode Live Server plugin to serve `index.html` for WebGL Unity interface

## 🤝 Contributing

This project demonstrates concepts in:

- Industrial IoT communication protocols
- AI-driven decision making in manufacturing
- Real-time system architecture
- Event-driven programming patterns

## 📄 License

This project is part of the SUPCON AdventureX Hackathon and follows the competition guidelines and licensing terms.
