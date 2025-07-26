#!/usr/bin/env python3
"""
Shared Order Manager Singleton
Ensures only one instance manages all orders across all agents.
"""

import logging
import threading
from typing import Dict, List, Optional

from order import Order, OrderManager

logger = logging.getLogger(__name__)


class SharedOrderManager:
    """Singleton OrderManager shared across all factory agents."""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if not self._initialized:
            self._order_manager = OrderManager()
            self._assignment_lock = threading.Lock()
            self._processed_orders = set()
            self._line_assignment_counter = 0
            self._available_lines = ["line1", "line2", "line3"]  # All production lines
            self._initialized = True
            logger.info("SharedOrderManager initialized")

    def process_order(self, payload: Dict, requesting_line: str) -> Optional[Order]:
        """Process an order with proper line assignment logic."""
        order_id = payload.get("order_id")
        if not order_id:
            return None

        with self._assignment_lock:
            # Check if already processed
            if order_id in self._processed_orders:
                logger.debug(f"Order {order_id} already processed")
                return self._order_manager.orders.get(order_id)

            # Create order
            order = self._order_manager.create_order_from_payload(payload)
            if not order:
                return None

            # Assign products to lines using round-robin
            products = order.get_pending_products()
            if products:
                # For simplicity, assign entire order to one line for now
                assigned_line = self._get_next_assignment_line()
                product_ids = [p.product_id for p in products]
                self._order_manager.assign_order_to_line(
                    order_id, assigned_line, product_ids
                )

                logger.info(
                    f"Assigned order {order_id} with {len(products)} products to {assigned_line}"
                )

            self._processed_orders.add(order_id)
            return order

    def _get_next_assignment_line(self) -> str:
        """Get next line for assignment using round-robin."""
        line = self._available_lines[
            self._line_assignment_counter % len(self._available_lines)
        ]
        self._line_assignment_counter += 1
        return line

    def get_orders_for_line(self, line_id: str) -> List[Order]:
        """Get orders assigned to a specific line."""
        return [
            order
            for order in self._order_manager.get_active_orders()
            if line_id in order.line_assignments
        ]

    def get_products_for_line(self, line_id: str) -> List:
        """Get products assigned to a specific line."""
        return self._order_manager.get_products_needing_transport(line_id)

    def update_product_status(
        self, product_id: str, new_status, location: str = None, agv_id: str = None
    ):
        """Update product status."""
        return self._order_manager.update_product_status(
            product_id, new_status, location, agv_id
        )

    def complete_order_check(self):
        """Check for completed orders."""
        return self._order_manager.complete_order_check()

    def get_statistics(self) -> Dict:
        """Get order statistics."""
        return self._order_manager.get_order_statistics()
