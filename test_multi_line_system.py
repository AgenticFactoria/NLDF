#!/usr/bin/env python3
"""
Test script for the multi-line factory system.
Tests initialization and basic functionality of all 3 production lines.
"""

import asyncio
import logging
import os
import sys
from unittest.mock import MagicMock, patch

# Add current directory to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from main import MultiLineFactoryManager

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def test_multi_line_initialization():
    """Test initialization of all 3 production lines."""
    logger.info("Testing multi-line factory initialization...")

    # Mock the OpenAI API key
    os.environ["OPENAI_API_KEY"] = "test-key"

    with patch("src.line_commander.LineCommander") as mock_line_commander:
        # Mock LineCommander to avoid actual MQTT connections
        mock_instance = MagicMock()
        mock_instance.start_command_operations = MagicMock(
            return_value=asyncio.Future()
        )
        mock_instance.start_command_operations.return_value.set_result(None)
        mock_instance.stop = MagicMock()
        mock_line_commander.return_value = mock_instance

        # Create factory manager
        factory_manager = MultiLineFactoryManager(max_orders_per_cycle=2)

        # Test initialization
        await factory_manager.initialize_line_commanders()

        # Verify all 3 lines were created
        assert len(factory_manager.line_commanders) == 3
        assert "line1" in factory_manager.line_commanders
        assert "line2" in factory_manager.line_commanders
        assert "line3" in factory_manager.line_commanders

        # Verify LineCommander was called for each line
        assert mock_line_commander.call_count == 3

        # Check that each line was initialized with correct parameters
        calls = mock_line_commander.call_args_list
        line_ids = [call[1]["line_id"] for call in calls]
        assert "line1" in line_ids
        assert "line2" in line_ids
        assert "line3" in line_ids

        logger.info("✅ Multi-line initialization test passed")


async def test_multi_line_startup():
    """Test startup of all production lines."""
    logger.info("Testing multi-line factory startup...")

    os.environ["OPENAI_API_KEY"] = "test-key"

    with patch("src.line_commander.LineCommander") as mock_line_commander:
        # Mock LineCommander
        mock_instance = MagicMock()

        # Create a future that completes after a short delay
        async def mock_start_operations():
            await asyncio.sleep(0.1)  # Simulate startup time
            return "completed"

        mock_instance.start_command_operations = mock_start_operations
        mock_instance.stop = MagicMock()
        mock_line_commander.return_value = mock_instance

        # Create factory manager
        factory_manager = MultiLineFactoryManager(max_orders_per_cycle=1)

        # Initialize
        await factory_manager.initialize_line_commanders()

        # Test startup (but don't wait for completion)
        await factory_manager.start_all_lines()

        # Verify tasks were created
        assert len(factory_manager.running_tasks) == 3
        assert factory_manager.is_running == True

        # Verify task names
        task_names = [task.get_name() for task in factory_manager.running_tasks]
        assert "LineCommander_line1" in task_names
        assert "LineCommander_line2" in task_names
        assert "LineCommander_line3" in task_names

        # Clean shutdown
        await factory_manager.shutdown_all_lines()

        logger.info("✅ Multi-line startup test passed")


async def test_multi_line_shutdown():
    """Test graceful shutdown of all production lines."""
    logger.info("Testing multi-line factory shutdown...")

    os.environ["OPENAI_API_KEY"] = "test-key"

    with patch("src.line_commander.LineCommander") as mock_line_commander:
        # Mock LineCommander
        mock_instance = MagicMock()

        # Mock that never completes (simulates long-running operation)
        async def mock_long_operation():
            try:
                await asyncio.sleep(10)  # Long operation
            except asyncio.CancelledError:
                logger.info("Mock operation cancelled")
                raise

        mock_instance.start_command_operations = mock_long_operation
        mock_instance.stop = MagicMock()
        mock_line_commander.return_value = mock_instance

        # Create factory manager
        factory_manager = MultiLineFactoryManager()

        # Initialize and start
        await factory_manager.initialize_line_commanders()
        await factory_manager.start_all_lines()

        # Verify running
        assert len(factory_manager.running_tasks) == 3
        assert factory_manager.is_running == True

        # Test shutdown
        await factory_manager.shutdown_all_lines()

        # Verify shutdown
        assert factory_manager.is_running == False
        assert factory_manager.shutdown_event.is_set()

        # Verify all line commanders were stopped
        for line_commander in factory_manager.line_commanders.values():
            line_commander.stop.assert_called_once()

        logger.info("✅ Multi-line shutdown test passed")


async def test_production_line_configuration():
    """Test that each production line is configured correctly."""
    logger.info("Testing production line configuration...")

    os.environ["OPENAI_API_KEY"] = "test-key"

    with patch("src.line_commander.LineCommander") as mock_line_commander:
        mock_instance = MagicMock()
        mock_instance.start_command_operations = MagicMock(
            return_value=asyncio.Future()
        )
        mock_instance.start_command_operations.return_value.set_result(None)
        mock_instance.stop = MagicMock()
        mock_line_commander.return_value = mock_instance

        # Create factory manager with specific configuration
        max_orders = 3
        factory_manager = MultiLineFactoryManager(max_orders_per_cycle=max_orders)

        # Initialize
        await factory_manager.initialize_line_commanders()

        # Verify configuration was passed correctly
        calls = mock_line_commander.call_args_list
        for call in calls:
            assert call[1]["max_orders_per_cycle"] == max_orders

        # Verify production lines list
        assert factory_manager.production_lines == ["line1", "line2", "line3"]

        logger.info("✅ Production line configuration test passed")


async def run_all_tests():
    """Run all multi-line system tests."""
    logger.info("Starting multi-line factory system tests...")

    try:
        await test_multi_line_initialization()
        await test_multi_line_startup()
        await test_multi_line_shutdown()
        await test_production_line_configuration()

        logger.info("🎉 All multi-line factory system tests passed!")

    except Exception as e:
        logger.error(f"❌ Multi-line test failed: {e}")
        raise


if __name__ == "__main__":
    asyncio.run(run_all_tests())
