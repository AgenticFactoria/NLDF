#!/usr/bin/env python3
"""
Order Management System for SUPCON NLDF Factory Automation
Handles order tracking, product lifecycle, and production coordination.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Dict, List, Optional, Set

logger = logging.getLogger(__name__)


class ProductType(Enum):
    """Product types supported by the factory."""

    P1 = "P1"
    P2 = "P2"
    P3 = "P3"


class ProductStatus(Enum):
    """Product status throughout the production pipeline."""

    PENDING = "pending"  # In raw material storage
    IN_TRANSPORT = "in_transport"  # Being moved by AGV
    AT_STATION_A = "at_station_a"  # At Station A
    AT_STATION_B = "at_station_b"  # At Station B
    AT_STATION_C = "at_station_c"  # At Station C
    AT_QUALITY_CHECK = "at_quality_check"  # At Quality Check
    IN_WAREHOUSE = "in_warehouse"  # Completed in warehouse
    FAILED_QC = "failed_qc"  # Failed quality check
    ERROR = "error"  # Error in production


class OrderStatus(Enum):
    """Order status tracking."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    OVERDUE = "overdue"


@dataclass
class Product:
    """Represents a single product in the production system."""

    product_id: str
    product_type: ProductType
    status: ProductStatus = ProductStatus.PENDING
    current_location: str = "RawMaterial"
    assigned_agv: Optional[str] = None
    created_time: datetime = field(default_factory=datetime.now)
    completion_time: Optional[datetime] = None
    processing_history: List[Dict] = field(default_factory=list)

    def add_processing_step(
        self, location: str, action: str, timestamp: Optional[datetime] = None
    ):
        """Add a processing step to the product's history."""
        if timestamp is None:
            timestamp = datetime.now()

        self.processing_history.append(
            {
                "location": location,
                "action": action,
                "timestamp": timestamp.isoformat(),
                "status": self.status.value,
            }
        )

    def get_next_processing_step(self) -> Optional[str]:
        """Get the next processing location for this product."""
        if self.product_type == ProductType.P3:
            return self._get_p3_next_step()
        else:
            return self._get_p1_p2_next_step()

    def _get_p1_p2_next_step(self) -> Optional[str]:
        """Get next step for P1/P2 products."""
        flow = {
            ProductStatus.PENDING: "StationA",
            ProductStatus.AT_STATION_A: "StationB",
            ProductStatus.AT_STATION_B: "StationC",
            ProductStatus.AT_STATION_C: "QualityCheck",
            ProductStatus.AT_QUALITY_CHECK: "Warehouse",
        }
        return flow.get(self.status)

    def _get_p3_next_step(self) -> Optional[str]:
        """Get next step for P3 products (includes double processing)."""
        # P3 has more complex flow with double processing at B and C
        if self.status == ProductStatus.PENDING:
            return "StationA"
        elif self.status == ProductStatus.AT_STATION_A:
            return "StationB"
        elif self.status == ProductStatus.AT_STATION_B:
            # Check if this is first or second time at Station B
            b_visits = sum(
                1 for step in self.processing_history if step["location"] == "StationB"
            )
            if b_visits < 2:
                return "StationC"
            else:
                return "StationC"  # Second round
        elif self.status == ProductStatus.AT_STATION_C:
            # Check if this is first or second time at Station C
            c_visits = sum(
                1 for step in self.processing_history if step["location"] == "StationC"
            )
            if c_visits < 2:
                return "StationB"  # Go back for second round
            else:
                return "QualityCheck"  # Done with processing
        elif self.status == ProductStatus.AT_QUALITY_CHECK:
            return "Warehouse"

        return None


@dataclass
class Order:
    """Represents a production order containing multiple products."""

    order_id: str
    products: List[Product] = field(default_factory=list)
    status: OrderStatus = OrderStatus.PENDING
    created_time: datetime = field(default_factory=datetime.now)
    delivery_time: Optional[datetime] = None
    assigned: bool = False
    line_assignments: Dict[str, List[str]] = field(
        default_factory=dict
    )  # line_id -> product_ids

    def add_product(self, product: Product):
        """Add a product to this order."""
        self.products.append(product)
        if self.status == OrderStatus.PENDING:
            self.status = OrderStatus.IN_PROGRESS

    def get_pending_products(self) -> List[Product]:
        """Get products that haven't been completed."""
        return [
            p
            for p in self.products
            if p.status not in [ProductStatus.IN_WAREHOUSE, ProductStatus.FAILED_QC]
        ]

    def get_products_for_line(self, line_id: str) -> List[Product]:
        """Get products assigned to a specific line."""
        assigned_product_ids = self.line_assignments.get(line_id, [])
        return [p for p in self.products if p.product_id in assigned_product_ids]

    def assign_product_to_line(self, product_id: str, line_id: str):
        """Assign a product to a specific production line."""
        if line_id not in self.line_assignments:
            self.line_assignments[line_id] = []

        if product_id not in self.line_assignments[line_id]:
            self.line_assignments[line_id].append(product_id)
            self.assigned = True

    def is_completed(self) -> bool:
        """Check if all products in the order are completed."""
        return all(
            p.status in [ProductStatus.IN_WAREHOUSE, ProductStatus.FAILED_QC]
            for p in self.products
        )

    def get_completion_rate(self) -> float:
        """Get the completion rate of this order (0.0 to 1.0)."""
        if not self.products:
            return 0.0

        completed = sum(
            1 for p in self.products if p.status == ProductStatus.IN_WAREHOUSE
        )
        return completed / len(self.products)


