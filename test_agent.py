#!/usr/bin/env python3
"""
Test script to verify OpenAI Agents SDK integration.
"""

import asyncio
import os

from agents import Agent, Runner


async def test_basic_agent():
    """Test basic agent functionality."""
    # Create a simple agent
    agent = Agent(
        name="TestAgent",
        instructions="You are a helpful test assistant. Respond concisely.",
    )

    # Test query
    result = await Runner.run(agent, "What is 2+2?")
    print(f"Agent response: {result.final_output}")


async def test_factory_agent_instructions():
    """Test factory-specific agent instructions."""
    instructions = """
You are an AI agent controlling production line line1 in a factory automation system.

RESPONSIBILITIES:
- Manage 2 AGVs (AGV_1 and AGV_2) to fulfill production orders
- Monitor station status and coordinate product flow
- Optimize for KPI metrics: order completion rate, production efficiency, AGV utilization

AVAILABLE ACTIONS:
1. move: Move AGV to specific location (P0-P9)
2. load: Load product from current location onto AGV
3. unload: Unload product from AGV to current location
4. charge: Send AGV to charge (when battery < 30%)

Given the context, respond with JSON commands only.
"""

    agent = Agent(name="FactoryTestAgent", instructions=instructions)

    # Test factory decision making
    context = {
        "available_agvs": [
            {
                "id": "AGV_1",
                "battery": 85,
                "location": "P0",
                "cargo": None,
                "status": "IDLE",
            },
            {
                "id": "AGV_2",
                "battery": 60,
                "location": "P1",
                "cargo": "prod_1_123",
                "status": "IDLE",
            },
        ],
        "active_orders": [
            {
                "order_id": "order_001",
                "products": [{"id": "prod_1_456", "type": "P1", "status": "pending"}],
            }
        ],
        "station_status": {
            "StationA": {"status": "IDLE", "queue_length": 0},
            "StationB": {"status": "PROCESSING", "queue_length": 2},
        },
    }

    query = f"""
Based on this factory state, determine optimal actions:
{context}

Provide JSON response with AGV commands.
"""

    result = await Runner.run(agent, query)
    print(f"Factory Agent Decision: {result.final_output}")


async def main():
    print("Testing OpenAI Agents SDK integration...")

    # Check if API key is set
    if not os.getenv("OPENAI_API_KEY"):
        print("WARNING: OPENAI_API_KEY not set. Please set your OpenAI API key.")
        print("export OPENAI_API_KEY='your-api-key-here'")
    else:
        print("✓ OpenAI API key found")

    try:
        await test_basic_agent()
        print("✓ Basic agent test passed")

        await test_factory_agent_instructions()
        print("✓ Factory agent test passed")

    except Exception as e:
        print(f"✗ Test failed: {e}")


if __name__ == "__main__":
    asyncio.run(main())
