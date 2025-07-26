#!/usr/bin/env python3
"""
Test script for the new Line Commander architecture.
Tests the modular components without requiring full factory simulation.
"""

import asyncio
import json
import logging
import os
import sys
from unittest.mock import MagicMock, patch

# Add current directory to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from src.line_commander import LineCommander
from src.mqtt_listener_manager import MQTTListenerManager

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class MockMQTTClient:
    """Mock MQTT client for testing."""

    def __init__(self, *args, **kwargs):
        self.connected = False
        self.subscriptions = {}
        self.published_messages = []

    def connect(self):
        self.connected = True
        logger.info("Mock MQTT client connected")

    def disconnect(self):
        self.connected = False
        logger.info("Mock MQTT client disconnected")

    def subscribe(self, topic, callback, qos=0):
        self.subscriptions[topic] = callback
        logger.info(f"Mock subscribed to: {topic}")

    def publish(self, topic, payload, qos=1, retain=False):
        message = {"topic": topic, "payload": payload, "qos": qos, "retain": retain}
        self.published_messages.append(message)
        logger.info(f"Mock published to {topic}: {payload}")

    def is_connected(self):
        return self.connected


async def test_mqtt_listener_manager():
    """Test the MQTT Listener Manager."""
    logger.info("Testing MQTT Listener Manager...")

    with patch("src.mqtt_listener_manager.MQTTClient", MockMQTTClient):
        listener = MQTTListenerManager("line1", "TestFactory")

        # Test handler registration
        test_handler_called = False

        def test_handler(device_id, data):
            nonlocal test_handler_called
            test_handler_called = True
            logger.info(f"Test handler called for {device_id}: {data}")

        listener.register_handler("station_status", test_handler)

        # Start listening
        listener.start_listening()

        # Simulate station status message
        test_payload = json.dumps(
            {
                "status": "idle",
                "buffer": ["product1", "product2"],
                "timestamp": 1234567890,
            }
        ).encode("utf-8")

        # Trigger the handler directly
        listener._on_station_status(
            "TestFactory/line1/station/StationA/status", test_payload
        )

        # Check if handler was called
        assert test_handler_called, "Station status handler was not called"

        # Check factory state
        factory_state = listener.get_factory_state()
        assert "stations" in factory_state
        assert "StationA" in factory_state["stations"]

        listener.stop()
        logger.info("✅ MQTT Listener Manager test passed")


async def test_line_commander_basic():
    """Test basic Line Commander functionality."""
    logger.info("Testing Line Commander basic functionality...")

    # Mock the OpenAI API key
    os.environ["OPENAI_API_KEY"] = "test-key"

    with patch("src.mqtt_listener_manager.MQTTClient", MockMQTTClient):
        with patch("agents.Agent") as mock_agent:
            with patch("agents.Runner") as mock_runner:
                # Mock agent response
                mock_result = MagicMock()
                mock_result.final_output = [
                    {
                        "command_id": "test_cmd_1",
                        "action": "move",
                        "target": "AGV_1",
                        "params": {"target_point": "P1"},
                        "priority": "medium",
                        "reasoning": "Test command",
                    }
                ]
                mock_runner.run.return_value = mock_result

                # Create line commander
                commander = LineCommander("line1", max_orders_per_cycle=1)

                # Test context creation
                factory_state = {
                    "stations": {"StationA": {"status": "idle", "buffer": []}},
                    "agvs": {
                        "AGV_1": {
                            "status": "idle",
                            "battery_level": 80,
                            "current_point": "P0",
                        }
                    },
                    "conveyors": {},
                    "warehouse": {"buffer": ["product1"]},
                    "alerts": [],
                }

                context = commander._create_agent_context(factory_state, [], "planned")
                assert "FACTORY OPERATION CONTEXT" in context

                # Test command generation
                commands = await commander._generate_agent_commands(context)
                assert len(commands) == 1
                assert commands[0]["action"] == "move"

                logger.info("✅ Line Commander basic test passed")


async def test_event_processing():
    """Test event processing and prioritization."""
    logger.info("Testing event processing...")

    os.environ["OPENAI_API_KEY"] = "test-key"

    with patch("src.mqtt_listener_manager.MQTTClient", MockMQTTClient):
        with patch("agents.Agent"):
            with patch("agents.Runner"):
                commander = LineCommander("line1")

                # Test event queuing
                commander._queue_decision_event(
                    "test_event", {"severity": "high", "device_id": "AGV_1"}
                )

                # Check if event was queued
                assert not commander.decision_queue.empty()

                # Get the event
                event = await commander.decision_queue.get()
                assert event["type"] == "test_event"
                assert event["data"]["severity"] == "high"

                logger.info("✅ Event processing test passed")


async def test_integration():
    """Test integration between components."""
    logger.info("Testing component integration...")

    os.environ["OPENAI_API_KEY"] = "test-key"

    with patch("src.mqtt_listener_manager.MQTTClient", MockMQTTClient):
        with patch("agents.Agent"):
            with patch("agents.Runner") as mock_runner:
                # Mock successful command generation
                mock_result = MagicMock()
                mock_result.final_output = []
                mock_runner.run.return_value = mock_result

                commander = LineCommander("line1")

                # Test MQTT handler integration
                commander._handle_agv_status(
                    "AGV_1",
                    {
                        "status": "idle",
                        "battery_level": 15,  # Low battery
                        "current_point": "P1",
                        "payload": [],
                    },
                )

                # Should have queued a critical battery event
                assert not commander.decision_queue.empty()

                event = await commander.decision_queue.get()
                assert event["type"] == "agv_critical_battery"
                assert event["data"]["severity"] == "critical"

                logger.info("✅ Integration test passed")


async def run_all_tests():
    """Run all tests."""
    logger.info("Starting Line Commander architecture tests...")

    try:
        await test_mqtt_listener_manager()
        await test_line_commander_basic()
        await test_event_processing()
        await test_integration()

        logger.info("🎉 All tests passed! New architecture is working correctly.")

    except Exception as e:
        logger.error(f"❌ Test failed: {e}")
        raise


if __name__ == "__main__":
    asyncio.run(run_all_tests())
