#!/usr/bin/env python3
"""
Multi-Line Factory Automation System
Starts Line Commanders for all 3 production lines simultaneously.

This is the main entry point for the complete factory automation system
that manages line1, line2, and line3 with their respective AGVs.
"""

import asyncio
import logging
import os
import signal
import sys
from typing import Dict, List

from dotenv import load_dotenv

# Add current directory to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from src.line_commander import LineCommander

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("factory_automation.log"),
    ],
)
logger = logging.getLogger(__name__)


class MultiLineFactoryManager:
    """
    Manages multiple production lines simultaneously.
    Coordinates Line Commanders for line1, line2, and line3.
    """

    def __init__(self, max_orders_per_cycle: int = 2):
        self.max_orders_per_cycle = max_orders_per_cycle
        self.line_commanders: Dict[str, LineCommander] = {}
        self.running_tasks: List[asyncio.Task] = []
        self.is_running = False

        # Production lines to manage
        self.production_lines = ["line1", "line2", "line3"]

        # Shutdown event
        self.shutdown_event = asyncio.Event()

    async def initialize_line_commanders(self):
        """Initialize Line Commanders for all production lines."""
        logger.info("Initializing Line Commanders for all production lines...")

        for line_id in self.production_lines:
            try:
                logger.info(f"Creating Line Commander for {line_id}...")
                line_commander = LineCommander(
                    line_id=line_id, max_orders_per_cycle=self.max_orders_per_cycle
                )
                self.line_commanders[line_id] = line_commander
                logger.info(f"✅ Line Commander for {line_id} created successfully")

            except Exception as e:
                logger.error(f"❌ Failed to create Line Commander for {line_id}: {e}")
                raise

        logger.info(
            f"🎉 All {len(self.line_commanders)} Line Commanders initialized successfully"
        )

    async def start_all_lines(self):
        """Start operations for all production lines concurrently."""
        logger.info("Starting operations for all production lines...")

        self.is_running = True

        # Start each line commander as a separate task
        for line_id, line_commander in self.line_commanders.items():
            try:
                logger.info(f"Starting operations for {line_id}...")
                task = asyncio.create_task(
                    line_commander.start_command_operations(),
                    name=f"LineCommander_{line_id}",
                )
                self.running_tasks.append(task)
                logger.info(f"✅ {line_id} operations started")

            except Exception as e:
                logger.error(f"❌ Failed to start operations for {line_id}: {e}")
                raise

        logger.info(
            f"🚀 All {len(self.running_tasks)} production lines are now operational!"
        )

    async def monitor_lines(self):
        """Monitor all production lines and handle failures."""
        logger.info("Starting line monitoring...")

        while self.is_running and not self.shutdown_event.is_set():
            try:
                # Check if any tasks have completed or failed
                done_tasks = [task for task in self.running_tasks if task.done()]

                for task in done_tasks:
                    line_name = task.get_name()
                    try:
                        # Check if task completed successfully or with exception
                        await task
                        logger.warning(f"⚠️  {line_name} completed unexpectedly")
                    except Exception as e:
                        logger.error(f"❌ {line_name} failed with error: {e}")

                    # Remove completed task from running tasks
                    self.running_tasks.remove(task)

                # If any critical tasks failed, we might want to restart them
                if done_tasks:
                    logger.warning(
                        f"⚠️  {len(done_tasks)} line(s) stopped. Remaining active: {len(self.running_tasks)}"
                    )

                # Wait before next check
                await asyncio.sleep(5.0)

            except Exception as e:
                logger.error(f"Error in line monitoring: {e}")
                await asyncio.sleep(5.0)

    async def shutdown_all_lines(self):
        """Gracefully shutdown all production lines."""
        logger.info("Initiating graceful shutdown of all production lines...")

        self.is_running = False
        self.shutdown_event.set()

        # Stop all line commanders
        for line_id, line_commander in self.line_commanders.items():
            try:
                logger.info(f"Stopping {line_id}...")
                line_commander.stop()
                logger.info(f"✅ {line_id} stopped")
            except Exception as e:
                logger.error(f"Error stopping {line_id}: {e}")

        # Cancel all running tasks
        if self.running_tasks:
            logger.info(f"Cancelling {len(self.running_tasks)} running tasks...")
            for task in self.running_tasks:
                if not task.done():
                    task.cancel()

            # Wait for tasks to complete cancellation
            try:
                await asyncio.gather(*self.running_tasks, return_exceptions=True)
            except Exception as e:
                logger.error(f"Error during task cancellation: {e}")

        logger.info("🛑 All production lines have been shut down")

    async def run_factory(self):
        """Main factory operation loop."""
        try:
            # Initialize all line commanders
            await self.initialize_line_commanders()

            # Start all production lines
            await self.start_all_lines()

            # Start monitoring task
            monitor_task = asyncio.create_task(self.monitor_lines(), name="LineMonitor")

            # Wait for shutdown signal or all tasks to complete
            try:
                # Wait for either shutdown event or all tasks to complete
                await asyncio.gather(
                    self.shutdown_event.wait(),
                    *self.running_tasks,
                    return_exceptions=True,
                )
            except KeyboardInterrupt:
                logger.info("Received keyboard interrupt")
            finally:
                # Cancel monitor task
                if not monitor_task.done():
                    monitor_task.cancel()
                    try:
                        await monitor_task
                    except asyncio.CancelledError:
                        pass

        except Exception as e:
            logger.error(f"Critical error in factory operations: {e}")
            raise
        finally:
            await self.shutdown_all_lines()


