#!/usr/bin/env python3
"""
Factory Agent Manager
Manages AI agents that process orders and command AGVs using OpenAI Agent SDK.
"""

import asyncio
import json
import logging
import os
import sys
from datetime import datetime
from typing import Any, Dict, List

# Add parent directory to path to import modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents import Agent, Runner, SQLiteSession

from config.settings import MQTT_BROKER_HOST, MQTT_BROKER_PORT
from shared_order_manager import SharedOrderManager
from utils.mqtt_client import MQTTClient
from utils.topic_manager import TopicManager

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class AgentCommandHistory:
    """Stores agent command history and responses."""

    def __init__(self):
        self.commands: List[Dict[str, Any]] = []
        self.responses: List[Dict[str, Any]] = []
        self.session_data: Dict[str, Any] = {}

    def add_command(self, command: Dict[str, Any], timestamp: float = None):
        """Add a command to history."""
        if timestamp is None:
            timestamp = datetime.now().timestamp()

        command_entry = {
            "timestamp": timestamp,
            "command": command,
            "command_id": command.get("command_id", f"cmd_{len(self.commands)}"),
        }
        self.commands.append(command_entry)
        logger.info(f"Added command to history: {command_entry['command_id']}")

    def add_response(self, response: Dict[str, Any]):
        """Add a response to history."""
        self.responses.append(response)
        logger.info(
            f"Added response to history: {response.get('command_id', 'unknown')}"
        )

    def get_recent_commands(self, count: int = 5) -> List[Dict[str, Any]]:
        """Get the most recent commands."""
        return self.commands[-count:] if self.commands else []

    def get_recent_responses(self, count: int = 5) -> List[Dict[str, Any]]:
        """Get the most recent responses."""
        return self.responses[-count:] if self.responses else []


