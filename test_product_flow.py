#!/usr/bin/env python3
"""
Test script for the Product Flow Agent.
Tests the specialized agent with realistic factory status data.
"""

import asyncio
import json
import logging
import os
import sys
from unittest.mock import MagicMock, patch

# Add current directory to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from src.product_flow_agent import ProductFlowAgent

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def create_test_factory_state():
    """Create a realistic factory state for testing."""
    return {
        "stations": {
            "StationA": {
                "timestamp": 0.0,
                "source_id": "StationA",
                "status": "idle",
                "message": "Station initialized",
                "buffer": [],
                "output_buffer": [],
                "stats": {"products_processed": 0},
                "last_updated": 1234567890,
            },
            "QualityCheck": {
                "timestamp": 101.60,
                "source_id": "QualityCheck",
                "status": "idle",
                "message": "Quality check complete",
                "buffer": [],
                "output_buffer": ["prod_1_75a16c3d"],  # Finished product ready
                "stats": {"products_processed": 1},
                "last_updated": 1234567890,
            },
        },
        "agvs": {
            "AGV_1": {
                "timestamp": 0.0,
                "source_id": "AGV_1",
                "status": "idle",
                "speed_mps": 2.0,
                "current_point": "P10",
                "position": {"x": 10.0, "y": 50.0},
                "target_point": None,
                "estimated_time": 0.0,
                "payload": [],
                "battery_level": 50.0,
                "message": "initialized",
                "last_updated": 1234567890,
            },
            "AGV_2": {
                "timestamp": 0.0,
                "source_id": "AGV_2",
                "status": "idle",
                "speed_mps": 2.0,
                "current_point": "P10",
                "position": {"x": 10.0, "y": 50.0},
                "target_point": None,
                "estimated_time": 0.0,
                "payload": [],
                "battery_level": 80.0,
                "message": "initialized",
                "last_updated": 1234567890,
            },
        },
        "conveyors": {
            "Conveyor_AB": {
                "timestamp": 0.0,
                "source_id": "Conveyor_AB",
                "status": "working",
                "message": "Conveyor initialized",
                "buffer": [],
                "upper_buffer": [],
                "lower_buffer": [],
                "last_updated": 1234567890,
            },
            "Conveyor_CQ": {
                "timestamp": 0.0,
                "source_id": "Conveyor_CQ",
                "status": "working",
                "message": "Conveyor initialized",
                "buffer": [],
                "upper_buffer": [
                    "prod_3_abc123"
                ],  # P3 product waiting for second processing
                "lower_buffer": [],
                "last_updated": 1234567890,
            },
        },
        "warehouse": {
            "timestamp": 0.0,
            "source_id": "RawMaterial",
            "message": "Raw material warehouse is ready",
            "buffer": ["prod_1_new123", "prod_2_new456"],  # Raw materials available
            "stats": {
                "total_materials_supplied": 2,
                "product_type_summary": {"P1": 1, "P2": 1, "P3": 0},
            },
            "last_updated": 1234567890,
        },
        "alerts": [],
        "last_updated": 1234567890,
    }


async def test_product_flow_agent():
    """Test the Product Flow Agent with realistic data."""
    logger.info("Testing Product Flow Agent...")

    # Mock the OpenAI API key
    os.environ["OPENAI_API_KEY"] = "test-key"

    with patch("agents.Agent") as mock_agent:
        with patch("agents.Runner") as mock_runner:
            # Mock agent response with realistic commands
            mock_result = MagicMock()
            mock_result.final_output = [
                {
                    "command_id": "flow_1234567890_quality_pickup",
                    "action": "move",
                    "target": "AGV_1",
                    "params": {"target_point": "P8"},
                    "priority": "high",
                    "reasoning": "Finished product prod_1_75a16c3d ready for pickup from QualityCheck",
                    "flow_stage": "quality_pickup",
                },
                {
                    "command_id": "flow_1234567890_raw_pickup",
                    "action": "move",
                    "target": "AGV_2",
                    "params": {"target_point": "P0"},
                    "priority": "high",
                    "reasoning": "Raw materials available, start new production",
                    "flow_stage": "raw_pickup",
                },
            ]
            mock_runner.run.return_value = mock_result

            # Create product flow agent
            agent = ProductFlowAgent("line1")

            # Test with realistic factory state
            factory_state = create_test_factory_state()

            # Generate commands
            commands = await agent.generate_flow_commands(factory_state, "planned")

            # Verify commands
            assert len(commands) == 2, f"Expected 2 commands, got {len(commands)}"

            # Check first command (quality pickup)
            cmd1 = commands[0]
            assert cmd1["action"] == "move"
            assert cmd1["target"] == "AGV_1"
            assert cmd1["params"]["target_point"] == "P8"
            assert cmd1["priority"] == "high"
            assert "quality_pickup" in cmd1["flow_stage"]

            # Check second command (raw pickup)
            cmd2 = commands[1]
            assert cmd2["action"] == "move"
            assert cmd2["target"] == "AGV_2"
            assert cmd2["params"]["target_point"] == "P0"
            assert cmd2["priority"] == "high"
            assert "raw_pickup" in cmd2["flow_stage"]

            logger.info("✅ Product Flow Agent test passed")
            logger.info(f"Generated commands: {json.dumps(commands, indent=2)}")


async def test_situation_analysis():
    """Test the situation analysis functionality."""
    logger.info("Testing situation analysis...")

    os.environ["OPENAI_API_KEY"] = "test-key"

    with patch("agents.Agent"):
        agent = ProductFlowAgent("line1")

        # Test data
        factory_state = create_test_factory_state()
        raw_material = factory_state["warehouse"]
        stations = factory_state["stations"]
        agvs = factory_state["agvs"]
        conveyors = factory_state["conveyors"]

        # Analyze situation
        analysis = agent._analyze_factory_situation(
            raw_material, stations, agvs, conveyors
        )

        # Verify analysis
        assert "actions_needed" in analysis
        assert len(analysis["actions_needed"]) > 0

        # Should detect finished products
        finished_product_actions = [
            a
            for a in analysis["actions_needed"]
            if a["action"] == "deliver_finished_products"
        ]
        assert len(finished_product_actions) == 1

        # Should detect raw materials
        raw_material_actions = [
            a
            for a in analysis["actions_needed"]
            if a["action"] == "start_new_production"
        ]
        assert len(raw_material_actions) == 1

        # Should detect P3 products in Conveyor_CQ
        p3_actions = [
            a
            for a in analysis["actions_needed"]
            if a["action"] == "continue_p3_processing"
        ]
        assert len(p3_actions) == 1

        logger.info("✅ Situation analysis test passed")
        logger.info(f"Analysis: {json.dumps(analysis, indent=2)}")


async def run_all_tests():
    """Run all product flow tests."""
    logger.info("Starting Product Flow Agent tests...")

    try:
        await test_product_flow_agent()
        await test_situation_analysis()

        logger.info("🎉 All Product Flow Agent tests passed!")

    except Exception as e:
        logger.error(f"❌ Test failed: {e}")
        raise


if __name__ == "__main__":
    asyncio.run(run_all_tests())
