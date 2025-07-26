#!/usr/bin/env python3
"""
Test script to verify AGV_2 requirement for P3 second processing.
"""

import asyncio
import logging
import os
import sys
from unittest.mock import patch

# Add current directory to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from src.product_flow_agent import ProductFlowAgent

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def test_agv2_p3_requirement():
    """Test that P3 second processing requires AGV_2."""
    logger.info("Testing AGV_2 requirement for P3 second processing...")

    os.environ["OPENAI_API_KEY"] = "test-key"

    with patch("agents.Agent"):
        agent = ProductFlowAgent("line1")

        # Test scenario: P3 product in upper_buffer, both AGVs available
        factory_state = {
            "warehouse": {"buffer": []},
            "stations": {"QualityCheck": {"output_buffer": []}},
            "agvs": {
                "AGV_1": {"status": "idle", "battery_level": 80, "payload": []},
                "AGV_2": {"status": "idle", "battery_level": 75, "payload": []},
            },
            "conveyors": {
                "Conveyor_CQ": {
                    "upper_buffer": ["prod_3_test123"],  # P3 product waiting
                    "lower_buffer": [],
                }
            },
        }

        # Analyze the situation
        analysis = agent._analyze_factory_situation(
            factory_state["warehouse"],
            factory_state["stations"],
            factory_state["agvs"],
            factory_state["conveyors"],
        )

        # Verify P3 detection
        p3_actions = [a for a in analysis["actions_needed"] if "p3" in a["action"]]
        assert len(p3_actions) > 0, "No P3 actions detected"

        p3_action = p3_actions[0]
        assert p3_action["action"] == "continue_p3_processing", (
            f"Expected continue_p3_processing, got {p3_action['action']}"
        )
        assert p3_action.get("required_agv") == "AGV_2", (
            f"Expected AGV_2 requirement, got {p3_action.get('required_agv')}"
        )

        logger.info("✅ P3 action correctly requires AGV_2")

        # Test AGV_2 selection method
        selected_agv = agent._select_agv_for_p3_second_processing(factory_state["agvs"])
        assert selected_agv == "AGV_2", f"Expected AGV_2, got {selected_agv}"

        logger.info("✅ AGV selection correctly returns AGV_2")

        # Test P3 command generation with correct AGV
        commands = agent._generate_p3_command_sequence(
            "AGV_2", "prod_3_test123", "continue_p3_processing"
        )
        assert len(commands) == 4, f"Expected 4 commands, got {len(commands)}"

        # Verify all commands use AGV_2
        for cmd in commands:
            assert cmd["target"] == "AGV_2", (
                f"Command should use AGV_2, got {cmd['target']}"
            )

        logger.info("✅ P3 command sequence correctly uses AGV_2")

        # Test P3 command generation with wrong AGV (should fail)
        wrong_commands = agent._generate_p3_command_sequence(
            "AGV_1", "prod_3_test123", "continue_p3_processing"
        )
        assert len(wrong_commands) == 0, (
            f"Expected empty commands for AGV_1, got {len(wrong_commands)}"
        )

        logger.info("✅ P3 command generation correctly rejects AGV_1")


async def test_agv2_unavailable_scenario():
    """Test scenario when AGV_2 is not available for P3."""
    logger.info("Testing P3 handling when AGV_2 is unavailable...")

    os.environ["OPENAI_API_KEY"] = "test-key"

    with patch("agents.Agent"):
        agent = ProductFlowAgent("line1")

        # Test scenario: P3 product waiting, but AGV_2 is busy
        factory_state = {
            "warehouse": {"buffer": []},
            "stations": {"QualityCheck": {"output_buffer": []}},
            "agvs": {
                "AGV_1": {"status": "idle", "battery_level": 80, "payload": []},
                "AGV_2": {
                    "status": "moving",
                    "battery_level": 75,
                    "payload": [],
                },  # AGV_2 busy
            },
            "conveyors": {
                "Conveyor_CQ": {
                    "upper_buffer": ["prod_3_waiting"],  # P3 product waiting
                    "lower_buffer": [],
                }
            },
        }

        # Test AGV_2 selection when unavailable
        selected_agv = agent._select_agv_for_p3_second_processing(factory_state["agvs"])
        assert selected_agv is None, (
            f"Expected None when AGV_2 unavailable, got {selected_agv}"
        )

        logger.info("✅ Correctly detects AGV_2 unavailable")

        # Analyze situation
        analysis = agent._analyze_factory_situation(
            factory_state["warehouse"],
            factory_state["stations"],
            factory_state["agvs"],
            factory_state["conveyors"],
        )

        # Should have a wait action instead of continue action
        wait_actions = [a for a in analysis["actions_needed"] if "wait" in a["action"]]
        assert len(wait_actions) > 0, "Expected wait action when AGV_2 unavailable"

        logger.info("✅ Correctly generates wait action when AGV_2 unavailable")


async def run_agv2_tests():
    """Run all AGV_2 requirement tests."""
    logger.info("Starting AGV_2 P3 requirement tests...")

    try:
        await test_agv2_p3_requirement()
        await test_agv2_unavailable_scenario()

        logger.info("🎉 All AGV_2 P3 requirement tests passed!")

    except Exception as e:
        logger.error(f"❌ AGV_2 test failed: {e}")
        raise


if __name__ == "__main__":
    asyncio.run(run_agv2_tests())