class OrderManager:
    """Manages all orders and product tracking for the factory."""

    def __init__(self):
        self.orders: Dict[str, Order] = {}
        self.products: Dict[str, Product] = {}
        self.active_order_ids: Set[str] = set()

    def create_order_from_payload(self, payload: Dict) -> Optional[Order]:
        """Create an order from MQTT payload."""
        try:
            order_id = payload.get("order_id")
            if not order_id:
                logger.error("Order payload missing order_id")
                return None

            # Check if order already exists
            if order_id in self.orders:
                logger.warning(f"Order {order_id} already exists")
                return self.orders[order_id]

            # Create new order
            order = Order(order_id=order_id)

            # Set delivery time if provided (deadline is in seconds from creation)
            if "deadline" in payload:
                try:
                    deadline_seconds = float(payload["deadline"])
                    order.delivery_time = datetime.now() + timedelta(
                        seconds=deadline_seconds
                    )
                except Exception as e:
                    logger.warning(f"Error parsing deadline: {e}")

            # Add products from payload - handle 'items' structure
            items_data = payload.get("items", [])
            product_counter = 1

            for item in items_data:
                product_type_str = item.get("product_type", "P1")
                quantity = item.get("quantity", 1)

                # Create individual products for each quantity
                for i in range(quantity):
                    # Generate unique product ID
                    product_id = f"prod_{product_type_str.lower()}_{order_id}_{product_counter:03d}"

                    product = self._create_product_from_item(
                        product_id, product_type_str
                    )
                    if product:
                        order.add_product(product)
                        self.products[product.product_id] = product
                        product_counter += 1

            # Store order
            self.orders[order_id] = order
            self.active_order_ids.add(order_id)

            logger.info(f"Created order {order_id} with {len(order.products)} products")
            return order

        except Exception as e:
            logger.error(f"Error creating order from payload: {e}")
            return None

    def _create_product_from_item(
        self, product_id: str, product_type_str: str
    ) -> Optional[Product]:
        """Create a product from order item data."""
        try:
            # Parse product type
            try:
                product_type = ProductType(product_type_str)
            except ValueError:
                logger.warning(
                    f"Unknown product type {product_type_str}, defaulting to P1"
                )
                product_type = ProductType.P1

            product = Product(product_id=product_id, product_type=product_type)

            product.add_processing_step("RawMaterial", "order_received")
            logger.debug(f"Created product {product_id} of type {product_type_str}")
            return product

        except Exception as e:
            logger.error(f"Error creating product: {e}")
            return None

    def get_active_orders(self) -> List[Order]:
        """Get all active (non-completed) orders."""
        return [
            order
            for order in self.orders.values()
            if order.order_id in self.active_order_ids and not order.is_completed()
        ]

    def get_unassigned_orders(self) -> List[Order]:
        """Get orders that haven't been assigned to any line."""
        return [order for order in self.get_active_orders() if not order.assigned]

    def update_product_status(
        self,
        product_id: str,
        new_status: ProductStatus,
        location: str = None,
        agv_id: str = None,
    ):
        """Update the status of a product."""
        if product_id not in self.products:
            logger.warning(f"Product {product_id} not found")
            return

        product = self.products[product_id]
        old_status = product.status
        product.status = new_status

        if location:
            product.current_location = location

        if agv_id:
            product.assigned_agv = agv_id

        # Add processing step
        action = f"status_changed_from_{old_status.value}_to_{new_status.value}"
        product.add_processing_step(location or product.current_location, action)

        # Mark as completed if reached warehouse
        if new_status == ProductStatus.IN_WAREHOUSE:
            product.completion_time = datetime.now()

        logger.info(
            f"Product {product_id} status: {old_status.value} -> {new_status.value}"
        )

    def assign_order_to_line(
        self, order_id: str, line_id: str, product_ids: Optional[List[str]] = None
    ):
        """Assign an order (or specific products) to a production line."""
        if order_id not in self.orders:
            logger.error(f"Order {order_id} not found")
            return

        order = self.orders[order_id]

        # If no specific products specified, assign all pending products
        if product_ids is None:
            product_ids = [p.product_id for p in order.get_pending_products()]

        for product_id in product_ids:
            order.assign_product_to_line(product_id, line_id)

        logger.info(
            f"Assigned {len(product_ids)} products from order {order_id} to {line_id}"
        )

    def get_products_needing_transport(self, line_id: str) -> List[Product]:
        """Get products that need AGV transport for a specific line."""
        line_products = []

        for order in self.get_active_orders():
            line_products.extend(order.get_products_for_line(line_id))

        # Filter for products that need transport
        transport_needed = []
        for product in line_products:
            if (
                product.status
                in [ProductStatus.PENDING, ProductStatus.AT_QUALITY_CHECK]
                and not product.assigned_agv
            ):
                transport_needed.append(product)

        return transport_needed

    def complete_order_check(self):
        """Check and update completed orders."""
        for order_id in list(self.active_order_ids):
            order = self.orders[order_id]
            if order.is_completed():
                order.status = OrderStatus.COMPLETED
                self.active_order_ids.discard(order_id)
                logger.info(
                    f"Order {order_id} completed with {order.get_completion_rate() * 100:.1f}% success rate"
                )

    def get_order_statistics(self) -> Dict:
        """Get statistics about current orders."""
        total_orders = len(self.orders)
        active_orders = len(self.active_order_ids)
        completed_orders = sum(1 for o in self.orders.values() if o.is_completed())

        total_products = len(self.products)
        completed_products = sum(
            1 for p in self.products.values() if p.status == ProductStatus.IN_WAREHOUSE
        )

        return {
            "total_orders": total_orders,
            "active_orders": active_orders,
            "completed_orders": completed_orders,
            "completion_rate": completed_orders / total_orders
            if total_orders > 0
            else 0,
            "total_products": total_products,
            "completed_products": completed_products,
            "product_completion_rate": completed_products / total_products
            if total_products > 0
            else 0,
        }
