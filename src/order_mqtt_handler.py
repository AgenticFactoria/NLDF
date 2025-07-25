import json
import logging
import os
import sys
from typing import Any, Dict

# Add parent directory to path to import modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.settings import MQTT_BROKER_HOST, MQTT_BROKER_PORT
from config.topics import NEW_ORDER_TOPIC
from shared_order_manager import SharedOrderManager
from utils.mqtt_client import MQTTClient

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class OrderMQTTHandler:
    """Handles order MQTT data reception and storage."""

    def __init__(self):
        self.mqtt_client = MQTTClient(
            host=MQTT_BROKER_HOST, port=MQTT_BROKER_PORT, client_id="order_mqtt_handler"
        )
        self.shared_order_manager = SharedOrderManager()

    def process_order_mqtt_data(self, mqtt_payload: Dict[str, Any]) -> bool:
        """
        Process order MQTT data and store it in appropriate data structures.

        Expected payload format:
        {
            'order_id': 'order_c88d7023',
            'created_at': 90.0,
            'items': [
                {'product_type': 'P1', 'quantity': 1},
                {'product_type': 'P2', 'quantity': 1}
            ],
            'priority': 'medium',
            'deadline': 810.0
        }

        Args:
            mqtt_payload (Dict[str, Any]): The MQTT payload containing order data

        Returns:
            bool: True if order was successfully processed and stored, False otherwise
        """
        try:
            logger.info(f"Processing order MQTT data: {mqtt_payload}")

            # Validate required fields
            required_fields = ["order_id", "items"]
            for field in required_fields:
                if field not in mqtt_payload:
                    logger.error(f"Missing required field '{field}' in MQTT payload")
                    return False

            # Extract order information
            order_id = mqtt_payload["order_id"]
            items = mqtt_payload["items"]
            deadline = mqtt_payload.get("deadline")

            # Validate items structure
            if not items or not isinstance(items, list):
                logger.error("Items field must be a non-empty list")
                return False

            for item in items:
                if (
                    not isinstance(item, dict)
                    or "product_type" not in item
                    or "quantity" not in item
                ):
                    logger.error(f"Invalid item structure: {item}")
                    return False

            # Convert to format expected by SharedOrderManager.process_order()
            order_payload = {"order_id": order_id, "items": items}

            # Add optional fields if present
            if deadline is not None:
                order_payload["deadline"] = deadline

            # Process and store the order using SharedOrderManager
            order = self.shared_order_manager.process_order(
                order_payload, requesting_line="line1"
            )

            if order:
                logger.info(f"Successfully processed and stored order {order_id}")

                # Log additional order details
                assigned_lines = (
                    list(order.line_assignments.keys())
                    if order.line_assignments
                    else ["None"]
                )
                logger.info(
                    f"Order details - ID: {order.order_id}, "
                    f"Status: {order.status}, "
                    f"Products: {len(order.products)}, "
                    f"Assigned Lines: {assigned_lines}"
                )

                # Log product details
                for product in order.products:
                    logger.info(
                        f"Product {product.product_id}: "
                        f"Type: {product.product_type}, "
                        f"Status: {product.status}"
                    )

                return True

            else:
                logger.error(f"Failed to process order {order_id}")
                return False

        except Exception as e:
            logger.error(f"Error processing order MQTT data: {e}")
            return False

    def on_order_message(self, client, userdata, message):
        """
        MQTT callback function for handling order messages.

        Args:
            client: MQTT client instance
            userdata: User data passed to callback
            message: MQTT message object
        """
        try:
            # Decode the MQTT message payload
            payload_str = message.payload.decode("utf-8")
            payload_dict = json.loads(payload_str)

            logger.info(f"Received order MQTT message on topic {message.topic}")

            # Process the order data
            self.process_order_mqtt_data(payload_dict)

        except json.JSONDecodeError as e:
            logger.error(f"Failed to decode JSON from MQTT message: {e}")
        except Exception as e:
            logger.error(f"Error in MQTT message callback: {e}")

    def start_listening(self):
        """Start listening for order MQTT messages."""
        try:
            logger.info(
                f"Starting to listen for order messages on topic: {NEW_ORDER_TOPIC}"
            )

            # Connect to MQTT broker
            self.mqtt_client.connect()

            # Subscribe to the order topic with callback
            self.mqtt_client.subscribe(NEW_ORDER_TOPIC, self.on_order_message)

            logger.info("Successfully started MQTT order listener")

        except Exception as e:
            logger.error(f"Failed to start MQTT order listener: {e}")
            raise

    def stop_listening(self):
        """Stop listening for order MQTT messages."""
        try:
            self.mqtt_client.disconnect()
            logger.info("Stopped MQTT order listener")
        except Exception as e:
            logger.error(f"Error stopping MQTT order listener: {e}")


def main():
    """Main function to demonstrate order MQTT handling."""

    # Example usage
    handler = OrderMQTTHandler()

    # # Example of processing order data directly (for testing)
    # sample_order_data = {
    #     "order_id": "order_c88d7023",
    #     "created_at": 90.0,
    #     "items": [
    #         {"product_type": "P1", "quantity": 1},
    #         {"product_type": "P2", "quantity": 1},
    #     ],
    #     "priority": "medium",
    #     "deadline": 810.0,
    # }

    # print("Processing sample order data...")
    # success = handler.process_order_mqtt_data(sample_order_data)
    # print(f"Order processing result: {'Success' if success else 'Failed'}")

    # Uncomment the following lines to start listening for real MQTT messages
    print("Starting MQTT order listener...")
    handler.start_listening()

    # Keep the program running (uncomment for real usage)
    try:
        while True:
            pass
    except KeyboardInterrupt:
        print("Stopping MQTT order listener...")
        handler.stop_listening()


if __name__ == "__main__":
    main()