def setup_signal_handlers(factory_manager: MultiLineFactoryManager):
    """Setup signal handlers for graceful shutdown."""

    def signal_handler(signum, frame):
        logger.info(f"Received signal {signum}, initiating shutdown...")
        asyncio.create_task(factory_manager.shutdown_all_lines())

    # Handle SIGINT (Ctrl+C) and SIGTERM
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)


async def main():
    """Main function to run the multi-line factory automation system."""

    # Load environment variables
    load_dotenv()

    # Check if API key is set
    if not os.getenv("OPENAI_API_KEY"):
        logger.error("❌ OPENAI_API_KEY not set. Please set your OpenAI API key.")
        logger.error("   export OPENAI_API_KEY='your-api-key-here'")
        return 1

    # Get configuration from environment
    max_orders = int(os.getenv("MAX_ORDERS_PER_CYCLE", "2"))
    topic_root = os.getenv(
        "TOPIC_ROOT", os.getenv("USERNAME", os.getenv("USER", "NLDF_TEST"))
    )

    logger.info("🏭 Starting Multi-Line Factory Automation System")
    logger.info(f"   Topic Root: {topic_root}")
    logger.info(f"   Max Orders Per Cycle: {max_orders}")
    logger.info("   Production Lines: line1, line2, line3")
    logger.info("   Total AGVs: 6 (2 per line)")

    # Create factory manager
    factory_manager = MultiLineFactoryManager(max_orders_per_cycle=max_orders)

    # Setup signal handlers for graceful shutdown
    setup_signal_handlers(factory_manager)

    try:
        # Run the factory
        await factory_manager.run_factory()
        return 0

    except KeyboardInterrupt:
        logger.info("🛑 Factory automation stopped by user")
        return 0
    except Exception as e:
        logger.error(f"❌ Factory automation failed: {e}")
        return 1


def print_startup_banner():
    """Print startup banner with system information."""
    banner = """
╔══════════════════════════════════════════════════════════════════════════════╗
║                    SUPCON NLDF Factory Automation System                    ║
║                          Multi-Line Production Manager                       ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  🏭 Production Lines: line1, line2, line3                                   ║
║  🤖 Total AGVs: 6 (AGV_1 & AGV_2 per line)                                 ║
║  🧠 AI Agents: Product Flow Specialists with P3 support                     ║
║  📡 Communication: MQTT with real-time status monitoring                    ║
║  ⚡ Features: Reactive processing, P3 double processing, AGV optimization   ║
╚══════════════════════════════════════════════════════════════════════════════╝
    """
    print(banner)


if __name__ == "__main__":
    # Print startup banner
    print_startup_banner()

    try:
        # Run the main factory system
        exit_code = asyncio.run(main())
        sys.exit(exit_code)

    except KeyboardInterrupt:
        logger.info("🛑 System interrupted by user")
        sys.exit(0)
    except Exception as e:
        logger.error(f"❌ System error: {e}")
        sys.exit(1)
