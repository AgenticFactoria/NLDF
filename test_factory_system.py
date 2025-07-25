#!/usr/bin/env python3
"""
Test Factory Agent System
Tests the complete system with sample order data.
"""

import asyncio
import json
import logging
import os
import sys

import dotenv
from agents import AgentOutputSchema

# Add parent directory to path to import modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.schemas import AgentCommand
from shared_order_manager import SharedOrderManager
from src.factory_agent_manager import FactoryAgentManager

dotenv.load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def test_agent_system():
    """Test the agent system with sample data."""

    # Check API key
    if not os.getenv("OPENAI_API_KEY"):
        logger.error("OPENAI_API_KEY not set. Please set your OpenAI API key.")
        return

    logger.info("Testing Factory Agent System...")

    # Create sample order data
    sample_orders = [
        {
            "order_id": "order_test_001",
            "items": [
                {"product_type": "P1", "quantity": 1},
                {"product_type": "P2", "quantity": 1},
            ],
            "deadline": 1800.0,  # 30 minutes
        },
        {
            "order_id": "order_test_002",
            "items": [{"product_type": "P3", "quantity": 1}],
            "deadline": 2400.0,  # 40 minutes
        },
    ]

    # Initialize shared order manager and add sample orders
    shared_manager = SharedOrderManager()

    for order_data in sample_orders:
        order = shared_manager.process_order(order_data, requesting_line="line1")
        if order:
            logger.info(f"Added test order: {order.order_id}")
        else:
            logger.error(f"Failed to add test order: {order_data['order_id']}")

    # Create agent manager
    agent_manager = FactoryAgentManager(line_id="line1", max_orders_per_cycle=2)

    try:
        # Start MQTT listening (for responses)
        agent_manager.start_mqtt_listening()

        # Run a few processing cycles
        for cycle in range(3):
            logger.info(f"Running processing cycle {cycle + 1}")
            await agent_manager.process_orders_cycle()
            await asyncio.sleep(3)  # Wait between cycles

        logger.info("Test completed successfully!")

        # Print command history
        logger.info("=== COMMAND HISTORY ===")
        recent_commands = agent_manager.command_history.get_recent_commands(10)
        for cmd in recent_commands:
            logger.info(f"Command: {json.dumps(cmd, indent=2)}")

    except Exception as e:
        logger.error(f"Test failed: {e}")
    finally:
        agent_manager.stop()


async def test_simple_agent_interaction():
    """Test simple agent interaction without full system."""

    # Check API key
    if not os.getenv("OPENAI_API_KEY"):
        logger.error("OPENAI_API_KEY not set. Skipping agent test.")
        return

    from agents import Agent, Runner, SQLiteSession

    logger.info("Testing simple agent interaction...")

    # Create a simple factory agent
    agent = Agent(
        name="TestFactoryAgent",
        model="gpt-4.1-mini",
        instructions="""
You are a factory control agent. When given factory state information, 
respond with AGV commands in JSON format.

Always respond with a JSON object like:
{"command_id": "test_1", "action": "move", "target": "AGV_1", "params": {"target_point": "P1"}}
""",
        output_type=AgentOutputSchema(AgentCommand, strict_json_schema=False),
    )

    # Create session for history
    session = SQLiteSession("test_factory_session")

    # Test query
    test_query = """
Factory State:
- AGV_1: at P0 (RawMaterial), battery 85%
- AGV_2: at P9 (Warehouse), battery 60%  
- Order pending: prod_p1_123 needs transport from P0 to P1

Generate commands to move the product.
"""

    try:
        result = await Runner.run(agent, test_query, session=session)
        logger.info(f"Agent response: {result.final_output}")

        # Test with follow-up (should remember context)
        follow_up = "What should AGV_2 do next?"
        result2 = await Runner.run(agent, follow_up, session=session)
        logger.info(f"Follow-up response: {result2.final_output}")

    except Exception as e:
        logger.error(f"Simple agent test failed: {e}")


async def main():
    """Main test function."""
    logger.info("Starting Factory Agent System Tests...")

    # Test 1: Simple agent interaction
    await test_simple_agent_interaction()

    await asyncio.sleep(2)

    # Test 2: Full system test
    await test_agent_system()

    logger.info("All tests completed!")


if __name__ == "__main__":
    asyncio.run(main())