class FactoryAgentManager:
    """Manages AI agents for factory automation using OpenAI Agent SDK."""

    def __init__(self, line_id: str = "line1", max_orders_per_cycle: int = 2):
        self.line_id = line_id
        self.max_orders_per_cycle = max_orders_per_cycle

        # MQTT communication
        self.mqtt_client = MQTTClient(
            host=MQTT_BROKER_HOST,
            port=MQTT_BROKER_PORT,
            client_id=f"factory_agent_{line_id}",
        )

        # Order management
        self.shared_order_manager = SharedOrderManager()

        # Topic management
        self.topic_manager = TopicManager("AgenticFactoria")

        # Agent history and session management
        self.command_history = AgentCommandHistory()
        self.session = SQLiteSession(f"factory_agent_{line_id}_session")

        # Current state tracking
        self.current_factory_state = {}
        self.active_agvs = ["AGV_1", "AGV_2"]  # Available AGVs for this line

        # Agent configuration (after active_agvs is defined)
        self.agent = self._create_factory_agent()

        # Processing control
        self.is_processing = False
        self.processing_interval = 5.0  # Process every 5 seconds

        # Reactive event processing
        self.reactive_queue = asyncio.Queue(maxsize=50)
        self.is_running = False

    def _create_factory_agent(self) -> Agent:
        """Create the factory AI agent with specific instructions."""
        instructions = f"""
You are an AI agent controlling production line {self.line_id} in a factory automation system.

RESPONSIBILITIES:
- Manage AGVs ({", ".join(self.active_agvs)}) to fulfill production orders
- Monitor station status and coordinate product flow
- React to real-time factory events and status changes
- Optimize for KPI metrics: order completion rate, production efficiency, AGV utilization

AVAILABLE ACTIONS:
1. move: Move AGV to specific location (P0-P9)
   - P0: RawMaterial, P1: StationA, P2: Conveyor_AB, P3: StationB
   - P4: Conveyor_BC, P5: StationC, P6: Conveyor_CQ, P7-P8: QualityCheck, P9: Warehouse

2. load: Load product from current location onto AGV (specify product_id for RawMaterial)
3. unload: Unload product from AGV to current location  
4. charge: Send AGV to charge (when battery < 30%, target_level default 80%)

COMMAND FORMAT:
Always respond with a JSON array of commands:
[
  {{
    "command_id": "unique_id",
    "action": "move|load|unload|charge",
    "target": "AGV_1|AGV_2", 
    "params": {{"target_point": "P1", "product_id": "prod_...", "target_level": 80.0}}
  }}
]

REACTIVE DECISION MAKING:
You will receive real-time updates about:
- Station statuses (idle, processing, blocked)
- AGV statuses (idle, moving, charging, battery levels)
- Conveyor statuses and buffer levels
- Factory alerts and bottlenecks

React immediately to:
- Idle stations with products ready for pickup
- AGVs with low battery (<30%)
- Blocked stations or conveyors
- Idle AGVs that could be productive
- Critical factory alerts

STRATEGY:
- Prioritize orders by deadline and priority
- Balance AGV workload efficiently
- Ensure AGVs are charged before long operations
- Minimize idle time and maximize throughput
- Handle products according to their type (P1/P2 vs P3 different flows)
- React quickly to status changes to prevent bottlenecks

Product P1/P2 Flow:
RawMaterial → [AGV] → StationA → Conveyor_AB → StationB → Conveyor_BC → StationC → Conveyor_CQ → QualityCheck → [AGV] → Warehouse

Product P3 Flow (Double Processing):
RawMaterial → [AGV] → StationA → Conveyor_AB → StationB → Conveyor_BC → StationC → Conveyor_CQ → [AGV] → StationB → Conveyor_BC → StationC → Conveyor_CQ → QualityCheck → [AGV] → Warehouse

Remember: P3 products require double processing at StationB and StationC.
"""

        return Agent(
            name=f"FactoryAgent_{self.line_id}",
            instructions=instructions,
            model="gpt-4.1-mini",
        )

    def start_mqtt_listening(self):
        """Start MQTT communication for all factory device statuses."""
        try:
            logger.info("Starting comprehensive MQTT communication...")
            self.mqtt_client.connect()

            # Subscribe to command responses
            response_topic = f"{self.topic_manager.root}/response/{self.line_id}"
            self.mqtt_client.subscribe(response_topic, self._on_response_message)
            logger.info(f"Subscribed to response topic: {response_topic}")

            # Subscribe to order topic to receive new orders
            self.mqtt_client.subscribe(
                self.topic_manager.get_order_topic(), self._on_order_message
            )
            logger.info(
                f"Subscribed to order topic: {self.topic_manager.get_order_topic()}"
            )

            for line in ["line1"]:
                root_topic = "AgenticFactoria"
                self.mqtt_client.subscribe(
                    f"{root_topic}/{line}/station/+/status",
                    self._on_station_status_message,
                )
                self.mqtt_client.subscribe(
                    f"{root_topic}/{line}/agv/+/status", self._on_agv_status_message
                )
                self.mqtt_client.subscribe(
                    f"{root_topic}/{line}/conveyor/+/status",
                    self._on_conveyor_status_message,
                )
                self.mqtt_client.subscribe(
                    f"{root_topic}/{line}/alerts", self._on_alert_message
                )
            self.mqtt_client.subscribe(
                f"{root_topic}/warehouse/+/status", self._on_warehouse_status_message
            )
            logger.info("Successfully started comprehensive MQTT listening")

        except Exception as e:
            logger.error(f"Failed to start MQTT listening: {e}")
            raise

    def _on_response_message(self, topic: str, payload: bytes):
        """Handle MQTT response messages."""
        try:
            payload_str = payload.decode("utf-8")
            response_data = json.loads(payload_str)

            logger.info(f"Received response on topic {topic}: {response_data}")
            self.command_history.add_response(response_data)

        except Exception as e:
            logger.error(f"Error processing response message: {e}")

    def _on_order_message(self, topic: str, payload: bytes):
        """Handle incoming order MQTT messages."""
        try:
            payload_str = payload.decode("utf-8")
            order_data = json.loads(payload_str)

            logger.info(f"Received new order on topic {topic}: {order_data}")

            # Process the order using SharedOrderManager
            order = self.shared_order_manager.process_order(order_data, self.line_id)

            if order:
                logger.info(
                    f"Successfully processed order {order.order_id} with {len(order.products)} products"
                )
            else:
                logger.warning(f"Failed to process order from MQTT: {order_data}")

        except Exception as e:
            logger.error(f"Error processing order message: {e}")

    def _on_station_status_message(self, topic: str, payload: bytes):
        """Handle station status updates and trigger reactive decisions."""
        try:
            payload_str = payload.decode("utf-8")
            station_data = json.loads(payload_str)

            # Extract station ID from topic
            station_id = topic.split("/")[-2]  # e.g., "StationA"

            logger.info(
                f"Station {station_id} status update: {station_data.get('status', 'unknown')}"
            )

            # Update current factory state
            if "stations" not in self.current_factory_state:
                self.current_factory_state["stations"] = {}
            self.current_factory_state["stations"][station_id] = station_data

            # Trigger reactive processing for critical station states
            self._handle_station_status_change(station_id, station_data)

        except Exception as e:
            logger.error(f"Error processing station status message: {e}")

    def _on_agv_status_message(self, topic: str, payload: bytes):
        """Handle AGV status updates and trigger reactive decisions."""
        try:
            payload_str = payload.decode("utf-8")
            agv_data = json.loads(payload_str)

            # Extract AGV ID from topic
            agv_id = topic.split("/")[-2]  # e.g., "AGV_1"

            logger.info(
                f"AGV {agv_id} status update: {agv_data.get('status', 'unknown')} at {agv_data.get('current_point', 'unknown')}"
            )

            # Update current factory state
            if "agvs" not in self.current_factory_state:
                self.current_factory_state["agvs"] = {}
            self.current_factory_state["agvs"][agv_id] = agv_data

            # Trigger reactive processing for critical AGV states
            self._handle_agv_status_change(agv_id, agv_data)

        except Exception as e:
            logger.error(f"Error processing AGV status message: {e}")

    def _on_conveyor_status_message(self, topic: str, payload: bytes):
        """Handle conveyor status updates."""
        try:
            payload_str = payload.decode("utf-8")
            conveyor_data = json.loads(payload_str)

            # Extract conveyor ID from topic
            conveyor_id = topic.split("/")[-2]  # e.g., "Conveyor_AB"

            logger.info(
                f"Conveyor {conveyor_id} status: {conveyor_data.get('status', 'unknown')}"
            )

            # Update current factory state
            if "conveyors" not in self.current_factory_state:
                self.current_factory_state["conveyors"] = {}
            self.current_factory_state["conveyors"][conveyor_id] = conveyor_data

            # Check for blocked conveyors or buffer issues
            self._handle_conveyor_status_change(conveyor_id, conveyor_data)

        except Exception as e:
            logger.error(f"Error processing conveyor status message: {e}")

    def _on_warehouse_status_message(self, topic: str, payload: bytes):
        """Handle warehouse status updates."""
        try:
            payload_str = payload.decode("utf-8")
            warehouse_data = json.loads(payload_str)

            logger.info(
                f"RawMaterial Warehouse status update: {len(warehouse_data.get('buffer', []))} products"
            )

            # Update current factory state
            self.current_factory_state["warehouse"] = warehouse_data

        except Exception as e:
            logger.error(f"Error processing warehouse status message: {e}")

    def _on_alert_message(self, topic: str, payload: bytes):
        """Handle factory alerts and trigger emergency responses."""
        try:
            payload_str = payload.decode("utf-8")
            alert_data = json.loads(payload_str)

            logger.warning(f"Factory alert: {alert_data}")

            # Store alerts for agent context
            if "alerts" not in self.current_factory_state:
                self.current_factory_state["alerts"] = []
            self.current_factory_state["alerts"].append(alert_data)

            # Trigger immediate reactive processing for critical alerts
            self._handle_factory_alert(alert_data)

        except Exception as e:
            logger.error(f"Error processing alert message: {e}")

    def _handle_station_status_change(
        self, station_id: str, station_data: Dict[str, Any]
    ):
        """Handle station status changes and trigger reactive decisions."""
        status = station_data.get("status", "unknown")
        buffer = station_data.get("buffer", [])

        # Only trigger agent for critical station issues that require immediate action
        if status == "blocked":
            logger.warning(
                f"Station {station_id} is blocked - needs immediate attention"
            )
            self._queue_critical_event(
                "station_blocked", {"station_id": station_id, "severity": "high"}
            )
        elif status == "idle" and len(buffer) > 3:  # Only if significant backup
            logger.info(
                f"Station {station_id} idle with {len(buffer)} products - may need pickup"
            )
            self._queue_critical_event(
                "station_idle_with_backup",
                {
                    "station_id": station_id,
                    "buffer_count": len(buffer),
                    "severity": "medium",
                },
            )
        else:
            # For minor status changes, just log - don't trigger agent
            logger.debug(
                f"Station {station_id} status: {status}, buffer: {len(buffer)}"
            )

    def _handle_agv_status_change(self, agv_id: str, agv_data: Dict[str, Any]):
        """Handle AGV status changes and trigger reactive decisions."""
        status = agv_data.get("status", "unknown")
        battery = agv_data.get("battery_level", 100)
        current_point = agv_data.get("current_point", "unknown")
        payload = agv_data.get("payload", [])

        # Only trigger agent for critical AGV issues
        if battery < 20 and status != "charging":  # Critical battery level
            logger.warning(
                f"AGV {agv_id} has critically low battery ({battery}%) - immediate charging needed"
            )
            self._queue_critical_event(
                "agv_critical_battery",
                {
                    "agv_id": agv_id,
                    "battery_level": battery,
                    "current_point": current_point,
                    "severity": "high",
                },
            )
        elif status == "idle" and len(payload) > 0:  # Loaded but stuck
            logger.info(f"AGV {agv_id} is idle but loaded - needs to unload")
            self._queue_critical_event(
                "agv_loaded_idle",
                {
                    "agv_id": agv_id,
                    "payload_count": len(payload),
                    "current_point": current_point,
                    "severity": "medium",
                },
            )
        else:
            # For routine status changes (normal idle, normal battery), just log
            logger.debug(
                f"AGV {agv_id} status: {status} at {current_point}, battery: {battery}%"
            )

    def _handle_conveyor_status_change(
        self, conveyor_id: str, conveyor_data: Dict[str, Any]
    ):
        """Handle conveyor status changes."""
        status = conveyor_data.get("status", "unknown")
        buffer = conveyor_data.get("buffer", [])

        if status == "blocked" or len(buffer) > 5:  # Buffer getting full
            logger.warning(
                f"Conveyor {conveyor_id} may need attention - status: {status}, buffer: {len(buffer)}"
            )

    def _handle_factory_alert(self, alert_data: Dict[str, Any]):
        """Handle critical factory alerts."""
        alert_type = alert_data.get("alert_type", "unknown")
        device_id = alert_data.get("device_id", "unknown")

        logger.critical(f"Factory alert {alert_type} for device {device_id}")

        # Only queue truly critical alerts that require agent intervention
        if alert_type in ["device_fault", "emergency_stop", "fire_alarm"]:
            self._queue_critical_event(
                "critical_alert",
                {
                    "alert_type": alert_type,
                    "device_id": device_id,
                    "severity": "critical",
                },
            )
        elif alert_type in ["buffer_full", "agv_battery_low"]:
            self._queue_critical_event(
                "operational_alert",
                {"alert_type": alert_type, "device_id": device_id, "severity": "high"},
            )
        else:
            # Log other alerts but don't trigger agent processing
            logger.info(f"Non-critical alert logged: {alert_type} for {device_id}")

    def _queue_critical_event(self, event_type: str, event_data: Dict[str, Any]):
        """Queue only critical events that require agent intervention."""
        event = {
            "type": event_type,
            "data": event_data,
            "timestamp": datetime.now().timestamp(),
            "severity": event_data.get("severity", "medium"),
        }

        try:
            self.reactive_queue.put_nowait(event)
            logger.info(
                f"Queued critical event: {event_type} (severity: {event_data.get('severity')})"
            )
        except asyncio.QueueFull:
            logger.error(f"Critical event queue is full, dropping {event_type} event")

    async def _process_critical_events(self):
        """Process critical events from the queue using the agent with session."""
        logger.info("Starting critical event processor...")

        while self.is_running:
            try:
                # Wait for a critical event with timeout
                event = await asyncio.wait_for(self.reactive_queue.get(), timeout=2.0)

                # Only process if not doing main order processing
                if self.is_processing:
                    logger.debug(
                        f"Main processing active, deferring critical event: {event['type']}"
                    )
                    # Put it back in the queue for later
                    await asyncio.sleep(1.0)
                    try:
                        self.reactive_queue.put_nowait(event)
                    except asyncio.QueueFull:
                        logger.warning("Queue full, dropping deferred event")
                    continue

                severity = event["data"].get("severity", "medium")
                event_type = event["type"]

                logger.info(
                    f"Processing critical event: {event_type} (severity: {severity})"
                )

                # Create agent query for the critical event
                query = f"""
CRITICAL FACTORY EVENT - IMMEDIATE RESPONSE NEEDED

Event Type: {event_type}
Severity: {severity}
Event Data: {json.dumps(event["data"], indent=2)}

Current Factory State:
{json.dumps(self.current_factory_state, indent=2)}

Recent Commands:
{json.dumps(self.command_history.get_recent_commands(2), indent=2)}

TASK:
A critical event has occurred requiring immediate action. Analyze and provide specific commands to address this issue.

Priority actions based on severity:
- CRITICAL: Immediate safety/emergency response
- HIGH: Urgent operational fixes (battery, blockages)  
- MEDIUM: Preventive actions to avoid problems

Respond with JSON array of commands, or empty array [] if no action needed.
Maximum 2 commands for focused response.
"""

                # Run the agent with session to preserve context
                result = await Runner.run(self.agent, query, session=self.session)

                # Parse and execute commands
                commands = result.final_output.get("commands", [])

                if commands:
                    logger.info(
                        f"Executing {len(commands)} reactive commands for {event_type}"
                    )
                    await self._execute_reactive_commands(commands, event_type)
                else:
                    logger.info(f"No reactive commands needed for {event_type}")

            except asyncio.TimeoutError:
                # No critical events, continue monitoring
                continue
            except Exception as e:
                logger.error(f"Error processing critical event: {e}")
                await asyncio.sleep(1.0)

    async def _execute_reactive_commands(self, commands: List[Dict], event_type: str):
        """Execute reactive commands generated from critical events."""
        try:
            command_topic = self.topic_manager.get_agent_command_topic(self.line_id)

            for command in commands:
                # Add reactive metadata
                if "command_id" not in command:
                    command["command_id"] = (
                        f"reactive_{event_type}_{datetime.now().timestamp()}"
                    )

                command["reactive"] = True
                command["trigger_event"] = event_type

                # Add to history
                self.command_history.add_command(command)

                # Publish via MQTT
                self.mqtt_client.publish(command_topic, json.dumps(command))

                logger.info(f"Published reactive command: {command}")
                await asyncio.sleep(0.1)

        except Exception as e:
            logger.error(f"Error executing reactive commands: {e}")

    async def process_orders_cycle(self):
        """Main processing cycle - get orders and generate AGV commands."""
        try:
            if self.is_processing:
                logger.debug("Already processing, skipping cycle")
                return

            self.is_processing = True
            logger.info("Starting order processing cycle...")

            # Get available orders for this line (max 2)
            available_orders = self.shared_order_manager.get_orders_for_line(
                self.line_id
            )
            orders_to_process = available_orders[: self.max_orders_per_cycle]

            if not orders_to_process:
                logger.info("No orders available for processing")
                return

            logger.info(f"Processing {len(orders_to_process)} orders")

            # Prepare context for the agent
            context = self._prepare_agent_context(orders_to_process)

            # Generate agent query
            query = self._create_agent_query(context, orders_to_process)

            # Run the agent with session to preserve history
            result = await Runner.run(self.agent, query, session=self.session)

            # Parse and execute agent commands
            await self._execute_agent_commands(result.final_output, orders_to_process)

        except Exception as e:
            logger.error(f"Error in processing cycle: {e}")
        finally:
            self.is_processing = False

    def _prepare_agent_context(self, orders: List) -> Dict[str, Any]:
        """Prepare current factory context for the agent."""
        # Get products needing transport
        products_needing_transport = self.shared_order_manager.get_products_for_line(
            self.line_id
        )

        # Get recent command history
        recent_commands = self.command_history.get_recent_commands(3)
        recent_responses = self.command_history.get_recent_responses(3)

        context = {
            "line_id": self.line_id,
            "available_agvs": self.active_agvs,
            "products_needing_transport": [
                {
                    "product_id": p.product_id,
                    "product_type": p.product_type.value,
                    "status": p.status.value,
                    "current_location": p.current_location,
                    "next_step": p.get_next_processing_step(),
                }
                for p in products_needing_transport
            ],
            "recent_commands": recent_commands,
            "recent_responses": recent_responses,
            "current_time": datetime.now().isoformat(),
            # Include real-time factory state from MQTT
            "real_time_factory_state": self.current_factory_state,
        }

        return context

    def _create_agent_query(self, context: Dict[str, Any], orders: List) -> str:
        """Create the query for the agent based on current context."""
        orders_info = []
        for order in orders:
            order_info = {
                "order_id": order.order_id,
                "status": order.status.value,
                "products": [
                    {
                        "product_id": p.product_id,
                        "product_type": p.product_type.value,
                        "status": p.status.value,
                        "current_location": p.current_location,
                    }
                    for p in order.products
                ],
                "delivery_time": order.delivery_time.isoformat()
                if order.delivery_time
                else None,
            }
            orders_info.append(order_info)

        query = f"""
FACTORY STATE UPDATE:
{json.dumps(context, indent=2)}

ORDERS TO PROCESS:
{json.dumps(orders_info, indent=2)}

TASK:
Analyze the current factory state and generate optimal AGV commands to process these orders efficiently.

Consider:
1. Current AGV locations and battery levels
2. Product flow requirements (P1/P2 vs P3 different workflows)
3. Station availability and capacity
4. Order priorities and deadlines
5. Previous commands and their results

Generate commands to:
- Move products from RawMaterial to production line
- Transport products between stations as needed
- Deliver finished products to Warehouse
- Manage AGV charging efficiently

Respond with JSON array of commands only. Each command must specify action, target AGV, and required parameters.
"""

        return query

    async def _execute_agent_commands(self, agent_output: Any, processed_orders: List):
        """Parse and execute commands generated by the agent."""
        try:
            logger.info(f"Agent output: {agent_output}")

            # Handle different output types from the agent
            commands = []
            if isinstance(agent_output, dict):
                commands = agent_output.get("commands", [])
            elif isinstance(agent_output, str):
                # Try to parse JSON from string output
                try:
                    if agent_output.strip().startswith("```json"):
                        # Extract JSON from markdown code block
                        json_str = (
                            agent_output.split("```json")[1].split("```")[0].strip()
                        )
                        commands = json.loads(json_str)
                    else:
                        commands = json.loads(agent_output)
                except json.JSONDecodeError:
                    logger.error("Failed to parse agent output as JSON")
                    return
            else:
                logger.error(f"Unexpected agent output type: {type(agent_output)}")
                return

            if not commands:
                logger.warning("No valid commands generated by agent")
                return

            # Execute each command via MQTT
            command_topic = self.topic_manager.get_agent_command_topic(self.line_id)

            for command in commands:
                # Add timestamp and ensure command_id
                if "command_id" not in command:
                    command["command_id"] = f"cmd_{datetime.now().timestamp()}"

                # Add to history
                self.command_history.add_command(command)

                # Publish command via MQTT
                self.mqtt_client.publish(command_topic, json.dumps(command))

                logger.info(f"Published command: {command}")

                # Small delay between commands
                await asyncio.sleep(0.1)

            logger.info(f"Successfully executed {len(commands)} commands")

        except Exception as e:
            logger.error(f"Error executing agent commands: {e}")

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse agent commands as JSON: {e}")
            return []
        except Exception as e:
            logger.error(f"Error parsing agent commands: {e}")
            return []

    def _validate_command(self, command: Dict[str, Any]) -> bool:
        """Validate command structure."""
        required_fields = ["action", "target"]

        # Check required fields
        for field in required_fields:
            if field not in command:
                return False

        # Validate action
        valid_actions = ["move", "load", "unload", "charge"]
        if command["action"] not in valid_actions:
            return False

        # Validate target (should be one of our AGVs)
        if command["target"] not in self.active_agvs:
            return False

        return True

    async def start_continuous_processing(self):
        """Start continuous order processing with reactive event handling."""
        logger.info("Starting continuous order processing with reactive monitoring...")
        self.is_running = True

        # Start MQTT listening
        self.start_mqtt_listening()

        # Start critical event processor as background task
        critical_event_task = asyncio.create_task(self._process_critical_events())

        try:
            # Main processing loop
            while self.is_running:
                try:
                    await self.process_orders_cycle()
                    await asyncio.sleep(self.processing_interval)
                except KeyboardInterrupt:
                    logger.info("Stopping continuous processing...")
                    break
                except Exception as e:
                    logger.error(f"Error in continuous processing: {e}")
                    await asyncio.sleep(self.processing_interval)
        finally:
            # Clean shutdown
            self.is_running = False
            critical_event_task.cancel()
            try:
                await critical_event_task
            except asyncio.CancelledError:
                logger.info("Critical event processor stopped")
                pass

    def stop(self):
        """Stop the agent manager."""
        try:
            self.mqtt_client.disconnect()
            logger.info("Factory Agent Manager stopped")
        except Exception as e:
            logger.error(f"Error stopping agent manager: {e}")


async def main():
    """Main function to run the factory agent manager."""
    from dotenv import load_dotenv

    load_dotenv()

    # Check if API key is set
    if not os.getenv("OPENAI_API_KEY"):
        logger.error("OPENAI_API_KEY not set. Please set your OpenAI API key.")
        logger.error("export OPENAI_API_KEY='your-api-key-here'")
        return

    # Create and start agent manager
    agent_manager = FactoryAgentManager(line_id="line1", max_orders_per_cycle=2)

    try:
        await agent_manager.start_continuous_processing()
    except KeyboardInterrupt:
        logger.info("Received interrupt signal")
    finally:
        agent_manager.stop()


if __name__ == "__main__":
    asyncio.run(main())
