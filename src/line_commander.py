#!/usr/bin/env python3
"""
Line Commander
Central decision-making component that receives status updates from MQTT listener
and coordinates AGV operations for a production line.
"""

import asyncio
import json
import logging
from datetime import datetime
from typing import Any, Dict, List

from agents import Agent, SQLiteSession
from shared_order_manager import SharedOrderManager
from src.mqtt_listener_manager import MQTTListenerManager
from src.product_flow_agent import ProductFlowAgent

logger = logging.getLogger(__name__)


class LineCommander:
    """
    Central command and control for a production line.
    Receives status updates and makes strategic decisions about AGV operations.
    """

    def __init__(self, line_id: str, max_orders_per_cycle: int = 2):
        self.line_id = line_id
        self.max_orders_per_cycle = max_orders_per_cycle

        # MQTT communication manager
        self.mqtt_listener = MQTTListenerManager(line_id)

        # Order management
        self.shared_order_manager = SharedOrderManager()

        # Available AGVs for this line (must be defined before agent creation)
        self.active_agvs = ["AGV_1", "AGV_2"]

        # AI Agents for decision making
        self.agent = self._create_line_commander_agent()
        self.session = SQLiteSession(f"line_commander_{line_id}_session")

        # Specialized product flow agent
        self.product_flow_agent = ProductFlowAgent(line_id)

        # Decision making state
        self.decision_queue = asyncio.Queue(maxsize=100)
        self.command_history = []
        self.is_running = False

        # Processing intervals
        self.main_cycle_interval = 8.0  # Main decision cycle every 8 seconds
        self.reactive_processing_delay = (
            2.0  # React to critical events within 2 seconds
        )

        # Register handlers with MQTT listener
        self._register_mqtt_handlers()

    def _create_line_commander_agent(self) -> Agent:
        """Create the line commander AI agent."""
        instructions = f"""
You are the Line Commander for production line {self.line_id} in an automated factory.

MISSION:
- Coordinate AGV operations ({", ".join(self.active_agvs)}) to maximize production efficiency
- Monitor all line status (stations, AGVs, conveyors, warehouse) and react to changes
- Optimize for KPI metrics: order completion rate, production cycle efficiency, AGV utilization
- Handle both planned production and reactive responses to factory events

FACTORY LAYOUT & WORKFLOW:
P0: RawMaterial → P1: StationA → P2: Conveyor_AB → P3: StationB → P4: Conveyor_BC → P5: StationC → P6: Conveyor_CQ → P7-P8: QualityCheck → P9: Warehouse

SUCCESSFUL PRODUCT FLOW EXAMPLE (P1/P2 products):
1. AGV moves to P0 (RawMaterial)
2. AGV loads product with specific product_id from RawMaterial buffer
3. AGV moves to P1 (StationA) 
4. AGV unloads product to StationA buffer
5. StationA processes product automatically (5s) → moves to Conveyor_AB
6. Conveyor_AB transfers product automatically (5s) → moves to StationB
7. StationB processes product automatically (5s) → moves to Conveyor_BC
8. Conveyor_BC transfers product automatically (5s) → moves to StationC
9. StationC processes product automatically (5s) → moves to Conveyor_CQ
10. Conveyor_CQ transfers product automatically (5s) → moves to QualityCheck
11. QualityCheck processes product automatically (5s) → moves to output_buffer
12. AGV moves to P8 (QualityCheck pickup point)
13. AGV loads finished product from QualityCheck output_buffer
14. AGV moves to P9 (Warehouse)
15. AGV unloads finished product to Warehouse

PRODUCT TYPES & FLOWS:
- P1/P2: Single pass A→B→C→QualityCheck (as shown above)
- P3: Double pass A→B→C→(AGV pickup from Conveyor_CQ upper/lower buffer)→B→C→QualityCheck

KEY UNDERSTANDING:
- Stations process products automatically once they receive them
- Conveyors transfer products automatically between stations
- AGV is only needed for: RawMaterial→StationA and QualityCheck→Warehouse
- For P3 products: Additional AGV transport from Conveyor_CQ buffer back to StationB

STATUS MONITORING:
- Station status: idle/processing, buffer (input), output_buffer (for QualityCheck)
- AGV status: idle/moving/interacting, current_point, battery_level, payload
- Conveyor status: working, buffer, upper_buffer, lower_buffer (for Conveyor_CQ)
- Warehouse status: buffer (available products), stats (product counts by type)

DECISION PRIORITIES:
1. CRITICAL: AGV battery < 20%, equipment failures
2. HIGH: Products available in RawMaterial buffer, finished products in QualityCheck output_buffer
3. MEDIUM: AGV positioning, preventive charging (battery < 40%)
4. LOW: Optimization moves

AVAILABLE COMMANDS:
1. move: Move AGV to location (P0-P9)
2. load: Load product onto AGV (specify product_id at RawMaterial, auto-detect at QualityCheck)
3. unload: Unload product from AGV at current location
4. charge: Send AGV to charge (when battery < 30%, target_level default 80%)

RESPONSE FORMAT:
Always respond with JSON array of commands:
[
  {{
    "command_id": "cmd_timestamp_description",
    "action": "move|load|unload|charge",
    "target": "AGV_1|AGV_2",
    "params": {{"target_point": "P1", "product_id": "prod_...", "target_level": 80.0}},
    "priority": "critical|high|medium|low",
    "reasoning": "Brief explanation of why this command is needed"
  }}
]

STRATEGIC THINKING:
- Focus on the two critical AGV tasks: RawMaterial pickup and QualityCheck delivery
- Monitor RawMaterial buffer for available products to start production
- Monitor QualityCheck output_buffer for finished products to deliver
- Keep AGVs charged and positioned efficiently
- Balance workload between AGVs
- Prioritize order completion and throughput
"""

        return Agent(
            name=f"LineCommander_{self.line_id}",
            instructions=instructions,
            model="gpt-4.1-mini",
        )

    def _register_mqtt_handlers(self):
        """Register handlers for different types of MQTT messages."""

        # Station status changes
        self.mqtt_listener.register_handler(
            "station_status", self._handle_station_status
        )

        # AGV status changes
        self.mqtt_listener.register_handler("agv_status", self._handle_agv_status)

        # Conveyor status changes
        self.mqtt_listener.register_handler(
            "conveyor_status", self._handle_conveyor_status
        )

        # Warehouse status changes
        self.mqtt_listener.register_handler(
            "warehouse_status", self._handle_warehouse_status
        )

        # Factory alerts
        self.mqtt_listener.register_handler("alerts", self._handle_alerts)

        # New orders
        self.mqtt_listener.register_handler("orders", self._handle_orders)

        # Command responses
        self.mqtt_listener.register_handler("responses", self._handle_responses)

    def _handle_station_status(self, station_id: str, data: Dict[str, Any]):
        """Handle station status updates."""
        status = data.get("status", "unknown")
        buffer_count = len(data.get("buffer", []))
        output_buffer_count = len(data.get("output_buffer", []))

        # Queue decision events for critical station states
        if status == "blocked":
            self._queue_decision_event(
                "station_blocked",
                {"station_id": station_id, "severity": "critical", "data": data},
            )
        elif station_id == "QualityCheck" and output_buffer_count > 0:
            # Finished products ready for pickup - HIGH priority
            self._queue_decision_event(
                "finished_products_ready",
                {
                    "station_id": station_id,
                    "product_count": output_buffer_count,
                    "severity": "high",
                    "data": data,
                },
            )
        elif station_id == "StationA" and status == "idle" and buffer_count == 0:
            # StationA is ready to receive products - check if we have products to deliver
            self._queue_decision_event(
                "station_ready_for_input",
                {"station_id": station_id, "severity": "medium", "data": data},
            )

    def _handle_agv_status(self, agv_id: str, data: Dict[str, Any]):
        """Handle AGV status updates."""
        status = data.get("status", "unknown")
        battery = data.get("battery_level", 100)
        current_point = data.get("current_point", "unknown")
        payload = data.get("payload", [])

        # Queue decision events for critical AGV states
        if battery < 20 and status != "charging":
            self._queue_decision_event(
                "agv_critical_battery",
                {
                    "agv_id": agv_id,
                    "battery_level": battery,
                    "current_point": current_point,
                    "severity": "critical",
                    "data": data,
                },
            )
        elif status == "idle" and len(payload) > 0:
            # AGV has products but is idle - needs to deliver them
            self._queue_decision_event(
                "agv_loaded_idle",
                {
                    "agv_id": agv_id,
                    "payload_count": len(payload),
                    "current_point": current_point,
                    "severity": "high",
                    "data": data,
                },
            )
        elif battery < 40 and status == "idle" and len(payload) == 0:
            # AGV needs charging but not critical yet
            self._queue_decision_event(
                "agv_needs_charging",
                {
                    "agv_id": agv_id,
                    "battery_level": battery,
                    "current_point": current_point,
                    "severity": "medium",
                    "data": data,
                },
            )
        elif status == "idle" and battery > 40 and len(payload) == 0:
            # Idle AGV with good battery - available for new tasks
            self._queue_decision_event(
                "agv_available",
                {
                    "agv_id": agv_id,
                    "battery_level": battery,
                    "current_point": current_point,
                    "severity": "low",
                    "data": data,
                },
            )

    def _handle_conveyor_status(self, conveyor_id: str, data: Dict[str, Any]):
        """Handle conveyor status updates."""
        status = data.get("status", "unknown")
        buffer_count = len(data.get("buffer", []))
        upper_buffer_count = len(data.get("upper_buffer", []))
        lower_buffer_count = len(data.get("lower_buffer", []))

        if status == "blocked" or buffer_count > 5:
            self._queue_decision_event(
                "conveyor_congestion",
                {
                    "conveyor_id": conveyor_id,
                    "buffer_count": buffer_count,
                    "severity": "high",
                    "data": data,
                },
            )
        elif conveyor_id == "Conveyor_CQ" and (
            upper_buffer_count > 0 or lower_buffer_count > 0
        ):
            # P3 products waiting in Conveyor_CQ upper/lower buffers for second processing
            self._queue_decision_event(
                "p3_products_ready_for_second_processing",
                {
                    "conveyor_id": conveyor_id,
                    "upper_buffer_count": upper_buffer_count,
                    "lower_buffer_count": lower_buffer_count,
                    "total_p3_products": upper_buffer_count + lower_buffer_count,
                    "severity": "high",
                    "data": data,
                },
            )

    def _handle_warehouse_status(self, warehouse_id: str, data: Dict[str, Any]):
        """Handle warehouse status updates."""
        buffer_count = len(data.get("buffer", []))
        stats = data.get("stats", {})

        if warehouse_id == "RawMaterial" and buffer_count > 0:
            # Raw materials available for pickup - HIGH priority to start production
            self._queue_decision_event(
                "raw_materials_available",
                {
                    "warehouse_id": warehouse_id,
                    "product_count": buffer_count,
                    "stats": stats,
                    "severity": "high",
                    "data": data,
                },
            )
        elif buffer_count > 0:
            # Other warehouse products available
            self._queue_decision_event(
                "products_available",
                {
                    "warehouse_id": warehouse_id,
                    "product_count": buffer_count,
                    "severity": "medium",
                    "data": data,
                },
            )

    def _handle_alerts(self, alert_type: str, data: Dict[str, Any]):
        """Handle factory alerts."""
        alert_severity = data.get("severity", "medium")

        self._queue_decision_event(
            "factory_alert",
            {"alert_type": alert_type, "severity": alert_severity, "data": data},
        )

    def _handle_orders(self, order_type: str, data: Dict[str, Any]):
        """Handle new orders."""
        # Process order through shared order manager
        order = self.shared_order_manager.process_order(data, self.line_id)

        if order:
            self._queue_decision_event(
                "new_order",
                {
                    "order_id": order.order_id,
                    "product_count": len(order.products),
                    "severity": "high",
                    "data": data,
                },
            )

    def _handle_responses(self, response_type: str, data: Dict[str, Any]):
        """Handle command responses."""
        command_id = data.get("command_id", "unknown")
        response = data.get("response", "")

        logger.info(f"Command {command_id} response: {response}")

        # Add to command history
        self.command_history.append(
            {
                "command_id": command_id,
                "response": response,
                "timestamp": datetime.now().timestamp(),
            }
        )

    def _queue_decision_event(self, event_type: str, event_data: Dict[str, Any]):
        """Queue an event for decision processing."""
        event = {
            "type": event_type,
            "data": event_data,
            "timestamp": datetime.now().timestamp(),
            "severity": event_data.get("severity", "medium"),
        }

        try:
            self.decision_queue.put_nowait(event)
            logger.debug(
                f"Queued decision event: {event_type} (severity: {event_data.get('severity')})"
            )
        except asyncio.QueueFull:
            logger.warning(f"Decision queue full, dropping {event_type} event")

    async def start_command_operations(self):
        """Start the line commander operations."""
        logger.info(f"Starting Line Commander for {self.line_id}")

        # Start MQTT listener
        self.mqtt_listener.start_listening()

        self.is_running = True

        # Start concurrent tasks
        main_cycle_task = asyncio.create_task(self._main_decision_cycle())
        reactive_task = asyncio.create_task(self._reactive_decision_processor())

        try:
            # Run both tasks concurrently
            await asyncio.gather(main_cycle_task, reactive_task)
        except KeyboardInterrupt:
            logger.info("Stopping Line Commander...")
        finally:
            self.is_running = False
            main_cycle_task.cancel()
            reactive_task.cancel()
            self.mqtt_listener.stop()

    async def _main_decision_cycle(self):
        """Main decision-making cycle for planned operations."""
        logger.info("Starting main decision cycle...")

        while self.is_running:
            try:
                await self._process_planned_operations()
                await asyncio.sleep(self.main_cycle_interval)
            except Exception as e:
                logger.error(f"Error in main decision cycle: {e}")
                await asyncio.sleep(self.main_cycle_interval)

    async def _reactive_decision_processor(self):
        """Process reactive decisions from queued events."""
        logger.info("Starting reactive decision processor...")

        while self.is_running:
            try:
                # Wait for events with timeout
                event = await asyncio.wait_for(
                    self.decision_queue.get(), timeout=self.reactive_processing_delay
                )

                await self._process_reactive_event(event)

            except asyncio.TimeoutError:
                # No events to process, continue monitoring
                continue
            except Exception as e:
                logger.error(f"Error in reactive decision processor: {e}")
                await asyncio.sleep(1.0)

    async def _process_planned_operations(self):
        """Process planned operations - regular order fulfillment."""
        logger.info("Processing planned operations...")

        # Get current factory state
        factory_state = self.mqtt_listener.get_factory_state()

        # Get available orders
        available_orders = self.shared_order_manager.get_orders_for_line(self.line_id)
        orders_to_process = available_orders[: self.max_orders_per_cycle]

        if not orders_to_process:
            logger.debug("No orders available for planned processing")
            return

        # Create context for agent
        context = self._create_agent_context(
            factory_state, orders_to_process, "planned"
        )

        # Generate and execute commands
        commands = await self._generate_agent_commands(context)
        await self._execute_commands(commands, "planned")

    async def _process_reactive_event(self, event: Dict[str, Any]):
        """Process a single reactive event."""
        event_type = event["type"]
        severity = event["data"].get("severity", "medium")

        logger.info(f"Processing reactive event: {event_type} (severity: {severity})")

        # Get current factory state
        factory_state = self.mqtt_listener.get_factory_state()

        # Create context for reactive decision
        context = self._create_reactive_context(factory_state, event)

        # Generate and execute commands
        commands = await self._generate_agent_commands(context)
        await self._execute_commands(commands, "reactive", event_type)

    def _create_agent_context(
        self, factory_state: Dict[str, Any], orders: List, operation_type: str
    ) -> str:
        """Create context string for the agent."""

        # Get products needing transport
        products_needing_transport = self.shared_order_manager.get_products_for_line(
            self.line_id
        )

        # Recent command history
        recent_commands = self.command_history[-5:] if self.command_history else []

        context_data = {
            "operation_type": operation_type,
            "line_id": self.line_id,
            "current_time": datetime.now().isoformat(),
            "factory_state": factory_state,
            "orders_to_process": [
                {
                    "order_id": order.order_id,
                    "status": order.status.value,
                    "products": [
                        {
                            "product_id": p.product_id,
                            "product_type": p.product_type.value,
                            "status": p.status.value,
                            "current_location": p.current_location,
                            "next_step": p.get_next_processing_step(),
                        }
                        for p in order.products
                    ],
                }
                for order in orders
            ],
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
            "available_agvs": self.active_agvs,
        }

        return f"""
FACTORY OPERATION CONTEXT:
{json.dumps(context_data, indent=2)}

TASK: Analyze the current factory state and generate optimal AGV commands for {operation_type} operations.

Consider:
1. Current AGV positions, battery levels, and payloads
2. Station statuses and buffer levels
3. Product flow requirements and priorities
4. Order deadlines and priorities
5. Recent command history and results

Generate commands to optimize production flow and KPI metrics.
Respond with JSON array of commands only.
"""

    def _create_reactive_context(
        self, factory_state: Dict[str, Any], event: Dict[str, Any]
    ) -> str:
        """Create context for reactive decision making."""

        context_data = {
            "operation_type": "reactive",
            "line_id": self.line_id,
            "current_time": datetime.now().isoformat(),
            "factory_state": factory_state,
            "trigger_event": event,
            "recent_commands": self.command_history[-3:]
            if self.command_history
            else [],
            "available_agvs": self.active_agvs,
        }

        return f"""
REACTIVE FACTORY EVENT:
{json.dumps(context_data, indent=2)}

URGENT TASK: A {event["data"].get("severity", "medium")} severity event has occurred requiring immediate response.

Event Type: {event["type"]}
Event Details: {json.dumps(event["data"], indent=2)}

Analyze the situation and provide immediate corrective actions.
Focus on addressing the specific issue while maintaining overall production flow.

Respond with JSON array of commands only. Maximum 3 commands for focused response.
"""

    async def _generate_agent_commands(self, context: str) -> List[Dict[str, Any]]:
        """Generate commands using the specialized product flow agent."""
        try:
            # Get current factory state from MQTT listener
            factory_state = self.mqtt_listener.get_factory_state()

            # Determine context type from the context string
            context_type = (
                "reactive" if "REACTIVE FACTORY EVENT" in context else "planned"
            )

            # Use specialized product flow agent for better command generation
            commands = await self.product_flow_agent.generate_flow_commands(
                factory_state, context_type
            )

            logger.info(f"Generated {len(commands)} commands from product flow agent")
            return commands

        except Exception as e:
            logger.error(f"Error generating agent commands: {e}")
            return []

    async def _execute_commands(
        self,
        commands: List[Dict[str, Any]],
        operation_type: str,
        event_type: str = None,
    ):
        """Execute generated commands."""
        if not commands:
            logger.debug(f"No commands to execute for {operation_type} operation")
            return

        logger.info(f"Executing {len(commands)} {operation_type} commands")

        for command in commands:
            try:
                # Ensure command has required fields
                if "command_id" not in command:
                    timestamp = datetime.now().timestamp()
                    command["command_id"] = f"{operation_type}_{timestamp}"

                # Add metadata
                command["operation_type"] = operation_type
                if event_type:
                    command["trigger_event"] = event_type
                command["timestamp"] = datetime.now().timestamp()

                # Publish command
                self.mqtt_listener.publish_command(command)

                # Add to history
                self.command_history.append(
                    {
                        "command_id": command["command_id"],
                        "command": command,
                        "timestamp": datetime.now().timestamp(),
                        "operation_type": operation_type,
                    }
                )

                logger.info(
                    f"Executed {operation_type} command: {command['command_id']}"
                )

                # Small delay between commands
                await asyncio.sleep(0.1)

            except Exception as e:
                logger.error(f"Error executing command: {e}")

    def stop(self):
        """Stop the line commander."""
        self.is_running = False
        self.mqtt_listener.stop()
        logger.info(f"Line Commander {self.line_id} stopped")


async def main():
    """Main function to run the line commander."""
    import os

    from dotenv import load_dotenv

    load_dotenv()

    # Check if API key is set
    if not os.getenv("OPENAI_API_KEY"):
        logger.error("OPENAI_API_KEY not set. Please set your OpenAI API key.")
        return

    # Create and start line commander
    line_commander = LineCommander(line_id="line1", max_orders_per_cycle=2)

    try:
        await line_commander.start_command_operations()
    except KeyboardInterrupt:
        logger.info("Received interrupt signal")
    finally:
        line_commander.stop()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
