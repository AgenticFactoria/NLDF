#!/usr/bin/env python3
"""
Main Factory Agent System
Integrates order MQTT handling with AI agent processing.
"""

import asyncio
import logging
import os
import sys
import threading

# Add parent directory to path to import modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.factory_agent_manager import FactoryAgentManager
from src.order_mqtt_handler import OrderMQTTHandler

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class FactoryAgentSystem:
    """Complete factory agent system combining order handling and AI processing."""

    def __init__(self, line_id: str = "line1"):
        self.line_id = line_id

        # Order handling component
        self.order_handler = OrderMQTTHandler()

        # AI agent management component
        self.agent_manager = FactoryAgentManager(
            line_id=line_id, max_orders_per_cycle=2
        )

        # Threading for concurrent operation
        self.order_thread = None
        self.agent_task = None
        self.is_running = False

    def start_order_listening(self):
        """Start order MQTT listening in a separate thread."""

        def run_order_handler():
            try:
                self.order_handler.start_listening()

                # Keep the handler running
                while self.is_running:
                    pass

            except Exception as e:
                logger.error(f"Error in order handler: {e}")
            finally:
                self.order_handler.stop_listening()

        self.order_thread = threading.Thread(target=run_order_handler, daemon=True)
        self.order_thread.start()
        logger.info("Started order MQTT listening thread")

    async def start_agent_processing(self):
        """Start AI agent processing."""
        try:
            await self.agent_manager.start_continuous_processing()
        except Exception as e:
            logger.error(f"Error in agent processing: {e}")

    async def start_system(self):
        """Start the complete factory agent system."""
        logger.info("Starting Factory Agent System...")

        # Check API key
        if not os.getenv("OPENAI_API_KEY"):
            logger.error("OPENAI_API_KEY not set. Please set your OpenAI API key.")
            return

        self.is_running = True

        # Start order listening in background thread
        self.start_order_listening()

        # Wait a moment for order handler to initialize
        await asyncio.sleep(2)

        # Start agent processing (this will run continuously)
        await self.start_agent_processing()

    def stop_system(self):
        """Stop the factory agent system."""
        logger.info("Stopping Factory Agent System...")
        self.is_running = False

        # Stop agent manager
        self.agent_manager.stop()

        # Order handler will stop when thread stops
        if self.order_thread and self.order_thread.is_alive():
            self.order_thread.join(timeout=5)

        logger.info("Factory Agent System stopped")


async def main():
    """Main function to run the complete factory agent system."""
    from dotenv import load_dotenv

    load_dotenv()
    system = FactoryAgentSystem(line_id="line1")

    try:
        await system.start_system()
    except KeyboardInterrupt:
        logger.info("Received interrupt signal")
    finally:
        system.stop_system()


if __name__ == "__main__":
    asyncio.run(main())
