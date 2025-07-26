#!/usr/bin/env python3
"""
Order MQTT Handler
Handles order-related MQTT communication and integrates with the shared order manager.
"""

import logging
from typing import Any, Dict

from shared_order_manager import SharedOrderManager

logger = logging.getLogger(__name__)


class OrderMQTTHandler:
    """Handles order processing from MQTT messages."""

    def __init__(self, line_id: str):
        self.line_id = line_id
        self.shared_order_manager = SharedOrderManager()

    def handle_order_message(self, message_type: str, data: Dict[str, Any]):
        """Handle incoming order MQTT messages."""
        try:
            if message_type == "order":
                logger.info(f"Processing new order for line {self.line_id}: {data}")

                # Process the order using SharedOrderManager
                order = self.shared_order_manager.process_order(data, self.line_id)

                if order:
                    logger.info(
                        f"Successfully processed order {order.order_id} with {len(order.products)} products"
                    )
                    return order
                else:
                    logger.warning(f"Failed to process order from MQTT: {data}")
                    return None
            else:
                logger.debug(f"Ignoring non-order message type: {message_type}")
                return None

        except Exception as e:
            logger.error(f"Error processing order message: {e}")
            return None

    def get_orders_for_processing(self, max_orders: int = 2):
        """Get orders available for processing on this line."""
        return self.shared_order_manager.get_orders_for_line(self.line_id)[:max_orders]

    def get_products_needing_transport(self):
        """Get products that need AGV transport."""
        return self.shared_order_manager.get_products_for_line(self.line_id)
