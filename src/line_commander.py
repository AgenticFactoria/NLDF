#!/usr/bin/env python3
"""
Line Commander
Central decision-making component that receives status updates from MQTT listener
and coordinates AGV operations for a production line.
"""

import asyncio
import logging
from datetime import datetime
from typing import Any, Dict, List

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

        # Available AGVs for this line
        self.active_agvs = ["AGV_1", "AGV_2"]

        # Specialized product flow agent
        self.product_flow_agent = ProductFlowAgent(line_id, self.shared_order_manager)

        # Decision making state
        self.decision_queue = asyncio.Queue(maxsize=1000)
        self.command_history = []
        self.is_running = False

        # Processing intervals
        self.main_cycle_interval = 8.0  # Main decision cycle every 8 seconds
        self.reactive_processing_delay = (
            2.0  # React to critical events within 2 seconds
        )

        # Register handlers with MQTT listener
        self._register_mqtt_handlers()

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
                    "payload": payload,
                    "current_point": current_point,
                    "severity": "high",
                    "data": data,
                },
            )
        elif current_point == "P8" and status == "idle" and len(payload) == 0:
            # AGV reached QualityCheck and is ready to load finished products
            self._queue_decision_event(
                "agv_at_quality_check_ready",
                {
                    "agv_id": agv_id,
                    "current_point": current_point,
                    "battery_level": battery,
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
        # Safe length checking for potentially None buffers
        buffer_count = len(data.get("buffer") or [])
        upper_buffer_count = len(data.get("upper_buffer") or [])
        lower_buffer_count = len(data.get("lower_buffer") or [])

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
        logger.info(f"Starting main decision cycle for {self.line_id}...")

        while self.is_running:
            try:
                await self._process_planned_operations()
                await asyncio.sleep(self.main_cycle_interval)
            except Exception as e:
                logger.error(f"Error in main decision cycle: {e}")
                await asyncio.sleep(self.main_cycle_interval)

    async def _reactive_decision_processor(self):
        """Process reactive decisions from queued events."""
        logger.info(f"Starting reactive decision processor for {self.line_id}...")

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
        logger.debug(f"Processing planned operations for {self.line_id}...")

        # Generate and execute commands for available AGVs
        commands = await self._generate_agent_commands()
        await self._execute_commands(commands)

    async def _process_reactive_event(self, event: Dict[str, Any]):
        """Process a single reactive event."""
        event_type = event["type"]
        severity = event["data"].get("severity", "medium")

        logger.info(f"Processing reactive event: {event_type} (severity: {severity})")

        # Generate and execute commands for available AGVs with reactive event context
        commands = await self._generate_agent_commands(event)
        await self._execute_commands(commands)

    async def _generate_agent_commands(
        self, reactive_event: Dict[str, Any] = None
    ) -> List[Dict[str, Any]]:
        """Generate commands for available AGVs using the specialized product flow agent."""
        try:
            # Get current factory state from MQTT listener
            factory_state = self.mqtt_listener.get_factory_state()

            # Use specialized product flow agent for command generation
            commands = (
                await self.product_flow_agent.generate_commands_for_available_agvs(
                    factory_state, reactive_event
                )
            )

            if commands:
                logger.info(
                    f"Generated {len(commands)} commands for available AGVs for for {self.line_id}"
                )
            else:
                logger.debug("No commands generated - no action needed")

            return commands

        except Exception as e:
            logger.error(f"Error generating agent commands: {e}")
            return []

    async def _execute_commands(self, commands: List[Dict[str, Any]]):
        """Execute commands for different AGVs."""
        if not commands:
            logger.debug("No commands to execute")
            return

        logger.info(
            f"Executing {len(commands)} commands for different AGVs for {self.line_id}"
        )

        for command in commands:
            try:
                # Ensure command has required fields
                if "command_id" not in command:
                    timestamp = datetime.now().timestamp()
                    command["command_id"] = f"cmd_{timestamp}"

                # Add timestamp
                command["timestamp"] = datetime.now().timestamp()

                # Publish command
                self.mqtt_listener.publish_command(command)

                # Add to history
                self.command_history.append(
                    {
                        "command_id": command["command_id"],
                        "command": command,
                        "timestamp": datetime.now().timestamp(),
                    }
                )

                logger.info(
                    f"Executed command: {command['command_id']} - {command['action']} for {command['target']}"
                )

                # Small delay between commands to different AGVs
                await asyncio.sleep(0.1)

            except Exception as e:
                logger.error(f"Error executing command: {e}")

    def stop(self):
        """Stop the line commander."""
        self.is_running = False
        self.mqtt_listener.stop()
        logger.info(f"Line Commander {self.line_id} stopped")
