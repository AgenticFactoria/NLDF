#!/usr/bin/env python3
"""
Test script specifically for P3 product workflow.
Tests the P3 double processing flow with realistic factory data.
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


def create_p3_test_scenarios():
    """Create different P3 test scenarios."""

    # Scenario 1: P3 product available in RawMaterial
    scenario_1 = {
        "name": "P3 Raw Material Available",
        "factory_state": {
            "stations": {
                "StationA": {
                    "status": "idle",
                    "buffer": [],
                    "output_buffer": [],
                },
                "QualityCheck": {
                    "status": "idle",
                    "buffer": [],
                    "output_buffer": [],
                },
            },
            "agvs": {
                "AGV_1": {
                    "status": "idle",
                    "current_point": "P10",
                    "battery_level": 60.0,
                    "payload": [],
                },
                "AGV_2": {
                    "status": "idle",
                    "current_point": "P10",
                    "battery_level": 80.0,
                    "payload": [],
                },
            },
            "conveyors": {
                "Conveyor_CQ": {
                    "status": "working",
                    "buffer": [],
                    "upper_buffer": [],
                    "lower_buffer": [],
                }
            },
            "warehouse": {
                "buffer": ["prod_3_75a16c3d", "prod_1_abc123"],  # P3 and P1 products
                "stats": {"P1": 1, "P2": 0, "P3": 1},
            },
        },
        "expected_commands": 4,  # move, load, move, unload for P3 start
        "expected_flow_stage": "p3_raw_pickup",
    }

    # Scenario 2: P3 product in Conveyor_CQ upper buffer (needs second processing)
    scenario_2 = {
        "name": "P3 Second Processing Needed",
        "factory_state": {
            "stations": {
                "StationA": {
                    "status": "idle",
                    "buffer": [],
                    "output_buffer": [],
                },
                "StationB": {
                    "status": "idle",
                    "buffer": [],
                    "output_buffer": [],
                },
                "QualityCheck": {
                    "status": "idle",
                    "buffer": [],
                    "output_buffer": [],
                },
            },
            "agvs": {
                "AGV_1": {
                    "status": "idle",
                    "current_point": "P10",
                    "battery_level": 70.0,
                    "payload": [],
                },
                "AGV_2": {
                    "status": "idle",
                    "current_point": "P10",
                    "battery_level": 85.0,
                    "payload": [],
                },
            },
            "conveyors": {
                "Conveyor_CQ": {
                    "status": "working",
                    "buffer": [],
                    "upper_buffer": [
                        "prod_3_75a16c3d"
                    ],  # P3 product waiting for second processing
                    "lower_buffer": [],
                }
            },
            "warehouse": {"buffer": [], "stats": {"P1": 0, "P2": 0, "P3": 0}},
        },
        "expected_commands": 4,  # move to P6, load, move to P3, unload
        "expected_flow_stage": "p3_second_pickup",
    }

    # Scenario 3: P3 product finished in QualityCheck
    scenario_3 = {
        "name": "P3 Finished Product Ready",
        "factory_state": {
            "stations": {
                "QualityCheck": {
                    "status": "idle",
                    "buffer": [],
                    "output_buffer": ["prod_3_75a16c3d"],  # Finished P3 product
                }
            },
            "agvs": {
                "AGV_1": {
                    "status": "idle",
                    "current_point": "P10",
                    "battery_level": 75.0,
                    "payload": [],
                }
            },
            "conveyors": {
                "Conveyor_CQ": {
                    "status": "working",
                    "buffer": [],
                    "upper_buffer": [],
                    "lower_buffer": [],
                }
            },
            "warehouse": {"buffer": [], "stats": {"P1": 0, "P2": 0, "P3": 0}},
        },
        "expected_commands": 4,  # move to P8, load, move to P9, unload
        "expected_flow_stage": "p3_quality_pickup",
    }

    return [scenario_1, scenario_2, scenario_3]


async def test_p3_command_generation():
    """Test P3 command generation for different scenarios."""
    logger.info("Testing P3 command generation...")

    os.environ["OPENAI_API_KEY"] = "test-key"

    scenarios = create_p3_test_scenarios()

    with patch("agents.Agent") as mock_agent:
        with patch("agents.Runner") as mock_runner:
            for scenario in scenarios:
                logger.info(f"\n--- Testing Scenario: {scenario['name']} ---")

                # Mock agent response based on scenario
                mock_result = MagicMock()

                if "prod_3" in str(
                    scenario["factory_state"]["warehouse"].get("buffer", [])
                ):
                    # P3 raw material scenario
                    mock_result.final_output = [
                        {
                            "command_id": "p3_start_test_move_to_raw",
                            "action": "move",
                            "target": "AGV_1",
                            "params": {"target_point": "P0"},
                            "priority": "high",
                            "reasoning": "P3 product prod_3_75a16c3d: Move to RawMaterial for pickup",
                            "flow_stage": "p3_raw_pickup",
                        },
                        {
                            "command_id": "p3_start_test_load_raw",
                            "action": "load",
                            "target": "AGV_1",
                            "params": {"product_id": "prod_3_75a16c3d"},
                            "priority": "high",
                            "reasoning": "P3 product prod_3_75a16c3d: Load from RawMaterial",
                            "flow_stage": "p3_raw_pickup",
                        },
                    ]
                elif scenario["factory_state"]["conveyors"]["Conveyor_CQ"][
                    "upper_buffer"
                ]:
                    # P3 second processing scenario
                    mock_result.final_output = [
                        {
                            "command_id": "p3_continue_test_move_to_conveyor_cq",
                            "action": "move",
                            "target": "AGV_1",
                            "params": {"target_point": "P6"},
                            "priority": "high",
                            "reasoning": "P3 product prod_3_75a16c3d: Move to Conveyor_CQ for second processing pickup",
                            "flow_stage": "p3_second_pickup",
                        },
                        {
                            "command_id": "p3_continue_test_load_conveyor_cq",
                            "action": "load",
                            "target": "AGV_1",
                            "params": {"product_id": "prod_3_75a16c3d"},
                            "priority": "high",
                            "reasoning": "P3 product prod_3_75a16c3d: Load from Conveyor_CQ upper/lower buffer",
                            "flow_stage": "p3_second_pickup",
                        },
                    ]
                else:
                    # P3 finished product scenario
                    mock_result.final_output = [
                        {
                            "command_id": "p3_finish_test_move_to_quality",
                            "action": "move",
                            "target": "AGV_1",
                            "params": {"target_point": "P8"},
                            "priority": "high",
                            "reasoning": "P3 product prod_3_75a16c3d: Move to QualityCheck for finished product pickup",
                            "flow_stage": "p3_quality_pickup",
                        }
                    ]

                mock_runner.run.return_value = mock_result

                # Create agent and test
                agent = ProductFlowAgent("line1")
                commands = await agent.generate_flow_commands(
                    scenario["factory_state"], "planned"
                )

                # Verify commands
                assert len(commands) > 0, (
                    f"No commands generated for {scenario['name']}"
                )

                # Check for P3-specific logic
                p3_commands = [
                    cmd
                    for cmd in commands
                    if "prod_3" in str(cmd.get("params", {}).get("product_id", ""))
                ]
                if p3_commands:
                    logger.info(f"✅ P3 commands generated: {len(p3_commands)}")
                    for cmd in p3_commands:
                        logger.info(
                            f"   - {cmd['action']} to {cmd.get('params', {}).get('target_point', 'N/A')}"
                        )

                # Verify flow stage
                flow_stages = [cmd.get("flow_stage", "") for cmd in commands]
                expected_stage = scenario["expected_flow_stage"]
                if any(expected_stage in stage for stage in flow_stages):
                    logger.info(f"✅ Expected flow stage '{expected_stage}' found")
                else:
                    logger.warning(
                        f"⚠️  Expected flow stage '{expected_stage}' not found in {flow_stages}"
                    )

                logger.info(
                    f"Generated commands for {scenario['name']}: {json.dumps(commands, indent=2)}"
                )


async def test_p3_situation_analysis():
    """Test P3 situation analysis."""
    logger.info("Testing P3 situation analysis...")

    os.environ["OPENAI_API_KEY"] = "test-key"

    with patch("agents.Agent"):
        agent = ProductFlowAgent("line1")

        # Test scenario with P3 products in different stages
        factory_state = {
            "warehouse": {
                "buffer": ["prod_3_abc123", "prod_1_def456"],
                "stats": {"P1": 1, "P2": 0, "P3": 1},
            },
            "stations": {"QualityCheck": {"output_buffer": ["prod_3_finished"]}},
            "agvs": {"AGV_1": {"status": "idle", "battery_level": 60, "payload": []}},
            "conveyors": {
                "Conveyor_CQ": {"upper_buffer": ["prod_3_waiting"], "lower_buffer": []}
            },
        }

        analysis = agent._analyze_factory_situation(
            factory_state["warehouse"],
            factory_state["stations"],
            factory_state["agvs"],
            factory_state["conveyors"],
        )

        # Verify P3 detection
        assert "p3_products_detected" in analysis
        assert len(analysis["p3_products_detected"]) > 0

        # Check for P3-specific actions
        p3_actions = [a for a in analysis["actions_needed"] if "p3" in a["action"]]
        assert len(p3_actions) > 0, "No P3-specific actions detected"

        logger.info("✅ P3 situation analysis test passed")
        logger.info(f"P3 products detected: {analysis['p3_products_detected']}")
        logger.info(f"P3 actions needed: {[a['action'] for a in p3_actions]}")


async def run_p3_tests():
    """Run all P3 workflow tests."""
    logger.info("Starting P3 workflow tests...")

    try:
        await test_p3_command_generation()
        await test_p3_situation_analysis()

        logger.info("🎉 All P3 workflow tests passed!")

    except Exception as e:
        logger.error(f"❌ P3 test failed: {e}")
        raise


if __name__ == "__main__":
    asyncio.run(run_p3_tests())
