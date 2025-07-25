#!/usr/bin/env python3
"""
Debug MQTT Orders
Listen to the order topic to see if any orders are being published.
"""

import json
import time
import sys
import os

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from config.settings import MQTT_BROKER_HOST, MQTT_BROKER_PORT
from config.topics import NEW_ORDER_TOPIC
from utils.mqtt_client import MQTTClient

def on_order_message(topic: str, payload: bytes):
    """Handle order messages."""
    try:
        payload_str = payload.decode("utf-8")
        order_data = json.loads(payload_str)
        print(f"🔔 ORDER RECEIVED on {topic}:")
        print(f"   Order ID: {order_data.get('order_id', 'unknown')}")
        print(f"   Items: {order_data.get('items', [])}")
        print(f"   Priority: {order_data.get('priority', 'unknown')}")
        print(f"   Payload: {payload_str}")
        print("-" * 50)
    except Exception as e:
        print(f"❌ Error processing order message: {e}")
        print(f"   Raw payload: {payload}")

def main():
    print("🔍 Debug MQTT Orders - Listening for order messages...")
    print(f"📡 Broker: {MQTT_BROKER_HOST}:{MQTT_BROKER_PORT}")
    print(f"📋 Topic: {NEW_ORDER_TOPIC}")
    print("-" * 50)
    
    mqtt_client = MQTTClient(
        host=MQTT_BROKER_HOST,
        port=MQTT_BROKER_PORT,
        client_id="debug_order_listener"
    )
    
    try:
        mqtt_client.connect()
        mqtt_client.subscribe(NEW_ORDER_TOPIC, on_order_message)
        print("✅ Connected and subscribed. Waiting for order messages...")
        print("   (Press Ctrl+C to stop)")
        
        # Keep listening
        while True:
            time.sleep(1)
            
    except KeyboardInterrupt:
        print("\n🛑 Stopping debug listener...")
    except Exception as e:
        print(f"❌ Error: {e}")
    finally:
        mqtt_client.disconnect()
        print("👋 Debug listener stopped")

if __name__ == "__main__":
    main()
