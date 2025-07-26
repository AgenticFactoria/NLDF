#!/usr/bin/env python3
"""
MQTT Listener Manager
Handles all MQTT subscriptions and routes messages to appropriate handlers.
Separates MQTT communication logic from agent decision making.
"""

import json
import logging
from datetime import datetime
from typing import Any, Callable, Dict, List

from config.settings import MQTT_BROKER_HOST, MQTT_BROKER_PORT
from utils.mqtt_client import MQTTClient
from utils.topic_manager import TopicManager

logger = logging.getLogger(__name__)


class MQTTListenerManager:
    """Manages all MQTT subscriptions and message routing for factory monitoring."""

    def __init__(self, line_id: str, topic_root: str = "AgenticFactoria"):
        self.line_id = line_id
        self.topic_root = topic_root

        # MQTT client setup
        self.mqtt_client = MQTTClient(
            host=MQTT_BROKER_HOST,
            port=MQTT_BROKER_PORT,
            client_id=f"mqtt_listener_{line_id}",
        )

        # Topic manager
        self.topic_manager = TopicManager(topic_root)

        # Message handlers - can be registered by other components
        self.message_handlers: Dict[str, List[Callable]] = {
            "station_status": [],
            "agv_status": [],
            "conveyor_status": [],
            "warehouse_status": [],
            "alerts": [],
            "orders": [],
            "responses": [],
            "kpi": [],
            "results": [],
        }

        # Current factory state - maintained by this manager
        self.factory_state = {
            "stations": {},
            "agvs": {},
            "conveyors": {},
            "warehouse": {},
            "alerts": [],
            "last_updated": None,
        }

        # Connection status
        self.is_connected = False

    def register_handler(
        self, message_type: str, handler: Callable[[str, Dict[str, Any]], None]
    ):
        """Register a handler for specific message types."""
        if message_type in self.message_handlers:
            self.message_handlers[message_type].append(handler)
            logger.info(f"Registered handler for {message_type}")
        else:
            logger.warning(f"Unknown message type: {message_type}")

    def start_listening(self):
        """Start MQTT communication and subscribe to all relevant topics."""
        try:
            logger.info("Starting MQTT listener manager...")
            self.mqtt_client.connect()
            self.is_connected = True

            # Subscribe to all factory device statuses
            self._subscribe_to_factory_topics()

            logger.info("MQTT listener manager started successfully")

        except Exception as e:
            logger.error(f"Failed to start MQTT listener: {e}")
            raise

    def _subscribe_to_factory_topics(self):
        """Subscribe to all factory-related MQTT topics."""

        # Station status for this line
        station_topic = f"{self.topic_root}/{self.line_id}/station/+/status"
        self.mqtt_client.subscribe(station_topic, self._on_station_status)
        logger.info(f"Subscribed to station status: {station_topic}")

        # AGV status for this line
        agv_topic = f"{self.topic_root}/{self.line_id}/agv/+/status"
        self.mqtt_client.subscribe(agv_topic, self._on_agv_status)
        logger.info(f"Subscribed to AGV status: {agv_topic}")

        # Conveyor status for this line
        conveyor_topic = f"{self.topic_root}/{self.line_id}/conveyor/+/status"
        self.mqtt_client.subscribe(conveyor_topic, self._on_conveyor_status)
        logger.info(f"Subscribed to conveyor status: {conveyor_topic}")

        # Warehouse status (global)
        warehouse_topic = f"{self.topic_root}/warehouse/+/status"
        self.mqtt_client.subscribe(warehouse_topic, self._on_warehouse_status)
        logger.info(f"Subscribed to warehouse status: {warehouse_topic}")

        # Alerts for this line
        alerts_topic = f"{self.topic_root}/{self.line_id}/alerts"
        self.mqtt_client.subscribe(alerts_topic, self._on_alerts)
        logger.info(f"Subscribed to alerts: {alerts_topic}")

        # Orders (global)
        orders_topic = self.topic_manager.get_order_topic()
        self.mqtt_client.subscribe(orders_topic, self._on_orders)
        logger.info(f"Subscribed to orders: {orders_topic}")

        # Command responses for this line
        response_topic = f"{self.topic_root}/response/{self.line_id}"
        self.mqtt_client.subscribe(response_topic, self._on_responses)
        logger.info(f"Subscribed to responses: {response_topic}")

        # KPI updates (global)
        kpi_topic = self.topic_manager.get_kpi_topic()
        self.mqtt_client.subscribe(kpi_topic, self._on_kpi)
        logger.info(f"Subscribed to KPI: {kpi_topic}")

        # Results (global)
        results_topic = self.topic_manager.get_result_topic()
        self.mqtt_client.subscribe(results_topic, self._on_results)
        logger.info(f"Subscribed to results: {results_topic}")

    def _on_station_status(self, topic: str, payload: bytes):
        """Handle station status messages."""
        try:
            data = json.loads(payload.decode("utf-8"))
            station_id = topic.split("/")[-2]  # Extract station ID from topic

            # Parse station-specific data
            parsed_data = {
                "timestamp": data.get("timestamp", 0.0),
                "source_id": data.get("source_id", station_id),
                "status": data.get("status", "unknown"),
                "message": data.get("message", ""),
                "buffer": data.get("buffer", []),
                "output_buffer": data.get("output_buffer", []),
                "stats": data.get("stats", {}),
                "last_updated": datetime.now().timestamp(),
            }

            # Update factory state
            self.factory_state["stations"][station_id] = parsed_data

            # Safe length checking for potentially None buffers
            buffer_len = len(parsed_data["buffer"]) if parsed_data.get("buffer") else 0
            output_len = (
                len(parsed_data["output_buffer"])
                if parsed_data.get("output_buffer")
                else 0
            )

            logger.debug(
                f"Station {station_id} status: {parsed_data['status']}, buffer: {buffer_len}, output: {output_len}"
            )

            # Notify all registered handlers
            for handler in self.message_handlers["station_status"]:
                try:
                    handler(station_id, parsed_data)
                except Exception as e:
                    logger.error(f"Error in station status handler: {e}")

        except Exception as e:
            logger.error(f"Error processing station status: {e}")

    def _on_agv_status(self, topic: str, payload: bytes):
        """Handle AGV status messages."""
        try:
            data = json.loads(payload.decode("utf-8"))
            agv_id = topic.split("/")[-2]  # Extract AGV ID from topic

            # Parse AGV-specific data
            parsed_data = {
                "timestamp": data.get("timestamp", 0.0),
                "source_id": data.get("source_id", agv_id),
                "status": data.get("status", "unknown"),
                "speed_mps": data.get("speed_mps", 0.0),
                "current_point": data.get("current_point", "unknown"),
                "position": data.get("position", {}),
                "target_point": data.get("target_point"),
                "estimated_time": data.get("estimated_time", 0.0),
                "payload": data.get("payload", []),
                "battery_level": data.get("battery_level", 100.0),
                "message": data.get("message", ""),
                "last_updated": datetime.now().timestamp(),
            }

            # Update factory state
            self.factory_state["agvs"][agv_id] = parsed_data

            # Safe length checking for potentially None payload
            payload_len = (
                len(parsed_data["payload"]) if parsed_data.get("payload") else 0
            )

            logger.debug(
                f"AGV {agv_id} status: {parsed_data['status']} at {parsed_data['current_point']}, battery: {parsed_data['battery_level']}%, payload: {payload_len}"
            )

            # Notify all registered handlers
            for handler in self.message_handlers["agv_status"]:
                try:
                    handler(agv_id, parsed_data)
                except Exception as e:
                    logger.error(f"Error in AGV status handler: {e}")

        except Exception as e:
            logger.error(f"Error processing AGV status: {e}")

    def _on_conveyor_status(self, topic: str, payload: bytes):
        """Handle conveyor status messages."""
        try:
            data = json.loads(payload.decode("utf-8"))
            conveyor_id = topic.split("/")[-2]  # Extract conveyor ID from topic

            # Parse conveyor-specific data
            parsed_data = {
                "timestamp": data.get("timestamp", 0.0),
                "source_id": data.get("source_id", conveyor_id),
                "status": data.get("status", "unknown"),
                "message": data.get("message", ""),
                "buffer": data.get("buffer", []),
                "upper_buffer": data.get("upper_buffer", []),
                "lower_buffer": data.get("lower_buffer", []),
                "last_updated": datetime.now().timestamp(),
            }

            # Update factory state
            self.factory_state["conveyors"][conveyor_id] = parsed_data

            # Safe length checking for potentially None buffers
            buffer_len = len(parsed_data["buffer"]) if parsed_data.get("buffer") else 0
            upper_len = (
                len(parsed_data["upper_buffer"])
                if parsed_data.get("upper_buffer")
                else 0
            )
            lower_len = (
                len(parsed_data["lower_buffer"])
                if parsed_data.get("lower_buffer")
                else 0
            )

            logger.debug(
                f"Conveyor {conveyor_id} status: {parsed_data['status']}, buffer: {buffer_len}, upper: {upper_len}, lower: {lower_len}"
            )

            # Notify all registered handlers
            for handler in self.message_handlers["conveyor_status"]:
                try:
                    handler(conveyor_id, parsed_data)
                except Exception as e:
                    logger.error(f"Error in conveyor status handler: {e}")

        except Exception as e:
            logger.error(f"Error processing conveyor status: {e}")

    def _on_warehouse_status(self, topic: str, payload: bytes):
        """Handle warehouse status messages."""
        try:
            data = json.loads(payload.decode("utf-8"))
            warehouse_id = topic.split("/")[-2]  # Extract warehouse ID from topic

            # Parse warehouse-specific data
            parsed_data = {
                "timestamp": data.get("timestamp", 0.0),
                "source_id": data.get("source_id", warehouse_id),
                "message": data.get("message", ""),
                "buffer": data.get("buffer", []),
                "stats": data.get("stats", {}),
                "last_updated": datetime.now().timestamp(),
            }

            # Update factory state
            self.factory_state["warehouse"] = parsed_data

            # Safe length checking for potentially None buffer
            buffer_len = len(parsed_data["buffer"]) if parsed_data.get("buffer") else 0

            logger.debug(
                f"Warehouse {warehouse_id} status: {buffer_len} products, stats: {parsed_data['stats']}"
            )

            # Notify all registered handlers
            for handler in self.message_handlers["warehouse_status"]:
                try:
                    handler(warehouse_id, parsed_data)
                except Exception as e:
                    logger.error(f"Error in warehouse status handler: {e}")

        except Exception as e:
            logger.error(f"Error processing warehouse status: {e}")

    def _on_alerts(self, topic: str, payload: bytes):
        """Handle factory alerts."""
        try:
            data = json.loads(payload.decode("utf-8"))

            # Add to alerts list (keep last 50)
            alert_entry = {**data, "timestamp": datetime.now().timestamp()}
            self.factory_state["alerts"].append(alert_entry)
            if len(self.factory_state["alerts"]) > 50:
                self.factory_state["alerts"] = self.factory_state["alerts"][-50:]

            logger.warning(f"Factory alert: {data}")

            # Notify all registered handlers
            for handler in self.message_handlers["alerts"]:
                try:
                    handler("alert", data)
                except Exception as e:
                    logger.error(f"Error in alert handler: {e}")

        except Exception as e:
            logger.error(f"Error processing alert: {e}")

    def _on_orders(self, topic: str, payload: bytes):
        """Handle new orders."""
        try:
            data = json.loads(payload.decode("utf-8"))

            logger.info(f"New order received: {data}")

            # Notify all registered handlers
            for handler in self.message_handlers["orders"]:
                try:
                    handler("order", data)
                except Exception as e:
                    logger.error(f"Error in order handler: {e}")

        except Exception as e:
            logger.error(f"Error processing order: {e}")

    def _on_responses(self, topic: str, payload: bytes):
        """Handle command responses."""
        try:
            data = json.loads(payload.decode("utf-8"))

            logger.info(f"Command response: {data}")

            # Notify all registered handlers
            for handler in self.message_handlers["responses"]:
                try:
                    handler("response", data)
                except Exception as e:
                    logger.error(f"Error in response handler: {e}")

        except Exception as e:
            logger.error(f"Error processing response: {e}")

    def _on_kpi(self, topic: str, payload: bytes):
        """Handle KPI updates."""
        try:
            data = json.loads(payload.decode("utf-8"))

            logger.info(f"KPI update: {data}")

            # Notify all registered handlers
            for handler in self.message_handlers["kpi"]:
                try:
                    handler("kpi", data)
                except Exception as e:
                    logger.error(f"Error in KPI handler: {e}")

        except Exception as e:
            logger.error(f"Error processing KPI: {e}")

    def _on_results(self, topic: str, payload: bytes):
        """Handle results updates."""
        try:
            data = json.loads(payload.decode("utf-8"))

            logger.info(f"Results update: {data}")

            # Notify all registered handlers
            for handler in self.message_handlers["results"]:
                try:
                    handler("results", data)
                except Exception as e:
                    logger.error(f"Error in results handler: {e}")

        except Exception as e:
            logger.error(f"Error processing results: {e}")

    def get_factory_state(self) -> Dict[str, Any]:
        """Get current factory state."""
        self.factory_state["last_updated"] = datetime.now().timestamp()
        return self.factory_state.copy()

    def get_station_status(self, station_id: str) -> Dict[str, Any]:
        """Get status of specific station."""
        return self.factory_state["stations"].get(station_id, {})

    def get_agv_status(self, agv_id: str) -> Dict[str, Any]:
        """Get status of specific AGV."""
        return self.factory_state["agvs"].get(agv_id, {})

    def get_recent_alerts(self, count: int = 10) -> List[Dict[str, Any]]:
        """Get recent alerts."""
        return (
            self.factory_state["alerts"][-count:]
            if self.factory_state["alerts"]
            else []
        )

    def publish_command(self, command: Dict[str, Any]):
        """Publish a command to the factory."""
        try:
            command_topic = self.topic_manager.get_agent_command_topic(self.line_id)
            self.mqtt_client.publish(command_topic, json.dumps(command))
            logger.info(f"Published command: {command}")
        except Exception as e:
            logger.error(f"Error publishing command: {e}")

    def stop(self):
        """Stop MQTT listener."""
        try:
            if self.is_connected:
                self.mqtt_client.disconnect()
                self.is_connected = False
                logger.info("MQTT listener manager stopped")
        except Exception as e:
            logger.error(f"Error stopping MQTT listener: {e}")
