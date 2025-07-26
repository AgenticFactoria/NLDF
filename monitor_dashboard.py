#!/usr/bin/env python3
"""
Factory Monitoring Dashboard
Real-time monitoring of all 3 production lines via MQTT.
"""

import asyncio
import json
import logging
import os
import sys
from datetime import datetime

from dotenv import load_dotenv

# Add current directory to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from config.settings import MQTT_BROKER_HOST, MQTT_BROKER_PORT
from utils.mqtt_client import MQTTClient
from utils.topic_manager import TopicManager

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class FactoryDashboard:
    """Real-time factory monitoring dashboard."""

    def __init__(self, topic_root: str = "AgenticFactoria"):
        self.topic_root = topic_root
        self.topic_manager = TopicManager(topic_root)

        # MQTT client
        self.mqtt_client = MQTTClient(
            host=MQTT_BROKER_HOST,
            port=MQTT_BROKER_PORT,
            client_id=f"factory_dashboard_{datetime.now().timestamp()}",
        )

        # Factory state for all lines
        self.factory_state = {
            "line1": {"stations": {}, "agvs": {}, "conveyors": {}, "alerts": []},
            "line2": {"stations": {}, "agvs": {}, "conveyors": {}, "alerts": []},
            "line3": {"stations": {}, "agvs": {}, "conveyors": {}, "alerts": []},
            "warehouse": {},
            "orders": [],
            "kpi": {},
            "last_updated": datetime.now(),
        }

        self.is_running = False

    def start_monitoring(self):
        """Start MQTT monitoring for all factory components."""
        logger.info("Starting factory monitoring dashboard...")

        try:
            self.mqtt_client.connect()
            self.is_running = True

            # Subscribe to all production lines
            for line_id in ["line1", "line2", "line3"]:
                # Station status
                self.mqtt_client.subscribe(
                    f"{self.topic_root}/{line_id}/station/+/status",
                    lambda topic, payload, line=line_id: self._on_station_status(
                        topic, payload, line
                    ),
                )

                # AGV status
                self.mqtt_client.subscribe(
                    f"{self.topic_root}/{line_id}/agv/+/status",
                    lambda topic, payload, line=line_id: self._on_agv_status(
                        topic, payload, line
                    ),
                )

                # Conveyor status
                self.mqtt_client.subscribe(
                    f"{self.topic_root}/{line_id}/conveyor/+/status",
                    lambda topic, payload, line=line_id: self._on_conveyor_status(
                        topic, payload, line
                    ),
                )

                # Alerts
                self.mqtt_client.subscribe(
                    f"{self.topic_root}/{line_id}/alerts",
                    lambda topic, payload, line=line_id: self._on_alerts(
                        topic, payload, line
                    ),
                )

            # Global subscriptions
            self.mqtt_client.subscribe(
                f"{self.topic_root}/warehouse/+/status", self._on_warehouse_status
            )
            self.mqtt_client.subscribe(
                f"{self.topic_root}/orders/status", self._on_orders
            )
            self.mqtt_client.subscribe(f"{self.topic_root}/kpi/status", self._on_kpi)

            logger.info("✅ Factory monitoring dashboard started successfully")

        except Exception as e:
            logger.error(f"Failed to start monitoring: {e}")
            raise

    def _on_station_status(self, topic: str, payload: bytes, line_id: str):
        """Handle station status updates."""
        try:
            data = json.loads(payload.decode("utf-8"))
            station_id = topic.split("/")[-2]

            self.factory_state[line_id]["stations"][station_id] = {
                **data,
                "last_updated": datetime.now().isoformat(),
            }

        except Exception as e:
            logger.error(f"Error processing station status: {e}")

    def _on_agv_status(self, topic: str, payload: bytes, line_id: str):
        """Handle AGV status updates."""
        try:
            data = json.loads(payload.decode("utf-8"))
            agv_id = topic.split("/")[-2]

            self.factory_state[line_id]["agvs"][agv_id] = {
                **data,
                "last_updated": datetime.now().isoformat(),
            }

        except Exception as e:
            logger.error(f"Error processing AGV status: {e}")

    def _on_conveyor_status(self, topic: str, payload: bytes, line_id: str):
        """Handle conveyor status updates."""
        try:
            data = json.loads(payload.decode("utf-8"))
            conveyor_id = topic.split("/")[-2]

            self.factory_state[line_id]["conveyors"][conveyor_id] = {
                **data,
                "last_updated": datetime.now().isoformat(),
            }

        except Exception as e:
            logger.error(f"Error processing conveyor status: {e}")

    def _on_alerts(self, topic: str, payload: bytes, line_id: str):
        """Handle factory alerts."""
        try:
            data = json.loads(payload.decode("utf-8"))

            alert_entry = {
                **data,
                "line_id": line_id,
                "timestamp": datetime.now().isoformat(),
            }

            self.factory_state[line_id]["alerts"].append(alert_entry)
            # Keep only last 10 alerts per line
            if len(self.factory_state[line_id]["alerts"]) > 10:
                self.factory_state[line_id]["alerts"] = self.factory_state[line_id][
                    "alerts"
                ][-10:]

        except Exception as e:
            logger.error(f"Error processing alert: {e}")

    def _on_warehouse_status(self, topic: str, payload: bytes):
        """Handle warehouse status updates."""
        try:
            data = json.loads(payload.decode("utf-8"))
            self.factory_state["warehouse"] = {
                **data,
                "last_updated": datetime.now().isoformat(),
            }
        except Exception as e:
            logger.error(f"Error processing warehouse status: {e}")

    def _on_orders(self, topic: str, payload: bytes):
        """Handle order updates."""
        try:
            data = json.loads(payload.decode("utf-8"))
            self.factory_state["orders"].append(
                {**data, "timestamp": datetime.now().isoformat()}
            )
            # Keep only last 20 orders
            if len(self.factory_state["orders"]) > 20:
                self.factory_state["orders"] = self.factory_state["orders"][-20:]
        except Exception as e:
            logger.error(f"Error processing order: {e}")

    def _on_kpi(self, topic: str, payload: bytes):
        """Handle KPI updates."""
        try:
            data = json.loads(payload.decode("utf-8"))
            self.factory_state["kpi"] = {
                **data,
                "last_updated": datetime.now().isoformat(),
            }
        except Exception as e:
            logger.error(f"Error processing KPI: {e}")

    def print_dashboard(self):
        """Print current factory status dashboard."""
        os.system("clear" if os.name == "posix" else "cls")  # Clear screen

        print("╔" + "═" * 78 + "╗")
        print("║" + " " * 20 + "SUPCON NLDF Factory Dashboard" + " " * 27 + "║")
        print("╠" + "═" * 78 + "╣")

        # Print timestamp
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"║ Last Updated: {now}" + " " * (78 - 15 - len(now)) + "║")
        print("╠" + "═" * 78 + "╣")

        # Print each production line
        for line_id in ["line1", "line2", "line3"]:
            line_data = self.factory_state[line_id]
            print(
                f"║ {line_id.upper():<8} │ AGVs: {len(line_data['agvs']):<2} │ Stations: {len(line_data['stations']):<2} │ Conveyors: {len(line_data['conveyors']):<2} │ Alerts: {len(line_data['alerts']):<2} ║"
            )

            # AGV status
            for agv_id, agv_data in line_data["agvs"].items():
                status = agv_data.get("status", "unknown")
                battery = agv_data.get("battery_level", 0)
                point = agv_data.get("current_point", "unknown")
                payload_count = len(agv_data.get("payload", []))

                status_icon = (
                    "🟢" if status == "idle" else "🔵" if status == "moving" else "🔴"
                )
                battery_icon = "🔋" if battery > 50 else "🪫" if battery > 20 else "⚠️"

                print(
                    f"║   {status_icon} {agv_id}: {status:<8} {battery_icon} {battery:>3.0f}% @ {point:<3} Load:{payload_count}"
                    + " " * (78 - 45)
                    + "║"
                )

            # Station status (brief)
            station_summary = []
            for station_id, station_data in line_data["stations"].items():
                status = station_data.get("status", "unknown")
                buffer_count = len(station_data.get("buffer", []))
                output_count = len(station_data.get("output_buffer", []))

                if status == "processing":
                    station_summary.append(f"{station_id}:🔄")
                elif buffer_count > 0 or output_count > 0:
                    station_summary.append(
                        f"{station_id}:📦{buffer_count + output_count}"
                    )
                else:
                    station_summary.append(f"{station_id}:💤")

            if station_summary:
                stations_str = " ".join(station_summary)
                print(
                    f"║   Stations: {stations_str:<60}"
                    + " " * (78 - 13 - len(stations_str))
                    + "║"
                )

            # P3 products in Conveyor_CQ
            conveyor_cq = line_data["conveyors"].get("Conveyor_CQ", {})
            upper_buffer = conveyor_cq.get("upper_buffer", [])
            p3_upper = [p for p in upper_buffer if isinstance(p, str) and "prod_3" in p]

            if p3_upper:
                print(
                    f"║   🚨 P3 Products waiting (AGV_2 needed): {len(p3_upper)}"
                    + " " * (78 - 40)
                    + "║"
                )

            print("║" + "─" * 78 + "║")

        # Warehouse status
        warehouse = self.factory_state.get("warehouse", {})
        raw_products = len(warehouse.get("buffer", []))
        stats = warehouse.get("stats", {})

        print(
            f"║ WAREHOUSE │ Raw Materials: {raw_products:<3} │ P1: {stats.get('P1', 0):<2} P2: {stats.get('P2', 0):<2} P3: {stats.get('P3', 0):<2}"
            + " " * (78 - 45)
            + "║"
        )

        # Recent orders
        recent_orders = len(self.factory_state.get("orders", []))
        print(f"║ ORDERS    │ Recent: {recent_orders:<3}" + " " * (78 - 20) + "║")

        # KPI summary
        kpi = self.factory_state.get("kpi", {})
        if kpi:
            print(
                f"║ KPI       │ Score: {kpi.get('total_score', 0):<6.1f}"
                + " " * (78 - 22)
                + "║"
            )

        print("╚" + "═" * 78 + "╝")

        # Recent alerts
        all_alerts = []
        for line_id in ["line1", "line2", "line3"]:
            all_alerts.extend(self.factory_state[line_id]["alerts"])

        if all_alerts:
            print("\n🚨 Recent Alerts:")
            for alert in all_alerts[-5:]:  # Show last 5 alerts
                line = alert.get("line_id", "unknown")
                alert_type = alert.get("alert_type", "unknown")
                timestamp = alert.get("timestamp", "")[:19]  # Remove microseconds
                print(f"   [{timestamp}] {line}: {alert_type}")

    async def run_dashboard(self):
        """Run the monitoring dashboard."""
        self.start_monitoring()

        try:
            while self.is_running:
                self.print_dashboard()
                await asyncio.sleep(2.0)  # Update every 2 seconds

        except KeyboardInterrupt:
            logger.info("Dashboard stopped by user")
        finally:
            self.mqtt_client.disconnect()

    def stop(self):
        """Stop the dashboard."""
        self.is_running = False


async def main():
    """Main function to run the monitoring dashboard."""
    load_dotenv()

    topic_root = os.getenv(
        "TOPIC_ROOT", os.getenv("USERNAME", os.getenv("USER", "NLDF_TEST"))
    )

    dashboard = FactoryDashboard(topic_root)

    try:
        await dashboard.run_dashboard()
    except KeyboardInterrupt:
        logger.info("Monitoring dashboard stopped")
    finally:
        dashboard.stop()


if __name__ == "__main__":
    print("🏭 Starting Factory Monitoring Dashboard...")
    print("Press Ctrl+C to stop")
    print("=" * 80)

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n🛑 Dashboard stopped by user")
    except Exception as e:
        logger.error(f"Dashboard error: {e}")
        sys.exit(1)
