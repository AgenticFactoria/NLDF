#!/usr/bin/env python3
"""
Main Line Commander Entry Point
Runs the new modular factory automation system with separated concerns:
- MQTT Listener Manager: Handles all MQTT communication
- Line Commander: Makes strategic decisions based on factory state
- Order MQTT Handler: Processes orders
"""

import asyncio
import logging
import os
import sys

from dotenv import load_dotenv

# Add current directory to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from src.line_commander import LineCommander

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


async def main():
    """Main function to run the line commander system."""

    # Load environment variables
    load_dotenv()

    # Check if API key is set
    if not os.getenv("OPENAI_API_KEY"):
        logger.error("OPENAI_API_KEY not set. Please set your OpenAI API key.")
        logger.error("export OPENAI_API_KEY='your-api-key-here'")
        return

    # Get line ID from environment or use default
    line_id = os.getenv("LINE_ID", "line1")
    max_orders = int(os.getenv("MAX_ORDERS_PER_CYCLE", "2"))

    logger.info(f"Starting Line Commander System for {line_id}")
    logger.info(f"Max orders per cycle: {max_orders}")

    # Create and start line commander
    line_commander = LineCommander(line_id=line_id, max_orders_per_cycle=max_orders)

    try:
        # Start the line commander operations
        await line_commander.start_command_operations()

    except KeyboardInterrupt:
        logger.info("Received interrupt signal, shutting down...")
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
    finally:
        # Clean shutdown
        line_commander.stop()
        logger.info("Line Commander System stopped")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("System interrupted by user")
    except Exception as e:
        logger.error(f"System error: {e}")
        sys.exit(1)
